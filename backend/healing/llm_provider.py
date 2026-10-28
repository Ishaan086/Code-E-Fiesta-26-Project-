"""Optional IBM watsonx.ai diagnosis fallback. Rules remain the first choice.

Configuration is read from backend/.env. If credentials are absent or the service fails,
callers safely fall back to an explicit fallback diagnosis/escalation path.
"""
import json
import time
import httpx
from backend.config import (
    WATSONX_API_KEY, WATSONX_PROJECT_ID, WATSONX_URL,
    WATSONX_MODEL_ID, WATSONX_API_VERSION,
)

_cached_token: str | None = None
_token_expires_at = 0.0

def _get_iam_token() -> str:
    global _cached_token, _token_expires_at
    if _cached_token and time.time() < _token_expires_at - 60:
        return _cached_token
    response = httpx.post(
        "https://iam.cloud.ibm.com/identity/token",
        data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": WATSONX_API_KEY},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=12.0,
    )
    response.raise_for_status()
    body = response.json()
    _cached_token = body["access_token"]
    _token_expires_at = time.time() + int(body.get("expires_in", 3600))
    return _cached_token

def diagnose_with_watsonx(*, failed_step: str, error: str, payload: dict, expected_fields: list[str]) -> dict | None:
    if not (WATSONX_API_KEY and WATSONX_PROJECT_ID):
        return None
    prompt = {
        "task": "Diagnose a business workflow payload failure and propose at most two safe patch operations.",
        "constraints": [
            "Return JSON only with keys root_cause, failed_step, confidence, risk, patch_ops.",
            "patch op schema: {op: rename_field|reformat_value|set_value, field: string, to?: string, format?: string, value?: string|null}.",
            "Allowed renames must map a present field to an expected field. Allowed format is ISO8601 for order_date only.",
            "Never invent missing customer data. For missing email, propose set_value with value null so a human supplies it.",
            "Never change order_id, customer_id, or amount.",
            "If no safe repair can be proposed, return patch_ops as an empty array and risk high."
        ],
        "failed_step": failed_step,
        "error": error[:1200],
        "payload": payload,
        "expected_fields": expected_fields,
    }
    try:
        token = _get_iam_token()
        url = f"{WATSONX_URL}/ml/v1/text/chat?version={WATSONX_API_VERSION}"
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
            json={
                "model_id": WATSONX_MODEL_ID,
                "project_id": WATSONX_PROJECT_ID,
                "messages": [
                    {"role": "system", "content": "You are a cautious workflow diagnosis component. Output strict JSON only."},
                    {"role": "user", "content": json.dumps(prompt)},
                ],
                "parameters": {"temperature": 0, "max_tokens": 700},
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        content = None
        if data.get("choices"):
            message = data["choices"][0].get("message", {})
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if content is None and data.get("results"):
            content = data["results"][0].get("generated_text")
        if not isinstance(content, str):
            return None
        # Accept JSON surrounded by a Markdown fence, but nothing executable.
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        parsed["source"] = "llm"
        return parsed
    except Exception:
        return None
