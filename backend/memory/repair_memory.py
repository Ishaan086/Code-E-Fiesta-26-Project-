import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.models import RepairMemory
from backend.schemas import Diagnosis, PatchOp

SCHEMA_FINGERPRINT = "Order:v1:order_id,customer_id,customer_name,email,phone,order_date,amount"

def find_candidate(db: Session, signature: str) -> RepairMemory | None:
    return db.scalar(select(RepairMemory).where(
        RepairMemory.signature == signature,
        RepairMemory.schema_fingerprint == SCHEMA_FINGERPRINT,
    ).order_by(RepairMemory.verified_uses.desc()))

def save_verified_repair(db: Session, signature: str, diagnosis: Diagnosis) -> None:
    # Do not persist a customer-specific set_value such as an email address.
    if any(op.op == "set_value" for op in diagnosis.patch_ops):
        return
    existing = db.scalar(select(RepairMemory).where(
        RepairMemory.signature == signature,
        RepairMemory.schema_fingerprint == SCHEMA_FINGERPRINT,
    ))
    patch_json = json.dumps([op.model_dump(mode="json") for op in diagnosis.patch_ops])
    if existing:
        existing.patch_json = patch_json
        existing.verified_uses += 1
        existing.last_used_at = datetime.now(timezone.utc)
    else:
        db.add(RepairMemory(
            signature=signature,
            schema_fingerprint=SCHEMA_FINGERPRINT,
            patch_json=patch_json,
            verified_uses=1,
            last_used_at=datetime.now(timezone.utc),
        ))
