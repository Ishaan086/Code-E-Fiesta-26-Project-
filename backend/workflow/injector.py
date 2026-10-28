from copy import deepcopy
from typing import Any

FAILURE_TYPES = {
    "none": "No failure injected",
    "schema_drift": "Rename phone to phone_number",
    "bad_format": "Change ISO date to DD/MM/YYYY",
    "missing_field": "Remove required email field",
}

DEFAULT_ORDER: dict[str, Any] = {
    "order_id": "ORD-1001",
    "customer_id": "CUS-42",
    "customer_name": "Asha Rao",
    "email": "asha@example.com",
    "phone": "9876543210",
    "order_date": "2026-10-28",
    "amount": 1499.0,
}

def inject_failure(order: dict[str, Any], failure_type: str) -> dict[str, Any]:
    payload = deepcopy(order)
    if failure_type == "none":
        return payload
    if failure_type == "schema_drift":
        if "phone" in payload:
            payload["phone_number"] = payload.pop("phone")
        return payload
    if failure_type == "bad_format":
        value = payload.get("order_date")
        if isinstance(value, str) and len(value) == 10 and value[4] == "-":
            payload["order_date"] = f"{value[8:10]}/{value[5:7]}/{value[:4]}"
        return payload
    if failure_type == "missing_field":
        payload.pop("email", None)
        return payload
    raise ValueError(f"Unknown failure type: {failure_type}")
