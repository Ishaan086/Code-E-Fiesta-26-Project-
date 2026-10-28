from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.models import CRMContact, EmailRecord
from backend.schemas import Order

def create_crm_record(db: Session, order: Order) -> dict:
    """Idempotently create one CRM contact per order."""
    existing = db.scalar(select(CRMContact).where(CRMContact.order_id == order.order_id))
    if existing:
        return {"id": existing.id, "order_id": existing.order_id, "created": False, "reason": "already_exists"}
    contact = CRMContact(
        order_id=order.order_id,
        customer_id=order.customer_id,
        customer_name=order.customer_name,
        email=str(order.email),
        phone=order.phone,
    )
    db.add(contact)
    db.flush()
    return {"id": contact.id, "order_id": contact.order_id, "created": True}

def send_confirmation(db: Session, order: Order) -> dict:
    """Mock email sink. No real email is sent. Idempotency key prevents duplicate records."""
    key = f"order-confirmation:{order.order_id}"
    existing = db.scalar(select(EmailRecord).where(EmailRecord.idempotency_key == key))
    if existing:
        return {"id": existing.id, "order_id": existing.order_id, "recorded": False, "reason": "already_exists"}
    email = EmailRecord(order_id=order.order_id, idempotency_key=key, recipient=str(order.email), status="RECORDED")
    db.add(email)
    db.flush()
    return {"id": email.id, "order_id": email.order_id, "recorded": True}
