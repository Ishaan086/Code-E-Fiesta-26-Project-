import json
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from pydantic import ValidationError
from backend.models import CRMContact, EmailRecord, Run
from backend.schemas import Order

def verify_repair(db: Session, run: Run, repaired_payload: dict[str, Any]) -> dict[str, Any]:
    original = json.loads(run.input_json)
    invariants: dict[str, bool] = {}
    failures: list[str] = []

    invariants["order_id_unchanged"] = original.get("order_id") == repaired_payload.get("order_id")
    invariants["amount_unchanged"] = original.get("amount") == repaired_payload.get("amount")
    try:
        Order.model_validate(repaired_payload)
        invariants["payload_schema_valid"] = True
    except ValidationError:
        invariants["payload_schema_valid"] = False

    order_id = repaired_payload.get("order_id")
    crm_count = db.scalar(select(func.count(CRMContact.id)).where(CRMContact.order_id == order_id)) or 0
    email_count = db.scalar(select(func.count(EmailRecord.id)).where(EmailRecord.order_id == order_id)) or 0
    invariants["crm_contact_exactly_once"] = crm_count == 1
    invariants["confirmation_exactly_once"] = email_count == 1

    for name, passed in invariants.items():
        if not passed:
            failures.append(name)
    return {"passed": not failures, "invariants": invariants, "failures": failures}
