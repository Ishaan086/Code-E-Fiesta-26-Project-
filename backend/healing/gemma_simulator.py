"""Gemma-powered simulation and diagnosis for synthetic workflow failures.

Gemma suggests structured scenarios and patches only.
Python validates mutations and your existing PS4 healing pipeline remains
responsible for patch validation, risk routing, execution and RepairProof.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.config import GEMMA_API_KEY, GEMMA_MODEL_ID


DEFAULT_SIMULATION_PROMPT = (
    "Invent a realistic, varied issue an AI-powered order automation might create "
    "while mapping data between an order agent, CRM, and email workflow. Use one "
    "or two constrained data mutations; choose an issue that can be safely repaired, "
    "requires human approval, or must be escalated."
)

EXPECTED_FIELDS = {
    "order_id",
    "customer_id",
    "customer_name",
    "email",
    "phone",
    "order_date",
    "amount",
}

# Known aliases are handled by deterministic diagnosis rules.
# Other safe aliases can go through Gemma diagnosis or escalation.
ALIAS_OPTIONS: dict[str, list[str]] = {
    "phone": [
        "phone_number",
        "mobile",
        "contact_number",
        "contactNumber",
    ],
    "customer_name": [
        "full_name",
        "name",
        "customerName",
        "customer_label",
    ],
    "email": [
        "email_address",
        "customer_email",
        "emailAddress",
    ],
    "order_date": [
        "orderDate",
        "date",
        "purchase_date",
    ],
}

SAFE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")

KNOWN_BAD_DATES = {
    "28/10/2026",
    "10-28-2026",
    "2026.10.28",
}


class SimulationMutation(BaseModel):
    """A declarative data mutation, never executable model-generated code."""

    model_config = ConfigDict(extra="forbid")

    op: Literal[
        "rename_field",
        "remove_field",
        "set_invalid_value",
        "add_unexpected_field",
    ]

    field: str = Field(min_length=1, max_length=80)
    to: str | None = Field(default=None, max_length=80)
    value: str | int | float | bool | None = None


class GemmaSimulationSpec(BaseModel):
    """Metadata and allowed data mutations for a generated scenario."""

    model_config = ConfigDict(extra="forbid")

    issue_category: str = Field(min_length=3, max_length=100)
    title: str = Field(min_length=8, max_length=140)
    description: str = Field(min_length=12, max_length=600)
    automation_component: str = Field(min_length=3, max_length=100)
    mutations: list[SimulationMutation] = Field(
        min_length=1,
        max_length=2,
    )


# Google GenerateContent responseSchema uses uppercase type names.
# Optional values are represented as empty strings in model output and
# converted to Python None after parsing.
SIMULATION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "issue_category": {"type": "STRING"},
        "title": {"type": "STRING"},
        "description": {"type": "STRING"},
        "automation_component": {"type": "STRING"},
        "mutations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "op": {
                        "type": "STRING",
                        "enum": [
                            "rename_field",
                            "remove_field",
                            "set_invalid_value",
                            "add_unexpected_field",
                        ],
                    },
                    "field": {"type": "STRING"},
                    "to": {"type": "STRING"},
                    "value": {"type": "STRING"},
                },
                "required": [
                    "op",
                    "field",
                    "to",
                    "value",
                ],
            },
        },
    },
    "required": [
        "issue_category",
        "title",
        "description",
        "automation_component",
        "mutations",
    ],
}


# Diagnosis has a different output structure from simulation generation.
DIAGNOSIS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "root_cause": {"type": "STRING"},
        "failed_step": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
        "risk": {
            "type": "STRING",
            "enum": ["low", "high"],
        },
        "patch_ops": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "op": {
                        "type": "STRING",
                        "enum": [
                            "rename_field",
                            "reformat_value",
                            "set_value",
                        ],
                    },
                    "field": {"type": "STRING"},
                    "to": {"type": "STRING"},
                    "format": {"type": "STRING"},
                    "value": {"type": "STRING"},
                },
                "required": [
                    "op",
                    "field",
                    "to",
                    "format",
                    "value",
                ],
            },
        },
    },
    "required": [
        "root_cause",
        "failed_step",
        "confidence",
        "risk",
        "patch_ops",
    ],
}


class GemmaAPIError(RuntimeError):
    """Readable provider error that never includes the API key."""


def gemma_is_configured() -> bool:
    """Return whether a non-empty API key was loaded at module import time."""
    return bool(GEMMA_API_KEY)


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating simple Markdown fences or surrounding text."""
    text = (text or "").strip()

    if not text:
        raise ValueError("Gemma returned empty text.")

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        result = json.loads(text)

    except json.JSONDecodeError:
        # Locate a complete JSON object using balanced braces.
        # This avoids the over-greedy behavior of a simple regular expression.
        start = text.find("{")

        if start < 0:
            preview = text[:300]
            raise ValueError(
                "Gemma did not return a JSON object. "
                f"Response preview: {preview!r}"
            )

        depth = 0
        in_string = False
        escaped = False
        end = None

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True

            elif char == "{":
                depth += 1

            elif char == "}":
                depth -= 1

                if depth == 0:
                    end = index + 1
                    break

        if end is None:
            preview = text[:300]
            raise ValueError(
                "Gemma response contained an incomplete JSON object. "
                f"Response preview: {preview!r}"
            )

        try:
            result = json.loads(text[start:end])

        except json.JSONDecodeError as exc:
            raise ValueError(
                "Gemma returned malformed JSON. "
                f"Response preview: {text[:300]!r}"
            ) from exc

    if not isinstance(result, dict):
        raise ValueError("Gemma response must be a JSON object.")

    return result


