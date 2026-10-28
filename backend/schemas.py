from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=80)
    customer_id: str = Field(min_length=1, max_length=80)
    customer_name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=40)
    order_date: date
    amount: float = Field(gt=0)

class RunCreate(BaseModel):
    order: dict[str, Any] | None = None

    inject: Literal[
        "none",
        "schema_drift",
        "bad_format",
        "missing_field",
        "gemma_simulate",
    ] = "none"

    simulation_prompt: str | None = Field(
        default=None,
        max_length=1000
    )

class PatchOp(BaseModel):
    op: Literal["rename_field", "reformat_value", "set_value"]
    field: str
    to: str | None = None
    format: str | None = None
    value: Any | None = None

class Diagnosis(BaseModel):
    root_cause: str
    failed_step: str
    confidence: float = Field(ge=0, le=1)
    risk: Literal["low", "high"]
    patch_ops: list[PatchOp] = Field(max_length=2)
    source: Literal["rule", "llm", "fallback", "memory"] = "rule"

class ValidationResult(BaseModel):
    passed: bool
    requires_approval: bool = False
    reasons: list[str] = Field(default_factory=list)
    candidate_payload: dict[str, Any] | None = None

class ApprovalRequest(BaseModel):
    field: str | None = None
    value: str | None = None

class BenchmarkRequest(BaseModel):
    repetitions: int = Field(default=3, ge=1, le=10)
    include_human_approval_simulation: bool = True
