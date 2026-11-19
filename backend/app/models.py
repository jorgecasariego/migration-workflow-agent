"""Pydantic models: API contracts, LLM output schemas and migration state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #


class MigrationStatus(StrEnum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


# Explicit allowed transitions. Any phase may fail; only the happy path moves forward.
ALLOWED_TRANSITIONS: dict[MigrationStatus, set[MigrationStatus]] = {
    MigrationStatus.PENDING: {MigrationStatus.ANALYZING, MigrationStatus.FAILED},
    MigrationStatus.ANALYZING: {MigrationStatus.PLANNING, MigrationStatus.FAILED},
    MigrationStatus.PLANNING: {MigrationStatus.EXECUTING, MigrationStatus.FAILED},
    MigrationStatus.EXECUTING: {MigrationStatus.VERIFYING, MigrationStatus.FAILED},
    MigrationStatus.VERIFYING: {MigrationStatus.COMPLETED, MigrationStatus.FAILED},
    MigrationStatus.COMPLETED: set(),
    MigrationStatus.FAILED: set(),
}

TERMINAL_STATUSES = {MigrationStatus.COMPLETED, MigrationStatus.FAILED}


class StepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # a dependency failed


# --------------------------------------------------------------------------- #
# API input
# --------------------------------------------------------------------------- #


class SourceFile(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    content: str

    @field_validator("path")
    @classmethod
    def _safe_path(cls, v: str) -> str:
        v = v.strip().replace("\\", "/")
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError("path must be relative and must not contain '..'")
        return v


class MigrateRequest(BaseModel):
    source_framework: Literal["express"] = "express"
    target_framework: Literal["fastapi"] = "fastapi"
    files: list[SourceFile] = Field(min_length=1)


class MigrateResponse(BaseModel):
    id: str
    status: MigrationStatus


# --------------------------------------------------------------------------- #
# LLM output schemas (kept flat and constraint-free so they work with
# structured outputs; business rules are validated in code afterwards).
# --------------------------------------------------------------------------- #


class Endpoint(BaseModel):
    method: str = Field(description="HTTP method in upper case, e.g. GET")
    path: str = Field(description="Full Express path including any app.use() mount prefix, e.g. /users/:id")
    source_file: str
    description: str


class Dependency(BaseModel):
    name: str
    purpose: str
    python_equivalent: str = Field(description="Suggested Python package or stdlib module, or 'none needed'")


class AnalysisOutput(BaseModel):
    summary: str
    endpoints: list[Endpoint]
    dependencies: list[Dependency]
    concerns: list[str] = Field(description="Migration risks: middleware, async patterns, error handling, etc.")


class PlanStepDraft(BaseModel):
    id: str = Field(description="Short unique id such as 'step-1'")
    title: str
    description: str
    source_files: list[str] = Field(description="Paths of the original files this step migrates")
    target_file: str = Field(description="Relative path of the Python file this step writes, e.g. app/routers/users.py")
    depends_on: list[str] = Field(description="Ids of steps that must complete first")


class PlanOutput(BaseModel):
    steps: list[PlanStepDraft]


class StepOutput(BaseModel):
    code: str = Field(description="The complete contents of the target Python file")
    notes: str = Field(description="Short notes on decisions or behaviour differences")


# --------------------------------------------------------------------------- #
# Migration state
# --------------------------------------------------------------------------- #


class PlanStep(BaseModel):
    id: str
    title: str
    description: str
    source_files: list[str]
    target_file: str
    depends_on: list[str]
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    notes: str | None = None
    error: str | None = None


class MigratedFile(BaseModel):
    path: str
    content: str
    step_id: str


class FileCheck(BaseModel):
    path: str
    syntax_ok: bool
    error: str | None = None


class EndpointCheck(BaseModel):
    method: str
    path: str
    found: bool
    matched_route: str | None = None


class VerificationReport(BaseModel):
    passed: bool
    files: list[FileCheck]
    endpoints: list[EndpointCheck]
    failed_steps: list[str]
    warnings: list[str]
    disclaimer: str = (
        "Verification checks Python syntax (ast.parse) and route coverage only. "
        "It does not execute the code and does not prove runtime or behavioural equivalence."
    )


class ErrorEntry(BaseModel):
    phase: MigrationStatus
    message: str
    step_id: str | None = None


class Event(BaseModel):
    at: datetime
    message: str


def _now() -> datetime:
    return datetime.now(UTC)


class Migration(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    status: MigrationStatus = MigrationStatus.PENDING
    source_framework: str
    target_framework: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    # Original inputs and generated outputs are stored in separate fields and never mixed.
    source_files: list[SourceFile]
    analysis: AnalysisOutput | None = None
    plan: list[PlanStep] = Field(default_factory=list)
    migrated_files: list[MigratedFile] = Field(default_factory=list)
    verification: VerificationReport | None = None
    errors: list[ErrorEntry] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