def _call_gemma_json(
    prompt: str,
    *,
    temperature: float = 0.3,
    max_output_tokens: int = 1000,
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the hosted Gemma model and parse its structured JSON response."""

    if not GEMMA_API_KEY:
        raise GemmaAPIError(
            "Gemma API key is missing. "
            "Configure GEMMA_API_KEY in backend/.env."
        )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMMA_MODEL_ID}:generateContent"
    )

    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
        "responseMimeType": "application/json",
        "thinkingConfig": {
            "thinkingLevel": "minimal",
        },
    }

    # IMPORTANT: callers must pass the schema corresponding to their task.
    if response_schema is not None:
        generation_config["responseSchema"] = response_schema

    try:
        response = httpx.post(
            url,
            headers={
                "x-goog-api-key": GEMMA_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": generation_config,
            },
            timeout=45.0,
        )

        if response.is_error:
            try:
                detail = response.json().get("error", {}).get(
                    "message",
                    response.reason_phrase,
                )
            except (ValueError, AttributeError):
                detail = response.reason_phrase

            raise GemmaAPIError(
                f"Gemma API returned HTTP {response.status_code}: "
                f"{str(detail)[:500]}"
            )

        body = response.json()
        candidates = body.get("candidates") or []

        if not candidates:
            feedback = body.get("promptFeedback", {})
            raise GemmaAPIError(
                f"Gemma returned no candidate. Prompt feedback: {feedback}"
            )

        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])

        # Ignore parts explicitly marked as internal thinking, if present.
        response_text = "\n".join(
            part.get("text", "")
            for part in parts
            if (
                isinstance(part, dict)
                and not part.get("thought", False)
                and part.get("text")
            )
        ).strip()

        if not response_text:
            finish_reason = candidate.get("finishReason", "unknown")
            raise GemmaAPIError(
                "Gemma returned no visible text candidate. "
                f"Finish reason: {finish_reason}"
            )

        try:
            return _extract_json(response_text)

        except (ValueError, json.JSONDecodeError) as exc:
            raise GemmaAPIError(str(exc)) from exc

    except httpx.TimeoutException as exc:
        raise GemmaAPIError(
            "Gemma API request timed out. Try again."
        ) from exc

    except httpx.HTTPError as exc:
        raise GemmaAPIError(
            f"Could not reach the Gemma API: {type(exc).__name__}."
        ) from exc


def _normalize_optional_strings(
    data: dict[str, Any],
    list_key: str,
    keys: tuple[str, ...],
) -> None:
    """Convert empty-string placeholders to None after JSON parsing."""

    items = data.get(list_key, [])

    if not isinstance(items, list):
        return

    for item in items:
        if not isinstance(item, dict):
            continue

        for key in keys:
            if item.get(key) == "":
                item[key] = None


def generate_simulation_spec(
    user_prompt: str | None,
    previous_types: list[str] | None = None,
) -> GemmaSimulationSpec:
    """Ask Gemma for a new synthetic incident and declarative mutations."""

    if not GEMMA_API_KEY:
        raise RuntimeError(
            "Gemma is not configured. Add GEMMA_API_KEY to backend/.env "
            "and restart FastAPI."
        )

    request = (
        user_prompt or DEFAULT_SIMULATION_PROMPT
    ).strip()[:1000]

    previous = (previous_types or [])[-5:]

    prompt = f"""
You are a failure-scenario designer for a synthetic AI order-processing
automation. Invent a realistic failure caused by an AI agent or integration
mapper. Try to vary the category, component, field alias, or value from
earlier scenarios.

Canonical order fields:
{json.dumps(sorted(EXPECTED_FIELDS))}

Order constraints:
order_id: string
customer_id: string
customer_name: string
email: valid email
phone: string
order_date: ISO date YYYY-MM-DD
amount: positive number

Allowed operations. Choose one or two:

1. rename_field:
   field is a canonical field that exists in the original payload.
   to is a new, noncanonical alias.

2. remove_field:
   field is an existing canonical field to omit.

3. set_invalid_value:
   field is an existing canonical field. value must violate its schema.

4. add_unexpected_field:
   field is a new, noncanonical field to add. value is a simple string.

The final payload MUST fail Pydantic Order schema validation.

Examples of invalid values:
email = "not-an-email"
order_date = "28/10/2026"
amount = "INR 1,499"

For rename_field, the direction is from canonical to alias.
For example, if customer_name becomes customer_label, return:
field = "customer_name"
to = "customer_label"

Do not generate code, SQL, shell commands, URLs, or executable instructions.
Do not request or include real customer data.
A generated change involving order_id, customer_id, or amount must be
marked for escalation by backend policy.
Missing or invalid email must require human input; never invent an email.

Previous issue categories:
{json.dumps(previous)}

User scenario direction:
{request}

Return ONLY a JSON object matching the supplied response schema.
For unused mutation fields "to" and "value", use an empty string.
Do not use Markdown or explanations outside the JSON object.
""".strip()

    try:
        # FIX: Pass the scenario schema instead of calling the model without it.
        data = _call_gemma_json(
            prompt,
            temperature=0.3,
            max_output_tokens=1000,
            response_schema=SIMULATION_RESPONSE_SCHEMA,
        )

    except GemmaAPIError as exc:
        raise RuntimeError(str(exc)) from exc

    _normalize_optional_strings(
        data,
        "mutations",
        ("to", "value"),
    )

    try:
        spec = GemmaSimulationSpec.model_validate(data)

    except ValidationError as exc:
        raise RuntimeError(
            "Gemma returned an unsupported scenario structure: "
            f"{exc.errors(include_url=False)}"
        ) from exc

    # All generated mutations are validated before any payload is changed.
    for mutation in spec.mutations:
        if mutation.op in {
            "rename_field",
            "remove_field",
            "set_invalid_value",
        }:
            if mutation.field not in EXPECTED_FIELDS:
                raise RuntimeError(
                    "Gemma proposed an unsupported source field: "
                    f"{mutation.field}"
                )

        if mutation.op == "rename_field":
            if (
                not mutation.to
                or not SAFE_KEY_RE.fullmatch(mutation.to)
            ):
                raise RuntimeError(
                    "Gemma proposed an unsafe target field name. "
                    "Generate another scenario."
                )

            if mutation.to in EXPECTED_FIELDS:
                raise RuntimeError(
                    "A field rename must use a noncanonical alias "
                    "to simulate schema drift."
                )

        if mutation.op == "add_unexpected_field":
            if (
                not SAFE_KEY_RE.fullmatch(mutation.field)
                or mutation.field in EXPECTED_FIELDS
            ):
                raise RuntimeError(
                    "Gemma proposed an unsafe or already-known extra field."
                )

        if mutation.op == "set_invalid_value":
            if mutation.value is not None and not isinstance(
                mutation.value,
                (str, int, float, bool),
            ):
                raise RuntimeError(
                    "Mutation values must be simple scalar values."
                )

    return spec


def _known_bad_dates() -> set[str]:
    return set(KNOWN_BAD_DATES)


def apply_simulated_fault(
    order: dict[str, Any],
    spec: GemmaSimulationSpec,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Apply only validated mutations to a synthetic order."""

    from backend.schemas import Order

    payload = deepcopy(order)
    applied: list[dict[str, Any]] = []

    for mutation in spec.mutations:
        field = mutation.field

        if mutation.op == "rename_field":
            if field not in payload:
                raise ValueError(
                    f"Cannot simulate field rename; '{field}' "
                    "is not in the base payload."
                )

            if (
                not mutation.to
                or mutation.to in payload
                or not SAFE_KEY_RE.fullmatch(mutation.to)
            ):
                raise ValueError(
                    f"Cannot safely apply proposed rename for '{field}'."
                )

            payload[mutation.to] = payload.pop(field)

            applied.append({
                "op": mutation.op,
                "from": field,
                "to": mutation.to,
            })

        elif mutation.op == "remove_field":
            if field not in payload:
                raise ValueError(
                    f"Cannot remove absent source field '{field}'."
                )

            payload.pop(field)

            applied.append({
                "op": mutation.op,
                "field": field,
            })

        elif mutation.op == "set_invalid_value":
            if field not in payload:
                raise ValueError(
                    f"Cannot corrupt absent source field '{field}'."
                )

            payload[field] = mutation.value

            applied.append({
                "op": mutation.op,
                "field": field,
                "value": mutation.value,
            })

        elif mutation.op == "add_unexpected_field":
            if (
                field in payload
                or not SAFE_KEY_RE.fullmatch(field)
            ):
                raise ValueError(
                    f"Cannot safely add extra field '{field}'."
                )

            payload[field] = (
                mutation.value
                if mutation.value is not None
                else "AI-generated-value"
            )

            applied.append({
                "op": mutation.op,
                "field": field,
                "value": payload[field],
            })

        else:
            raise ValueError(
                f"Unsupported simulation mutation: {mutation.op}"
            )

    # Reject a scenario if the proposed mutation did not cause a real failure.
    try:
        Order.model_validate(payload)

    except ValidationError:
        pass  # Expected: this simulation must produce an invalid order.

    else:
        raise ValueError(
            "Gemma's proposed mutations still produced a valid order. "
            "Generate another scenario."
        )

    # This is a hint for the operator. The normal backend healing policy
    # independently determines whether repair is allowed.
    if any(
        mutation.op in {"remove_field", "set_invalid_value"}
        and mutation.field == "email"
        for mutation in spec.mutations
    ):
        handling = "HUMAN_APPROVAL"

    elif any(
        mutation.field in {"amount", "order_id", "customer_id"}
        for mutation in spec.mutations
    ):
        handling = "ESCALATE"

    elif all(
        mutation.op == "rename_field"
        and mutation.field in ALIAS_OPTIONS
        and mutation.to in ALIAS_OPTIONS[mutation.field]
        for mutation in spec.mutations
    ):
        handling = "AUTO_REPAIR"

    elif any(
        mutation.op == "set_invalid_value"
        and mutation.field == "order_date"
        and str(mutation.value) in _known_bad_dates()
        for mutation in spec.mutations
    ):
        handling = "AUTO_REPAIR"

    else:
        handling = "AI_DIAGNOSIS_OR_ESCALATION"

    return payload, applied, handling


def diagnose_with_gemma(
    *,
    failed_step: str,
    error: str,
    payload: dict[str, Any],
    expected_fields: list[str],
) -> dict[str, Any] | None:
    """Suggest a repair for an unfamiliar error; never execute it directly."""

    if not gemma_is_configured():
        return None

    prompt = f"""
Diagnose this failure in a synthetic business workflow.
You cannot execute actions. Return only one JSON object matching
the supplied diagnosis response schema.

Allowed patch operations:

1. rename_field:
   field is the existing unexpected alias; to is the canonical target field.

2. reformat_value:
   allowed only for field="order_date", format="ISO8601".

3. set_value:
   allowed only for field="email". Set value to an empty string to request
   human input. Never invent an email address.

If no safe supported repair is clear, return an empty patch_ops array
and risk="high".

Never modify order_id, customer_id, or amount.
Do not suggest executable code, SQL or shell commands.
For unused patch fields "to", "format" and "value", return an empty string.

Failed step:
{failed_step}

Observed validation error:
{error[:1200]}

Synthetic failing payload:
{json.dumps(payload, ensure_ascii=False)}

Expected canonical fields:
{json.dumps(expected_fields)}
""".strip()

    try:
        # FIX: Diagnosis uses its own schema, not the scenario schema.
        data = _call_gemma_json(
            prompt,
            temperature=0.1,
            max_output_tokens=700,
            response_schema=DIAGNOSIS_RESPONSE_SCHEMA,
        )

        _normalize_optional_strings(
            data,
            "patch_ops",
            ("to", "format", "value"),
        )

        # The provider cannot choose its own trust label.
        data["source"] = "llm"

        return data

    except (
        GemmaAPIError,
        ValueError,
        ValidationError,
    ):
        # Caller will apply its existing safe fallback/escalation behavior.
        return None