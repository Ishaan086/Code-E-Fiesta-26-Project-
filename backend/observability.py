import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from sqlalchemy.orm import Session
from backend.models import Incident, IncidentEvent, Run, StepTrace

def now_utc():
    return datetime.now(timezone.utc)

def add_event(db: Session, incident: Incident, event_type: str, details: dict[str, Any] | None = None) -> None:
    db.add(IncidentEvent(
        incident_id=incident.id,
        event_type=event_type,
        details_json=json.dumps(details or {}, default=str),
    ))
    db.flush()

def add_trace(db: Session, run: Run, step_name: str, attempt: int, status: str,
              input_data: Any = None, output_data: Any = None, error: str | None = None,
              started: float | None = None) -> None:
    duration_ms = max(0.0, (perf_counter() - started) * 1000) if started is not None else 0.0
    db.add(StepTrace(
        run_id=run.id,
        step_name=step_name,
        attempt=attempt,
        status=status,
        input_json=json.dumps(input_data, default=str) if input_data is not None else None,
        output_json=json.dumps(output_data, default=str) if output_data is not None else None,
        error=error,
        duration_ms=duration_ms,
    ))
    db.flush()
