import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.db import SessionLocal
from backend.models import Incident, Run
from backend.observability import add_event, add_trace, now_utc
from backend.schemas import Diagnosis, Order, PatchOp
from backend.workflow.services import create_crm_record, send_confirmation
from backend.healing.diagnoser import diagnose_failure
from backend.healing.patch_ops import apply_patch_ops
from backend.healing.validator import validate_patch
from backend.healing.repair_proof import verify_repair
from backend.memory.repair_memory import save_verified_repair
import logging

logger = logging.getLogger(__name__)

MAX_RETRIES = 2

def _set_escalated(db: Session, run: Run, incident: Incident, why: str) -> None:
    incident.status = "ESCALATED"
    incident.error = why
    run.status = "ESCALATED"
    run.error = why
    run.ended_at = now_utc()
    add_event(db, incident, "ESCALATED", {"reason": why})
    db.commit()

def _execute_steps(db: Session, run: Run, payload: dict[str, Any], attempt: int) -> tuple[bool, str | None, str | None]:
    """Execute workflow steps. Each successful write is committed and idempotent."""
    started = perf_counter()
    try:
        order = Order.model_validate(payload)
        normalized = order.model_dump(mode="json")
        add_trace(db, run, "receive_order", attempt, "SUCCESS", payload, normalized, started=started)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        # The run record is reloaded after rollback in case the transaction was aborted.
        run = db.get(Run, run.id)
        add_trace(db, run, "receive_order", attempt, "FAILED", payload, None, str(exc), started)
        db.commit()
        return False, "receive_order", str(exc)

    started = perf_counter()
    try:
        crm_result = create_crm_record(db, order)
        add_trace(db, run, "create_crm_record", attempt, "SUCCESS", order.model_dump(mode="json"), crm_result, started=started)
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(Run, run.id)
        add_trace(db, run, "create_crm_record", attempt, "FAILED", order.model_dump(mode="json"), None, str(exc), started)
        db.commit()
        return False, "create_crm_record", str(exc)

    started = perf_counter()
    try:
        email_result = send_confirmation(db, order)
        add_trace(db, run, "send_confirmation", attempt, "SUCCESS", order.model_dump(mode="json"), email_result, started=started)
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(Run, run.id)
        add_trace(db, run, "send_confirmation", attempt, "FAILED", order.model_dump(mode="json"), None, str(exc), started)
        db.commit()
        return False, "send_confirmation", str(exc)
    return True, None, None

def execute_run(
    run_id: int,
    mode: str = "full",
    simulated_approval_value: str | None = None,
) -> None:
    """Background task entrypoint. Modes: full, rule_only, retry_only."""

    logger.info(
        "Regular workflow executor started: run_id=%s, mode=%s",
        run_id,
        mode,
    )

    db = None

    try:
        # Create the database session inside try so failures are logged.
        db = SessionLocal()

        run = db.get(Run, run_id)

        if not run:
            logger.error("Run %s was not found in the database", run_id)
            return

        run.status = "RUNNING"
        run.started_at = now_utc()
        db.commit()

        logger.info("Run %s transitioned to RUNNING", run_id)

        payload = json.loads(run.payload_json)

        succeeded, failed_step, error = _execute_steps(
            db,
            run,
            payload,
            attempt=1,
        )

        if succeeded:
            run = db.get(Run, run_id)

            if run:
                run.status = "SUCCEEDED"
                run.ended_at = now_utc()
                run.error = None
                db.commit()

            logger.info("Run %s completed successfully", run_id)
            return

        run = db.get(Run, run_id)

        if run:
            _handle_failure(
                db,
                run,
                payload,
                failed_step or "unknown",
                error or "Unknown failure",
                mode,
                simulated_approval_value,
            )

            logger.info(
                "Run %s handed to failure handler; failed_step=%s",
                run_id,
                failed_step,
            )

    except Exception as exc:
        logger.exception("Regular workflow failed: run_id=%s", run_id)

        if db is not None:
            try:
                db.rollback()

                run = db.get(Run, run_id)

                if run:
                    run.status = "ERROR"
                    run.error = str(exc)
                    run.ended_at = now_utc()
                    db.commit()

            except Exception:
                db.rollback()
                logger.exception(
                    "Could not persist error status for run_id=%s",
                    run_id,
                )

    finally:
        if db is not None:
            db.close()
