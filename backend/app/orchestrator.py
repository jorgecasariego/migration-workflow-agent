"""Single-agent plan-and-execute orchestrator.

    PENDING -> ANALYZING -> PLANNING -> EXECUTING -> VERIFYING -> COMPLETED
                 \\___________\\___________\\___________\\______-> FAILED

Each transition is checked against ALLOWED_TRANSITIONS. Every LLM call is retried
a bounded number of times, the whole run has a wall-clock deadline, and the state
is saved to the store after every change so the API can report live progress.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from . import prompts
from .config import Settings
from .llm import LLMClient, LLMError, LLMFatalError
from .models import (
    ALLOWED_TRANSITIONS,
    AnalysisOutput,
    ErrorEntry,
    Event,
    MigratedFile,
    Migration,
    MigrationStatus,
    PlanOutput,
    PlanStep,
    StepOutput,
    StepStatus,
    _now,
)
from .store import MigrationStore
from .verification import check_syntax, verify

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class PhaseError(Exception):
    """Aborts the workflow; recorded as an error on the migration."""


class InvalidTransition(Exception):
    pass


class DeadlineExceeded(PhaseError):
    pass


class MigrationOrchestrator:
    def __init__(self, llm: LLMClient, store: MigrationStore, settings: Settings):
        self.llm = llm
        self.store = store
        self.settings = settings
        self._deadline = 0.0

    # ------------------------------------------------------------------ helpers

    def _save(self, m: Migration) -> None:
        m.updated_at = _now()
        self.store.save(m)

    def _event(self, m: Migration, message: str) -> None:
        log.info("[%s] %s", m.id[:8], message)
        m.events.append(Event(at=_now(), message=message))
        self._save(m)

    def transition(self, m: Migration, new: MigrationStatus) -> None:
        if new not in ALLOWED_TRANSITIONS[m.status]:
            raise InvalidTransition(f"{m.status.value} -> {new.value} is not allowed")
        m.status = new
        self._event(m, f"Phase: {new.value}")

    def _check_deadline(self) -> None:
        if time.monotonic() > self._deadline:
            raise DeadlineExceeded(f"Migration exceeded the {self.settings.migration_timeout_s}s time limit")

    def _call(
        self,
        m: Migration,
        label: str,
        build_prompt: Callable[[str | None], str],
        schema: type[T],
        validate: Callable[[T], str | None] | None = None,
    ) -> tuple[T, int]:
        """Call the LLM with bounded retries.

        `validate` returns an error string to reject output (e.g. a syntax error);
        that message is fed back into the next attempt's prompt.
        Returns (result, attempts_used).
        """
        last_error: str | None = None
        for attempt in range(1, self.settings.max_attempts_per_call + 1):
            self._check_deadline()
            try:
                result = self.llm.structured(system=prompts.SYSTEM, prompt=build_prompt(last_error), schema=schema)
            except LLMFatalError as e:
                raise PhaseError(str(e)) from e
            except LLMError as e:
                last_error = str(e)
                self._event(m, f"{label}: attempt {attempt} failed: {last_error}")
                continue
            problem = validate(result) if validate else None
            if problem is None:
                return result, attempt
            last_error = problem
            self._event(m, f"{label}: attempt {attempt} rejected: {problem}")
        raise PhaseError(f"{label} failed after {self.settings.max_attempts_per_call} attempts: {last_error}")

    # ------------------------------------------------------------------ phases

    def analyze(self, m: Migration) -> None:
        def validate(a: AnalysisOutput) -> str | None:
            return None if a.endpoints else "No endpoints were identified; list every route defined in the files"

        m.analysis, _ = self._call(
            m, "Analysis", lambda _e: prompts.analysis_prompt(m.source_files), AnalysisOutput, validate
        )
        self._event(
            m, f"Analysis found {len(m.analysis.endpoints)} endpoint(s), {len(m.analysis.dependencies)} dependenc(ies)"
        )

    def plan(self, m: Migration) -> None:
        assert m.analysis
        analysis = m.analysis

        def build(err: str | None) -> str:
            p = prompts.planning_prompt(m.source_files, analysis, self.settings.max_plan_steps)
            return p + (f"\nYour previous plan was rejected: {err}" if err else "")

        out, _ = self._call(m, "Planning", build, PlanOutput, self.validate_plan)
        m.plan = [PlanStep(**s.model_dump()) for s in out.steps]
        self._event(m, f"Plan created with {len(m.plan)} step(s)")

    def validate_plan(self, plan: PlanOutput) -> str | None:
        steps = plan.steps
        if not steps:
            return "Plan has no steps"
        if len(steps) > self.settings.max_plan_steps:
            return f"Plan has {len(steps)} steps; the maximum is {self.settings.max_plan_steps}"
        seen: set[str] = set()
        for s in steps:
            if s.id in seen:
                return f"Duplicate step id {s.id}"
            for dep in s.depends_on:
                if dep not in seen:  # only earlier steps allowed -> guarantees no cycles
                    return f"Step {s.id} depends on {dep}, which is not an earlier step"
            if not s.target_file.endswith(".py") or s.target_file.startswith("/") or ".." in s.target_file:
                return f"Step {s.id} has invalid target_file {s.target_file!r}"
            seen.add(s.id)
        return None

    def execute(self, m: Migration) -> None:
        assert m.analysis
        analysis = m.analysis
        for step in m.plan:
            failed_deps = [
                d for d in step.depends_on if next(s for s in m.plan if s.id == d).status != StepStatus.COMPLETED
            ]
            if failed_deps:
                step.status = StepStatus.SKIPPED
                step.error = f"Skipped because dependencies did not complete: {', '.join(failed_deps)}"
                m.errors.append(ErrorEntry(phase=m.status, message=step.error, step_id=step.id))
                self._event(m, f"{step.id} skipped")
                continue

            step.status = StepStatus.IN_PROGRESS
            self._event(m, f"{step.id} started: {step.title}")
            generated = list(m.migrated_files)

            def build(err: str | None, step: PlanStep = step, generated: list[MigratedFile] = generated) -> str:
                return prompts.execution_prompt(step, m.source_files, analysis, generated, err)

            def validate(out: StepOutput) -> str | None:
                if not out.code.strip():
                    return "Generated code was empty"
                return check_syntax(out.code)

            try:
                out, attempts = self._call(m, step.id, build, StepOutput, validate)
            except DeadlineExceeded:
                step.status = StepStatus.FAILED
                step.error = "Time limit reached"
                raise
            except PhaseError as e:
                # A failed step does not abort the run: dependents are skipped and
                # verification reports the gap.
                step.status = StepStatus.FAILED
                step.attempts = self.settings.max_attempts_per_call
                step.error = str(e)
                m.errors.append(ErrorEntry(phase=m.status, message=str(e), step_id=step.id))
                self._event(m, f"{step.id} failed")
                continue

            step.attempts, step.notes, step.status = attempts, out.notes, StepStatus.COMPLETED
            m.migrated_files = [f for f in m.migrated_files if f.path != step.target_file]
            m.migrated_files.append(MigratedFile(path=step.target_file, content=out.code, step_id=step.id))
            self._event(m, f"{step.id} completed ({attempts} attempt(s))")

        if not any(s.status == StepStatus.COMPLETED for s in m.plan):
            raise PhaseError("No plan steps completed")

    def verify(self, m: Migration) -> None:
        m.verification = verify(m.analysis, m.plan, m.migrated_files)
        self._event(m, "Verification " + ("passed" if m.verification.passed else "found problems"))

    # ------------------------------------------------------------------ driver

    def run(self, migration_id: str) -> None:
        m = self.store.get(migration_id)
        if m is None:
            return
        self._deadline = time.monotonic() + self.settings.migration_timeout_s
        try:
            for status, phase in (
                (MigrationStatus.ANALYZING, self.analyze),
                (MigrationStatus.PLANNING, self.plan),
                (MigrationStatus.EXECUTING, self.execute),
                (MigrationStatus.VERIFYING, self.verify),
            ):
                self.transition(m, status)
                phase(m)
            self.transition(m, MigrationStatus.COMPLETED)
        except PhaseError as e:
            self._fail(m, str(e))
        except Exception as e:  # noqa: BLE001 - never leave a job stuck in a running state
            log.exception("Unexpected error in migration %s", migration_id)
            self._fail(m, f"Internal error: {type(e).__name__}")

    def _fail(self, m: Migration, message: str) -> None:
        m.errors.append(ErrorEntry(phase=m.status, message=message))
        # Still produce a verification report for whatever was generated.
        if m.migrated_files and m.verification is None:
            try:
                m.verification = verify(m.analysis, m.plan, m.migrated_files)
            except Exception:  # noqa: BLE001
                log.exception("Verification after failure crashed")
        m.status = MigrationStatus.FAILED
        self._event(m, f"Migration failed: {message}")
