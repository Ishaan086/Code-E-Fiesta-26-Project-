import json
from datetime import datetime, timezone
from typing import Any
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from backend.observability import add_event
from backend.workflow.pipeline import reject_incident
from backend.config import (
    FRONTEND_ORIGIN,
    GEMMA_API_KEY,
    GEMMA_MODEL_ID,
)
from backend.workflow.injector import (
    DEFAULT_ORDER,
    FAILURE_TYPES,
    inject_failure,
)

from backend.models import (
    AutomationSimulation,
    BenchmarkRun,
    CRMContact,
    EmailRecord,
    Incident,
    IncidentEvent,
    RepairMemory,
    Run,
    StepTrace,
)
from backend.schemas import (
    ApprovalRequest,
    BenchmarkRequest,
    Order,
    RunCreate,
)
from backend.db import get_db, init_db, SessionLocal
from backend.workflow.ai_simulation import simulate_and_execute_run
from backend.healing.gemma_simulator import gemma_is_configured

app = FastAPI(title="PS4 Self-Healing Workflow Engine", version="1.0.0", description="AI-assisted, policy-governed recovery for business workflows.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup() -> None:
    init_db()

def _json_load(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default

def _run_dict(db: Session, run: Run) -> dict:
    traces = db.scalars(select(StepTrace).where(StepTrace.run_id == run.id).order_by(StepTrace.id)).all()
    incidents = db.scalars(select(Incident).where(Incident.run_id == run.id).order_by(Incident.id.desc())).all()
    simulation = db.scalar(
        select(AutomationSimulation).where(
            AutomationSimulation.run_id == run.id
        )
    )

    simulation_data = None

    if simulation:
        simulation_data = {
            "id": simulation.id,
            "provider": simulation.provider,
            "model_id": simulation.model_id,
            "status": simulation.status,
            "user_prompt": simulation.user_prompt,
            "fault_type": simulation.fault_type,
            "title": simulation.title,
            "description": simulation.description,
            "automation_component": simulation.automation_component,
            "mutation": _json_load(simulation.mutation_json, {}),
            "expected_handling": simulation.expected_handling,
            "error": simulation.error,
            "created_at": (
                simulation.created_at.isoformat()
                if simulation.created_at else None
            ),
        }
    return {
        "id": run.id, "input": _json_load(run.input_json, {}), "payload": _json_load(run.payload_json, {}),
        "inject_type": run.inject_type, "status": run.status, "error": run.error,
        "retry_count": run.retry_count, "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,"simulation": simulation_data,
        "traces": [{
            "id": t.id, "step_name": t.step_name, "attempt": t.attempt, "status": t.status,
            "input": _json_load(t.input_json), "output": _json_load(t.output_json), "error": t.error,
            "duration_ms": t.duration_ms, "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in traces],
        "incidents": [_incident_dict(db, i, include_events=False) for i in incidents],
    }

def _incident_dict(db: Session, incident: Incident, include_events: bool = True) -> dict:
    result = {
        "id": incident.id, "run_id": incident.run_id, "failed_step": incident.failed_step,
        "status": incident.status, "root_cause": incident.root_cause, "confidence": incident.confidence,
        "risk": incident.risk, "source": incident.source, "signature": incident.signature,
        "patch_ops": _json_load(incident.patch_json, []), "validation": _json_load(incident.validation_json),
        "error": incident.error, "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
    }
    if include_events:
        events = db.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == incident.id).order_by(IncidentEvent.id)).all()
        result["events"] = [{
            "id": e.id, "event_type": e.event_type, "details": _json_load(e.details_json, {}),
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events]
    return result

@app.get("/health")
def health():
    return {"status": "ok", "service": "ps4-self-healing"}
@app.get("/ai-simulator/status")
def ai_simulator_status():
    return {
        "provider": "Google Gemma via Gemini API",
        "model_id": GEMMA_MODEL_ID,
        "configured": gemma_is_configured(),
        "message": (
            "Gemma API key is configured. "
            "Live access and quota still need to be verified."
            if gemma_is_configured()
            else "Add GEMMA_API_KEY to backend/.env and restart FastAPI."
        ),
    }
@app.get("/meta")
def metadata():
    return {"failure_types": FAILURE_TYPES, "workflow_steps": ["receive_order", "create_crm_record", "send_confirmation"], "modes": ["full", "rule_only", "retry_only"]}

@app.post("/runs", status_code=202)
def create_run(
    body: RunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    is_gemma_simulation = body.inject == "gemma_simulate"

    if is_gemma_simulation and not gemma_is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Gemma is not configured. Add GEMMA_API_KEY "
                "to backend/.env and restart FastAPI."
            ),
        )

    # Simulations always use synthetic data, never a caller's real order.
    raw_order = (
        DEFAULT_ORDER
        if is_gemma_simulation
        else (body.order or DEFAULT_ORDER)
    )

    try:
        valid_order = Order.model_validate(raw_order)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False),
        )

    order = valid_order.model_dump(mode="json")

    if is_gemma_simulation:
        import uuid

        suffix = uuid.uuid4().hex[:8].upper()

        # Unique synthetic IDs make side effects easy to audit.
        order["order_id"] = f"GEMMA-{suffix}"
        order["customer_id"] = f"GEMMA-CUS-{suffix}"
        order["customer_name"] = "Demo Customer"
        order["email"] = f"demo-{suffix.lower()}@example.com"
        order["phone"] = "5551234567"

        # The background task will generate the invalid payload.
        initial_payload = order
    else:
        initial_payload = inject_failure(order, body.inject)

    run = Run(
        input_json=json.dumps(order),
        payload_json=json.dumps(initial_payload),
        inject_type=body.inject,
        status="QUEUED",
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    if is_gemma_simulation:
        background_tasks.add_task(
            simulate_and_execute_run,
            run.id,
            body.simulation_prompt,
        )

        message = (
            "Gemma scenario generation queued. "
            "Poll GET /runs/{run_id} for the scenario and result."
        )
    else:
        background_tasks.add_task(execute_run, run.id)
        message = "Run queued."

    return {
        "run_id": run.id,
        "status": run.status,
        "message": message,
    }
@app.get("/runs")
def list_runs(limit: int = 30, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    rows = db.scalars(select(Run).order_by(desc(Run.id)).limit(limit)).all()
    return [_run_dict(db, run) for run in rows]

@app.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_dict(db, run)

@app.get("/incidents")
def list_incidents(status: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    stmt = select(Incident).order_by(desc(Incident.id)).limit(limit)
    if status:
        stmt = select(Incident).where(Incident.status == status.upper()).order_by(desc(Incident.id)).limit(limit)
    incidents = db.scalars(stmt).all()
    return [_incident_dict(db, incident) for incident in incidents]

@app.get("/incidents/{incident_id}")
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _incident_dict(db, incident)

@app.post("/incidents/{incident_id}/approve", status_code=202)
def approve(incident_id: int, body: ApprovalRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail=f"Incident is {incident.status}, not PENDING_APPROVAL")
    patch_ops = _json_load(incident.patch_json, [])
    pending_fields = [op.get("field") for op in patch_ops if op.get("op") == "set_value" and op.get("value") is None]
    if pending_fields:
        field = body.field or pending_fields[0]
        if field not in pending_fields:
            raise HTTPException(status_code=400, detail=f"A human-provided value is required for one of: {pending_fields}")
        if body.value is None:
            raise HTTPException(status_code=400, detail=f"Provide a value for field '{field}'")
        if field == "email":
            try:
                body.value = str(TypeAdapter(EmailStr).validate_python(body.value))
            except ValidationError:
                raise HTTPException(status_code=422, detail="Corrected email is not valid")
        for op in patch_ops:
            if op.get("op") == "set_value" and op.get("field") == field:
                op["value"] = body.value
        incident.patch_json = json.dumps(patch_ops)
    incident.status = "APPROVED"
    add_event(db, incident, "APPROVED", {"approved_by": "operator", "corrected_field": body.field})
    run = db.get(Run, incident.run_id)
    if run:
        run.status = "RETRYING"
    db.commit()
    background_tasks.add_task(approve_and_retry, incident_id)
    return {"incident_id": incident_id, "status": "APPROVED", "message": "Approval recorded; poll the incident and run for recovery status."}

@app.post("/incidents/{incident_id}/reject")
def reject(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail=f"Incident is {incident.status}, not PENDING_APPROVAL")
    success = reject_incident(incident_id)
    if not success:
        raise HTTPException(status_code=409, detail="Could not reject this incident")
    return {"incident_id": incident_id, "status": "CLOSED_MANUAL"}

@app.get("/repair-memory")
def list_repair_memory(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(select(RepairMemory).order_by(desc(RepairMemory.verified_uses), desc(RepairMemory.id)).limit(max(1, min(limit, 100)))).all()
    return [{"id": r.id, "signature": r.signature, "schema_fingerprint": r.schema_fingerprint,
             "patch_ops": _json_load(r.patch_json, []), "verified_uses": r.verified_uses,
             "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

@app.get("/crm-contacts")
def list_contacts(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(select(CRMContact).order_by(desc(CRMContact.id)).limit(max(1, min(limit, 100)))).all()
    return [{"id": x.id, "order_id": x.order_id, "customer_id": x.customer_id, "customer_name": x.customer_name,
             "email": x.email, "phone": x.phone, "created_at": x.created_at.isoformat() if x.created_at else None} for x in rows]

@app.get("/emails")
def list_emails(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(select(EmailRecord).order_by(desc(EmailRecord.id)).limit(max(1, min(limit, 100)))).all()
    return [{"id": x.id, "order_id": x.order_id, "idempotency_key": x.idempotency_key,
             "recipient": x.recipient, "status": x.status, "created_at": x.created_at.isoformat() if x.created_at else None} for x in rows]

@app.post("/benchmark", status_code=202)
def create_benchmark(body: BenchmarkRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    bench = BenchmarkRun(status="QUEUED")
    db.add(bench)
    db.commit()
    db.refresh(bench)
    background_tasks.add_task(run_benchmark, bench.id, body.repetitions, body.include_human_approval_simulation)
    return {"benchmark_id": bench.id, "status": bench.status, "message": "Benchmark queued; poll GET /benchmark/{benchmark_id}."}

@app.get("/benchmark")
def list_benchmarks(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.scalars(select(BenchmarkRun).order_by(desc(BenchmarkRun.id)).limit(max(1, min(limit, 100)))).all()
    return [{"id": x.id, "status": x.status, "metrics": _json_load(x.metrics_json), "created_at": x.created_at.isoformat() if x.created_at else None,
             "completed_at": x.completed_at.isoformat() if x.completed_at else None} for x in rows]

@app.get("/benchmark/{benchmark_id}")
def get_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    bench = db.get(BenchmarkRun, benchmark_id)
    if not bench:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return {"id": bench.id, "status": bench.status, "metrics": _json_load(bench.metrics_json), "trials": _json_load(bench.trials_json, []),
            "created_at": bench.created_at.isoformat() if bench.created_at else None,
            "completed_at": bench.completed_at.isoformat() if bench.completed_at else None}

@app.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    runs = db.scalars(select(Run).order_by(desc(Run.id)).limit(100)).all()
    incidents = db.scalars(select(Incident).order_by(desc(Incident.id)).limit(100)).all()
    pending = sum(1 for i in incidents if i.status == "PENDING_APPROVAL")
    recovered = sum(1 for r in runs if r.status == "RECOVERED")
    escalated = sum(1 for r in runs if r.status in {"ESCALATED", "FAILED", "ERROR"})
    crm_count = len(db.scalars(select(CRMContact)).all())
    email_count = len(db.scalars(select(EmailRecord)).all())
    return {"total_runs": len(runs), "recovered_runs": recovered, "pending_approvals": pending,
            "failed_or_escalated_runs": escalated, "crm_records": crm_count, "email_records": email_count}
