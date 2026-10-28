from backend.workflow.injector import DEFAULT_ORDER, inject_failure

def test_schema_drift_renames_phone_field():
    result = inject_failure(DEFAULT_ORDER, "schema_drift")
    assert "phone" not in result
    assert result["phone_number"] == DEFAULT_ORDER["phone"]

def test_bad_format_changes_date():
    result = inject_failure(DEFAULT_ORDER, "bad_format")
    assert result["order_date"] == "28/10/2026"

def test_missing_field_removes_email():
    result = inject_failure(DEFAULT_ORDER, "missing_field")
    assert "email" not in result

def test_injector_does_not_mutate_original():
    _ = inject_failure(DEFAULT_ORDER, "schema_drift")
    assert "phone" in DEFAULT_ORDER
    assert "phone_number" not in DEFAULT_ORDER
