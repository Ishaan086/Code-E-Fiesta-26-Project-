from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db import Base

def utcnow():
    return datetime.now(timezone.utc)

class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_json: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    inject_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="QUEUED")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    traces: Mapped[list["StepTrace"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="run", cascade="all, delete-orphan")

class StepTrace(Base):
    __tablename__ = "step_traces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    step_name: Mapped[str] = mapped_column(String(80))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30))
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run: Mapped[Run] = relationship(back_populates="traces")

class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    failed_step: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="DETECTED")
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    patch_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run: Mapped[Run] = relationship(back_populates="incidents")
    events: Mapped[list["IncidentEvent"]] = relationship(back_populates="incident", cascade="all, delete-orphan")

class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    incident: Mapped[Incident] = relationship(back_populates="events")

class CRMContact(Base):
    __tablename__ = "crm_contacts"
    __table_args__ = (UniqueConstraint("order_id", name="uq_crm_order_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(80), index=True)
    customer_id: Mapped[str] = mapped_column(String(80))
    customer_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class EmailRecord(Base):
    __tablename__ = "emails"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_email_idempotency_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(80), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    recipient: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="RECORDED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class RepairMemory(Base):
    __tablename__ = "repair_memory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signature: Mapped[str] = mapped_column(String(255), index=True)
    schema_fingerprint: Mapped[str] = mapped_column(String(255))
    patch_json: Mapped[str] = mapped_column(Text)
    verified_uses: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED")
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    trials_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
class AutomationSimulation(Base):
    __tablename__ = "automation_simulations"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_ai_simulation_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id"),
        index=True
    )

    provider: Mapped[str] = mapped_column(
        String(80),
        default="Google Gemma via Gemini API"
    )
    model_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="GENERATING")

    user_prompt: Mapped[str] = mapped_column(Text, default="")
    fault_type: Mapped[str] = mapped_column(String(100), default="pending")
    title: Mapped[str] = mapped_column(String(180), default="Generating scenario")
    description: Mapped[str] = mapped_column(Text, default="")
    automation_component: Mapped[str] = mapped_column(
        String(100),
        default="unknown"
    )

    mutation_json: Mapped[str] = mapped_column(Text, default="{}")
    expected_handling: Mapped[str] = mapped_column(
        String(40),
        default="UNKNOWN"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow
    )