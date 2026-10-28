from backend.schemas import Diagnosis
from backend.workflow.injector import DEFAULT_ORDER, inject_failure
from backend.healing.validator import validate_patch
from backend.healing.patch_ops import apply_patch_ops

def test_schema_drift_patch_validates():
    payload = inject_failure(DEFAULT_ORDER, "schema_drift")
    diagnosis = Diagnosis(
        root_cause="Field renamed", failed_step="receive_order", confidence=0.98, risk="low",
        source="rule", patch_ops=[{"op": "rename_field", "field": "phone_number", "to": "phone"}],
    )
    result = validate_patch(payload, diagnosis)
    assert result.passed
    assert result.candidate_payload["phone"] == DEFAULT_ORDER["phone"]

def test_bad_format_patch_validates():
    payload = inject_failure(DEFAULT_ORDER, "bad_format")
    diagnosis = Diagnosis(
        root_cause="Date format", failed_step="receive_order", confidence=0.98, risk="low",
        source="rule", patch_ops=[{"op": "reformat_value", "field": "order_date", "format": "ISO8601"}],
    )
    result = validate_patch(payload, diagnosis)
    assert result.passed
    assert result.candidate_payload["order_date"] == "2026-10-28"

def test_missing_email_requires_human_input():
    payload = inject_failure(DEFAULT_ORDER, "missing_field")
    diagnosis = Diagnosis(
        root_cause="Missing email", failed_step="receive_order", confidence=0.99, risk="high",
        source="rule", patch_ops=[{"op": "set_value", "field": "email", "value": None}],
    )
    result = validate_patch(payload, diagnosis)
    assert result.passed
    assert result.requires_approval
    assert "will not invent" in result.reasons[0]

def test_protected_fields_cannot_be_patched():
    payload = dict(DEFAULT_ORDER)
    diagnosis = Diagnosis(
        root_cause="Bad amount", failed_step="receive_order", confidence=0.99, risk="low",
        source="rule", patch_ops=[{"op": "set_value", "field": "amount", "value": 1}],
    )
    result = validate_patch(payload, diagnosis)
    assert not result.passed

def test_patch_apply_does_not_change_original_payload():
    payload = inject_failure(DEFAULT_ORDER, "schema_drift")
    diagnosis = Diagnosis(
        root_cause="Field renamed", failed_step="receive_order", confidence=0.98, risk="low",
        source="rule", patch_ops=[{"op": "rename_field", "field": "phone_number", "to": "phone"}],
    )
    patched = apply_patch_ops(payload, diagnosis.patch_ops)
    assert "phone_number" in payload
    assert "phone" in patched
    assert "phone_number" not in patched