def _handle_failure(db: Session, run: Run, payload: dict[str, Any], failed_step: str, error: str,
                    mode: str, simulated_approval_value: str | None = None) -> None:
    incident = Incident(run_id=run.id, failed_step=failed_step, status="DETECTED", error=error)
    db.add(incident)
    db.flush()
    add_event(db, incident, "DETECTED", {"failed_step": failed_step, "error": error[:500]})
    db.commit()

    if mode == "retry_only":
        incident.root_cause = "Retry-only baseline does not diagnose or patch the payload."
        incident.source = "fallback"
        incident.status = "RETRYING"
        db.commit()
        retry_succeeded = False
        retry_error = error
        for retry_number in range(1, MAX_RETRIES + 1):
            run = db.get(Run, run.id)
            run.retry_count = retry_number
            run.status = "RETRYING"
            add_event(db, incident, "RETRYING_WITHOUT_PATCH", {"attempt": retry_number + 1})
            db.commit()
            retry_succeeded, retry_step, retry_error = _execute_steps(db, run, payload, attempt=retry_number + 1)
            if retry_succeeded:
                run = db.get(Run, run.id)
                run.status = "SUCCEEDED"
                run.ended_at = now_utc()
                db.commit()
                return
            if retry_number < MAX_RETRIES:
                run = db.get(Run, run.id)
                add_event(db, incident, "RETRY_ATTEMPT_FAILED", {"attempt": retry_number + 1, "failed_step": retry_step, "error": retry_error})
                db.commit()
        run = db.get(Run, run.id)
        incident = db.get(Incident, incident.id)
        incident.status = "ESCALATED"
        run.status = "FAILED"
        run.error = retry_error or error
        run.ended_at = now_utc()
        add_event(db, incident, "RETRY_ONLY_FAILED", {"retries": MAX_RETRIES, "error": run.error})
        db.commit()
        return

    diagnosis, signature = diagnose_failure(
        db, failed_step=failed_step, error=error, payload=payload,
        allow_llm=(mode == "full"), allow_memory=(mode == "full"),
    )
    incident.signature = signature
    incident.root_cause = diagnosis.root_cause
    incident.confidence = diagnosis.confidence
    incident.risk = diagnosis.risk
    incident.source = diagnosis.source
    incident.patch_json = json.dumps([op.model_dump(mode="json") for op in diagnosis.patch_ops])
    incident.status = "DIAGNOSED"
    add_event(db, incident, "DIAGNOSED", {"root_cause": diagnosis.root_cause, "source": diagnosis.source, "confidence": diagnosis.confidence})
    if diagnosis.patch_ops:
        incident.status = "PATCH_PROPOSED"
        add_event(db, incident, "PATCH_PROPOSED", {"patch_ops": [op.model_dump(mode="json") for op in diagnosis.patch_ops]})
    db.commit()

    if not diagnosis.patch_ops:
        _set_escalated(db, run, incident, "No supported repair was identified.")
        return

    validation = validate_patch(payload, diagnosis)
    incident.validation_json = json.dumps(validation.model_dump(mode="json"), default=str)
    add_event(db, incident, "VALIDATED" if validation.passed else "VALIDATION_FAILED", validation.model_dump(mode="json"))
    db.commit()
    if not validation.passed:
        _set_escalated(db, run, incident, "Patch validation failed: " + "; ".join(validation.reasons))
        return

    human_approved = False
    if validation.requires_approval:
        if simulated_approval_value is None:
            incident.status = "PENDING_APPROVAL"
            run.status = "PENDING_APPROVAL"
            run.error = None
            add_event(db, incident, "PENDING_APPROVAL", {"reason": validation.reasons})
            db.commit()
            return
        # Used only by RecoveryBench to simulate a human-approved correction. Real runs use the approval API.
        try:
            value = str(TypeAdapter(EmailStr).validate_python(simulated_approval_value))
        except ValidationError:
            _set_escalated(db, run, incident, "Benchmark approval fixture was not a valid email address.")
            return
        diagnosis.patch_ops = [PatchOp(**({**op.model_dump(), "value": value} if op.op == "set_value" and op.field == "email" else op.model_dump())) for op in diagnosis.patch_ops]
        incident.patch_json = json.dumps([op.model_dump(mode="json") for op in diagnosis.patch_ops])
        validation = validate_patch(payload, diagnosis)
        incident.validation_json = json.dumps(validation.model_dump(mode="json"), default=str)
        if not validation.passed or validation.requires_approval:
            _set_escalated(db, run, incident, "Corrected-value validation failed.")
            return
        human_approved = True
        incident.status = "APPROVED"
        add_event(db, incident, "APPROVED", {"source": "benchmark_simulation"})
        db.commit()

    low_risk_ops = all(op.op in {"rename_field", "reformat_value"} for op in diagnosis.patch_ops)
    auto_allowed = validation.passed and not validation.requires_approval and diagnosis.risk == "low" and diagnosis.confidence >= 0.8 and low_risk_ops
    if not auto_allowed and not human_approved:
        incident.status = "PENDING_APPROVAL"
        run.status = "PENDING_APPROVAL"
        run.error = None
        add_event(db, incident, "PENDING_APPROVAL", {"reason": "Risk/confidence policy requires a human decision."})
        db.commit()
        return

    _apply_and_retry(db, run, incident, payload, diagnosis, signature, human_approved=human_approved)

