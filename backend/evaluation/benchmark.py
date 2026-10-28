import json
from datetime import datetime, timezone
from statistics import mean
from sqlalchemy import select
from backend.db import SessionLocal
from backend.models import BenchmarkRun, Incident, Run
from backend.observability import now_utc
from backend.workflow.injector import DEFAULT_ORDER, inject_failure
from backend.workflow.pipeline import execute_run

FAILURES = ["schema_drift", "bad_format", "missing_field"]
MODES = ["retry_only", "rule_only", "full"]

def _expected_signature(failure: str) -> str:
    return {
        "schema_drift": "schema_drift:phone_number->phone",
        "bad_format": "bad_format:order_date:dd/mm/yyyy",
        "missing_field": "missing_required:email",
    }[failure]

def run_benchmark(benchmark_id: int, repetitions: int = 3, include_human_approval_simulation: bool = True) -> None:
    db = SessionLocal()
    try:
        bench = db.get(BenchmarkRun, benchmark_id)
        if not bench:
            return
        bench.status = "RUNNING"
        db.commit()
    finally:
        db.close()

    trials: list[dict] = []
    counter = 0
    for mode in MODES:
        for failure in FAILURES:
            for rep in range(repetitions):
                counter += 1
                order = dict(DEFAULT_ORDER)
                order["order_id"] = f"BENCH-{benchmark_id}-{counter:03d}"
                order["customer_id"] = f"BENCH-CUS-{counter:03d}"
                order["amount"] = float(1000 + counter)
                mutated = inject_failure(order, failure)
                run_db = SessionLocal()
                try:
                    record = Run(
                        input_json=json.dumps(order), payload_json=json.dumps(mutated),
                        inject_type=failure, status="QUEUED",
                    )
                    run_db.add(record)
                    run_db.commit()
                    run_db.refresh(record)
                    run_id = record.id
                finally:
                    run_db.close()

                approval_fixture = "benchmark@example.com" if failure == "missing_field" and include_human_approval_simulation and mode != "retry_only" else None
                execute_run(run_id, mode=mode, simulated_approval_value=approval_fixture)

                result_db = SessionLocal()
                try:
                    result_run = result_db.get(Run, run_id)
                    incident = result_db.scalar(select(Incident).where(Incident.run_id == run_id).order_by(Incident.id.desc()))
                    incident_events = []
                    if incident:
                        from backend.models import IncidentEvent
                        incident_events = result_db.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == incident.id)).all()
                    patch_was_applied = any(event.event_type == "PATCH_APPLIED" for event in incident_events)
                    proof_passed = False
                    proof_checked = False
                    if incident and incident.validation_json:
                        try:
                            stored = json.loads(incident.validation_json)
                            proof = stored.get("repair_proof")
                            proof_checked = isinstance(proof, dict) and "passed" in proof
                            proof_passed = bool(proof.get("passed", False)) if proof_checked else False
                        except Exception:
                            pass
                    duration_ms = 0.0
                    if result_run and result_run.ended_at and result_run.started_at:
                        start = result_run.started_at
                        end = result_run.ended_at
                        if start.tzinfo is None:
                            start = start.replace(tzinfo=timezone.utc)
                        if end.tzinfo is None:
                            end = end.replace(tzinfo=timezone.utc)
                        duration_ms = max(0.0, (end - start).total_seconds() * 1000)
                    recovered = bool(result_run and result_run.status == "RECOVERED")
                    signature_correct = bool(incident and incident.signature == _expected_signature(failure))
                    # Count only runs with an explicit PATCH_APPLIED audit event.
                    # If RepairProof fails after the patch, it is a false fix even if escalated.
                    patch_applied = patch_was_applied
                    trials.append({
                        "run_id": run_id, "mode": mode, "failure": failure, "repetition": rep + 1,
                        "status": result_run.status if result_run else "MISSING",
                        "diagnosis_correct": signature_correct,
                        "recovered": recovered,
                        "patch_applied": patch_applied,
                        "false_fix": patch_applied and proof_checked and not proof_passed,
                        "proof_checked": proof_checked,
                        "proof_passed": proof_passed,
                        "duration_ms": round(duration_ms, 2),
                    })
                finally:
                    result_db.close()

    metrics: dict[str, dict] = {}
    for mode in MODES:
        subset = [trial for trial in trials if trial["mode"] == mode]
        cases = len(subset)
        diagnosed = sum(1 for trial in subset if trial["diagnosis_correct"])
        recovered = sum(1 for trial in subset if trial["recovered"])
        repairs = sum(1 for trial in subset if trial["patch_applied"])
        false_fixes = sum(1 for trial in subset if trial["false_fix"])
        metrics[mode] = {
            "cases": cases,
            "diagnosis_accuracy_pct": round(100 * diagnosed / cases, 2) if cases else 0,
            "recovery_rate_pct": round(100 * recovered / cases, 2) if cases else 0,
            "false_fix_rate_pct": round(100 * false_fixes / repairs, 2) if repairs else 0,
            "mean_recovery_time_ms": round(mean([t["duration_ms"] for t in subset if t["recovered"]]), 2) if any(t["recovered"] for t in subset) else 0,
            "proof_pass_count": sum(1 for t in subset if t["proof_passed"]),
        }

    db = SessionLocal()
    try:
        bench = db.get(BenchmarkRun, benchmark_id)
        if bench:
            bench.status = "COMPLETED"
            bench.metrics_json = json.dumps(metrics)
            bench.trials_json = json.dumps(trials)
            bench.completed_at = now_utc()
            db.commit()
    except Exception as exc:
        db.rollback()
        bench = db.get(BenchmarkRun, benchmark_id)
        if bench:
            bench.status = "FAILED"
            bench.metrics_json = json.dumps({"error": str(exc)})
            db.commit()
    finally:
        db.close()
