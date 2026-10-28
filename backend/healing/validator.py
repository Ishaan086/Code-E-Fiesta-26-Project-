from typing import Any
from pydantic import ValidationError
from backend.schemas import Diagnosis, Order, PatchOp, ValidationResult
from backend.healing.patch_ops import PROTECTED_FIELDS, apply_patch_ops


def validate_patch(payload: dict[str, Any], diagnosis: Diagnosis) -> ValidationResult:
    ops = diagnosis.patch_ops
    if not ops:
        return ValidationResult(passed=False, reasons=["Diagnosis contains no repair operations."])
    if len(ops) > 2:
        return ValidationResult(passed=False, reasons=["A patch may contain at most two operations."])

    allowed = {"rename_field", "reformat_value", "set_value"}
    for op in ops:
        if op.op not in allowed:
            return ValidationResult(passed=False, reasons=[f"Operation is not allowlisted: {op.op}"])
        if op.field in PROTECTED_FIELDS:
            return ValidationResult(passed=False, reasons=[f"Protected field cannot be modified: {op.field}"])
        if op.op == "rename_field" and op.to in PROTECTED_FIELDS:
            return ValidationResult(passed=False, reasons=[f"Cannot rename a field into protected field: {op.to}"])
        if op.op == "set_value" and op.field != "email":
            return ValidationResult(passed=False, reasons=[f"Setting {op.field} is not allowed."])
        if op.op == "set_value" and op.value is None:
            # Missing data must be supplied by a human, never hallucinated by the model.
            return ValidationResult(
                passed=True,
                requires_approval=True,
                reasons=[f"Human input is required for '{op.field}'. The system will not invent this value."],
                candidate_payload=payload,
            )

    try:
        candidate = apply_patch_ops(payload, ops)
        Order.model_validate(candidate)
        return ValidationResult(passed=True, candidate_payload=candidate, reasons=["Allowlist, patch limit, protected-field and schema checks passed."])
    except (ValueError, ValidationError) as exc:
        return ValidationResult(passed=False, reasons=[str(exc)])