def _apply_and_retry(db: Session, run: Run, incident: Incident, payload: dict[str, Any], diagnosis: Diagnosis,
                     signature: str, human_approved: bool = False) -> None:
    try:
        patched = apply_patch_ops(payload, diagnosis.patch_ops)
        # Revalidate the final candidate immediately before any write/side effect.
        normalized_order = Order.model_validate(patched)
        patched = normalized_order.model_dump(mode="json")
    except Exception as exc:
        _set_escalated(db, run, incident, f"Final patch check failed: {exc}")
        return

    run = db.get(Run, run.id)
    incident = db.get(Incident, incident.id)
    run.payload_json = json.dumps(patched)
    incident.patch_json = json.dumps([op.model_dump(mode="json") for op in diagnosis.patch_ops])
    add_event(db, incident, "PATCH_APPLIED", {"patch_ops": [op.model_dump(mode="json") for op in diagnosis.patch_ops], "human_approved": human_approved})
    db.commit()

    succeeded = False
    failed_step = None
    error = None
    # Retry the patched workflow at most MAX_RETRIES times. Each step uses idempotent writes.
    for retry_number in range(1, MAX_RETRIES + 1):
        run = db.get(Run, run.id)
        incident = db.get(Incident, incident.id)
        run.retry_count = retry_number
        run.status = "RETRYING"
        incident.status = "RETRYING"
        add_event(db, incident, "RETRYING", {"attempt": retry_number + 1, "human_approved": human_approved})
        db.commit()
        succeeded, failed_step, error = _execute_steps(db, run, patched, attempt=retry_number + 1)
        if succeeded:
            break
        if retry_number < MAX_RETRIES:
            run = db.get(Run, run.id)
            incident = db.get(Incident, incident.id)
            add_event(db, incident, "RETRY_ATTEMPT_FAILED", {"attempt": retry_number + 1, "failed_step": failed_step, "error": error})
            db.commit()
    run = db.get(Run, run.id)
    incident = db.get(Incident, incident.id)
    if not succeeded:
        _set_escalated(db, run, incident, f"Recovery retries exhausted at {failed_step}: {error}")
        return

    proof = verify_repair(db, run, patched)
    add_event(db, incident, "REPAIR_PROOF", proof)
    if not proof["passed"]:
        incident.validation_json = json.dumps({"patch_validation": "passed", "repair_proof": proof})
        _set_escalated(db, run, incident, "RepairProof failed: " + ", ".join(proof["failures"]))
        return

    incident.status = "RECOVERED"
    incident.resolved_at = now_utc()
    run.status = "RECOVERED"
    run.error = None
    run.ended_at = now_utc()
    incident.validation_json = json.dumps({"patch_validation": "passed", "repair_proof": proof})
    if diagnosis.source in {"rule", "memory"} and not human_approved:
        save_verified_repair(db, signature, diagnosis)
    elif human_approved:
        save_verified_repair(db, signature, diagnosis)
    add_event(db, incident, "RECOVERED", {"repair_proof": proof})
    db.commit()

def approve_and_retry(incident_id: int) -> None:
    db = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        if not incident or incident.status != "APPROVED":
            return
        run = db.get(Run, incident.run_id)
        payload = json.loads(run.payload_json)
        ops = [PatchOp.model_validate(op) for op in json.loads(incident.patch_json or "[]")]
        diagnosis = Diagnosis(
            root_cause=incident.root_cause or "Approved repair", failed_step=incident.failed_step,
            confidence=incident.confidence or 0.0, risk=incident.risk or "high", patch_ops=ops,
            source=incident.source if incident.source in {"rule", "llm", "fallback", "memory"} else "rule",
        )
        validation = validate_patch(payload, diagnosis)
        incident.validation_json = json.dumps(validation.model_dump(mode="json"), default=str)
        if not validation.passed or validation.requires_approval:
            _set_escalated(db, run, incident, "Final validation failed after approval: " + "; ".join(validation.reasons))
            return
        _apply_and_retry(db, run, incident, payload, diagnosis, incident.signature or "approved-repair", human_approved=True)
    finally:
        db.close()

def reject_incident(incident_id: int) -> bool:
    db = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        if not incident or incident.status != "PENDING_APPROVAL":
            return False
        run = db.get(Run, incident.run_id)
        incident.status = "CLOSED_MANUAL"
        incident.resolved_at = now_utc()
        run.status = "CLOSED_MANUAL"
        run.ended_at = now_utc()
        add_event(db, incident, "CLOSED_MANUAL", {"reason": "Rejected by operator"})
        db.commit()
        return True
    finally:
        db.close()
