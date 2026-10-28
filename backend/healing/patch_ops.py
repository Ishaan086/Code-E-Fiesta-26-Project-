from copy import deepcopy
from datetime import datetime
from typing import Any
from backend.schemas import PatchOp

PROTECTED_FIELDS = {"order_id", "customer_id", "amount"}
ALLOWED_FORMATS = {"ISO8601"}

def apply_patch_ops(payload: dict[str, Any], ops: list[PatchOp]) -> dict[str, Any]:
    result = deepcopy(payload)
    for op in ops:
        if op.field in PROTECTED_FIELDS:
            raise ValueError(f"Protected field cannot be modified: {op.field}")
        if op.op == "rename_field":
            if not op.to:
                raise ValueError("rename_field requires 'to'")
            if op.field not in result:
                raise ValueError(f"Cannot rename missing field: {op.field}")
            if op.to in result:
                raise ValueError(f"Cannot rename into existing field: {op.to}")
            result[op.to] = result.pop(op.field)
        elif op.op == "reformat_value":
            if op.field not in result:
                raise ValueError(f"Cannot reformat missing field: {op.field}")
            if op.format != "ISO8601" or op.field != "order_date":
                raise ValueError("Only order_date -> ISO8601 is supported")
            raw = str(result[op.field])
            try:
                result[op.field] = datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
            except ValueError as exc:
                raise ValueError("Date is not in DD/MM/YYYY format") from exc
        elif op.op == "set_value":
            if op.field not in {"email"}:
                raise ValueError(f"Setting field '{op.field}' is not allowed")
            if op.value is not None:
                result[op.field] = op.value
    return result
