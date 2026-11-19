import pytest

from app.llm import LLMError, LLMFatalError
from app.models import (
    AnalysisOutput,
    Migration,
    MigrationStatus,
    PlanOutput,
    PlanStepDraft,
    StepOutput,
    StepStatus,
)
from app.orchestrator import InvalidTransition, MigrationOrchestrator
from app.store import MigrationStore

from .conftest import ANALYSIS, PLAN, FakeLLM, step_responder


def _run(llm, settings, files):
    store = MigrationStore()
    m = Migration(source_framework="express", target_framework="fastapi", source_files=files)
    store.save(m)
    MigrationOrchestrator(llm, store, settings).run(m.id)
    return store.get(m.id)


def test_happy_path_runs_all_phases(happy_llm, settings, sample_files):
    m = _run(happy_llm, settings, sample_files)
    assert m.status == MigrationStatus.COMPLETED, m.errors
    assert [s.status for s in m.plan] == [StepStatus.COMPLETED] * 3
    assert {f.path for f in m.migrated_files} == {"app/schemas.py", "app/routers/users.py", "app/main.py"}
    assert m.verification and m.verification.passed
    phases = [e.message for e in m.events if e.message.startswith("Phase:")]
    assert phases == ["Phase: analyzing", "Phase: planning", "Phase: executing", "Phase: verifying", "Phase: completed"]
    # Original inputs are untouched and stored separately from generated code.
    assert [f.path for f in m.source_files] == ["server.js", "routes/users.js"]


def test_untrusted_source_is_sent_as_tagged_data(happy_llm, settings, sample_files):
    _run(happy_llm, settings, sample_files)
    schema, prompt = happy_llm.calls[0]
    assert schema is AnalysisOutput
    assert '<source_file path="routes/users.js">' in prompt


def test_syntax_error_is_retried_with_feedback(settings, sample_files):
    outputs = iter([StepOutput(code="def broken(:", notes=""), None])

    def responder(prompt):
        nxt = next(outputs, None)
        return nxt if nxt is not None else step_responder(prompt)

    llm = FakeLLM({AnalysisOutput: [ANALYSIS], PlanOutput: [PLAN], StepOutput: [responder]})
    m = _run(llm, settings, sample_files)
    assert m.status == MigrationStatus.COMPLETED
    assert m.plan[0].attempts == 2
    retry_prompt = [p for s, p in llm.calls if s is StepOutput][1]
    assert "previous attempt for this step was rejected: SyntaxError" in retry_prompt


def test_step_failure_skips_dependents_and_verification_reports_it(settings, sample_files):
    def responder(prompt):
        if "file: app/routers/users.py" in prompt:
            raise LLMError("bad output")
        return step_responder(prompt)

    llm = FakeLLM({AnalysisOutput: [ANALYSIS], PlanOutput: [PLAN], StepOutput: [responder]})
    m = _run(llm, settings, sample_files)
    assert [s.status for s in m.plan] == [StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED]
    assert m.plan[1].attempts == settings.max_attempts_per_call
    assert m.status == MigrationStatus.COMPLETED  # workflow finished, but verification failed
    assert m.verification and not m.verification.passed
    assert set(m.verification.failed_steps) == {"step-2", "step-3"}
    assert {e.step_id for e in m.errors} == {"step-2", "step-3"}


def test_invalid_plan_is_rejected_then_retried(settings, sample_files):
    bad = PlanOutput(
        steps=[
            PlanStepDraft(
                id="step-1", title="", description="", source_files=[], target_file="main.py", depends_on=["step-9"]
            )
        ]
    )
    llm = FakeLLM({AnalysisOutput: [ANALYSIS], PlanOutput: [bad, PLAN], StepOutput: [step_responder]})
    m = _run(llm, settings, sample_files)
    assert m.status == MigrationStatus.COMPLETED
    assert any("not an earlier step" in e.message for e in m.events)


def test_bounded_retries_then_failure(settings, sample_files):
    llm = FakeLLM({AnalysisOutput: [LLMError("timeout")]})
    m = _run(llm, settings, sample_files)
    assert m.status == MigrationStatus.FAILED
    assert len(llm.calls) == settings.max_attempts_per_call
    assert "Analysis failed after 3 attempts" in m.errors[-1].message


def test_fatal_error_is_not_retried(settings, sample_files):
    llm = FakeLLM({AnalysisOutput: [LLMFatalError("invalid x-api-key")]})
    m = _run(llm, settings, sample_files)
    assert m.status == MigrationStatus.FAILED
    assert len(llm.calls) == 1


def test_deadline_stops_the_run(settings, sample_files):
    from dataclasses import replace

    llm = FakeLLM({AnalysisOutput: [ANALYSIS], PlanOutput: [PLAN], StepOutput: [step_responder]})
    m = _run(llm, replace(settings, migration_timeout_s=-1), sample_files)
    assert m.status == MigrationStatus.FAILED
    assert "time limit" in m.errors[-1].message


def test_illegal_transition_raises(happy_llm, settings, sample_files):
    store = MigrationStore()
    orch = MigrationOrchestrator(happy_llm, store, settings)
    m = Migration(source_framework="express", target_framework="fastapi", source_files=sample_files)
    with pytest.raises(InvalidTransition):
        orch.transition(m, MigrationStatus.EXECUTING)
