import json
from typing import Any
from sqlalchemy.orm import Session
from backend.schemas import Diagnosis
from backend.healing.llm_provider import diagnose_with_watsonx
from backend.memory.repair_memory import find_candidate
from backend.healing.gemma_simulator import diagnose_with_gemma
EXPECTED_FIELDS = ["order_id", "customer_id", "customer_name", "email", "phone", "order_date", "amount"]

def identify_signature(payload: dict[str, Any], error: str) -> str:
    if "phone_number" in payload and "phone" not in payload:
        return "schema_drift:phone_number->phone"
    value = payload.get("order_date")
    if isinstance(value, str) and len(value) == 10 and value[2] == "/" and value[5] == "/":
        return "bad_format:order_date:dd/mm/yyyy"
    if "email" not in payload and "email" in error.lower():
        return "missing_required:email"
    return f"unknown:{error.strip()[:100]}"

def _rule_diagnosis(failed_step: str, signature: str) -> Diagnosis | None:
    if signature == "schema_drift:phone_number->phone":
        return Diagnosis(
            root_cause="The required phone field was renamed to phone_number.", failed_step=failed_step,
            confidence=0.98, risk="low", patch_ops=[{"op": "rename_field", "field": "phone_number", "to": "phone"}], source="rule"
        )
    if signature == "bad_format:order_date:dd/mm/yyyy":
        return Diagnosis(
            root_cause="The order date uses DD/MM/YYYY instead of the required ISO date format.", failed_step=failed_step,
            confidence=0.98, risk="low", patch_ops=[{"op": "reformat_value", "field": "order_date", "format": "ISO8601"}], source="rule"
        )
    if signature == "missing_required:email":
        return Diagnosis(
            root_cause="The required email field is missing; the value must be supplied by a human.", failed_step=failed_step,
            confidence=0.99, risk="high", patch_ops=[{"op": "set_value", "field": "email", "value": None}], source="rule"
        )
    return None

def diagnose_failure(db: Session, *, failed_step: str, error: str, payload: dict[str, Any],
                     allow_llm: bool = True, allow_memory: bool = True) -> tuple[Diagnosis, str]:
    signature = identify_signature(payload, error)
    if allow_memory:
        memory = find_candidate(db, signature)
        if memory:
            try:
                stored_ops = json.loads(memory.patch_json)
                return Diagnosis(
                    root_cause=f"Known failure matched approved repair memory: {signature}", failed_step=failed_step,
                    confidence=0.96, risk="low", patch_ops=stored_ops, source="memory"
                ), signature
            except Exception:
                pass
    rule = _rule_diagnosis(failed_step, signature)
    if rule:
        return rule, signature
    if allow_llm:
    # First attempt: hosted Gemma.
        llm_result = diagnose_with_gemma(
            failed_step=failed_step,
            error=error,
            payload=payload,
            expected_fields=EXPECTED_FIELDS,
    )

    # Optional fallback: IBM watsonx if its credentials are configured.
        if llm_result is None:
            llm_result = diagnose_with_watsonx(
            failed_step=failed_step,
            error=error,
            payload=payload,
            expected_fields=EXPECTED_FIELDS,
        )

        if llm_result:
            try:
                diagnosis = Diagnosis.model_validate(llm_result)
                return diagnosis, signature
            except Exception:
            # Untrusted or malformed output never bypasses fallback handling.
                pass
    return Diagnosis(
        root_cause="No supported repair could be determined with sufficient evidence.",
        failed_step=failed_step, confidence=0.0, risk="high", patch_ops=[], source="fallback"
    ), signature
