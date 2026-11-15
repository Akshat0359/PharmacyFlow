from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, Text, JSON, Float, Integer, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> float:
    return datetime.now(timezone.utc).timestamp()


def uid() -> str:
    return str(uuid4())


class State(StrEnum):
    INTAKE = "intake"
    IDENTITY = "identity_verification"
    LOOKUP = "record_lookup"
    CLARIFICATION = "clarification"
    PREPARATION = "preparation"
    REVIEW = "review"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


TERMINAL = {State.COMPLETED, State.ESCALATED, State.CANCELLED, State.TIMED_OUT, State.REJECTED}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Strict):
    page: int = Field(ge=1)
    text: str = Field(max_length=1000)
    bbox: list[float] | None = None


class ExtractedField(Strict):
    value: str | None
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    issue: str | None = None


FIELD_NAMES = [
    "patient_name",
    "dob",
    "prescriber",
    "medication",
    "strength",
    "directions",
    "quantity",
    "date",
    "refills",
]


class Extraction(Strict):
    fields: dict[str, ExtractedField]
    warnings: list[str] = Field(default_factory=list)
    mode: Literal["fixture", "live"]


class Action(Strict):
    kind: Literal["refill_request", "intake_draft"]
    tenant: str
    patient_id: str
    prescription_id: str | None = None
    fields: dict[str, str | None] = Field(default_factory=dict)


class AgentInput(Strict):
    case_id: str
    tenant: str
    state: State


class AgentOutput(Strict):
    state: State
    reason: str
    evidence: dict = Field(default_factory=dict)


class ModelDecision(Strict):
    decision: Literal["proceed", "escalate"]
    explanation: str = Field(max_length=1500)
    citations: list[str] = Field(max_length=5)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant: Mapped[str] = mapped_column(String, index=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String)
    patient_id: Mapped[str | None] = mapped_column(String, nullable=True)
    demo_account: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    disabled: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    dob: Mapped[str] = mapped_column(String)
    verification_code: Mapped[str] = mapped_column(String)


class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant: Mapped[str] = mapped_column(String, index=True)
    patient_id: Mapped[str] = mapped_column(String, index=True)
    medication: Mapped[str] = mapped_column(String)
    strength: Mapped[str] = mapped_column(String)
    refills: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="active")


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("tenant", "created_by", "request_key"),
        UniqueConstraint("tenant", "document_key", name="uq_case_document"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String, index=True)
    created_by: Mapped[str] = mapped_column(String)
    patient_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default=State.INTAKE)
    request_key: Mapped[str] = mapped_column(String)
    document_key: Mapped[str | None] = mapped_column(String, nullable=True)
    mode: Mapped[str] = mapped_column(String, default="multi")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    action: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    action_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    __mapper_args__ = {"version_id_col": revision, "version_id_generator": False}


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(String, index=True)
    tenant: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str] = mapped_column(String, default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Job(Base):
    __tablename__ = "jobs"
    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="ready", index=True)
    available_at: Mapped[float] = mapped_column(Float, default=now)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String)
    topic: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String)
    embedding: Mapped[list] = mapped_column(JSON)
    effective_from: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    effective_until: Mapped[float | None] = mapped_column(Float, nullable=True)


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String, default="demo")
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class JudgeLabel(Base):
    __tablename__ = "judge_labels"
    __table_args__ = (UniqueConstraint("evaluation_id", "scenario_id", "reviewer"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    evaluation_id: Mapped[str] = mapped_column(String)
    scenario_id: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str] = mapped_column(String)
    score: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text)


class MockRequest(Base):
    __tablename__ = "mock_requests"
    __table_args__ = (
        UniqueConstraint("tenant", "idempotency_key"),
        UniqueConstraint("tenant", "action_hash", name="uq_mock_pending_action"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String)
    patient_id: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String)
    action_hash: Mapped[str] = mapped_column(String)
    action: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="recorded_for_pharmacist")
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Budget(Base):
    __tablename__ = "provider_budgets"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reserved_usd: Mapped[float] = mapped_column(Float, default=0)


class ProviderUsage(Base):
    __tablename__ = "provider_usage"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String, index=True)
    case_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String)
    component: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    pricing_version: Mapped[str] = mapped_column(String)
    usage: Mapped[dict] = mapped_column(JSON)
    estimated_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class RateWindow(Base):
    __tablename__ = "rate_windows"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[float] = mapped_column(Float)
