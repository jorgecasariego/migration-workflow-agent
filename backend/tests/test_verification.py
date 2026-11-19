from app.models import (
    AnalysisOutput,
    Endpoint,
    MigratedFile,
    PlanStep,
    StepStatus,
)
from app.verification import check_syntax, extract_routes, normalize_path, verify

from .conftest import ANALYSIS, MAIN_PY, ROUTER_PY, SAMPLES


def test_check_syntax_ok_and_error():
    assert check_syntax("x = 1\n") is None
    err = check_syntax("def broken(:\n  pass")
    assert err and err.startswith("SyntaxError line 1")


def test_normalize_path_express_and_fastapi_match():
    assert normalize_path("/users/:id") == normalize_path("/users/{user_id}") == "/users/{}"
    assert normalize_path("/users/") == "/users"
    assert normalize_path("") == "/"


def test_extract_routes_applies_router_prefix():
    routes = extract_routes(ROUTER_PY)
    assert ("GET", "/users") in routes
    assert ("GET", "/users/{user_id}") in routes
    assert ("DELETE", "/users/{user_id}") in routes


def test_extract_routes_never_executes_code(tmp_path):
    marker = tmp_path / "pwned"
    code = f"open({str(marker)!r}, 'w').write('x')\n"
    extract_routes(code)
    check_syntax(code)
    assert not marker.exists()


def _plan(status=StepStatus.COMPLETED):
    return [
        PlanStep(
            id="step-1", title="t", description="d", source_files=[], target_file="a.py", depends_on=[], status=status
        )
    ]


def test_verify_passes_for_complete_migration():
    files = [
        MigratedFile(path="app/routers/users.py", content=ROUTER_PY, step_id="s"),
        MigratedFile(path="app/main.py", content=MAIN_PY, step_id="s"),
    ]
    report = verify(ANALYSIS, _plan(), files)
    assert report.passed, report
    assert all(e.found for e in report.endpoints)
    assert "does not prove" in report.disclaimer


def test_verify_flags_missing_endpoint_syntax_error_and_failed_step():
    analysis = AnalysisOutput(
        summary="",
        dependencies=[],
        concerns=[],
        endpoints=[Endpoint(method="PUT", path="/users/:id", source_file="x", description="")],
    )
    files = [MigratedFile(path="bad.py", content="def (:", step_id="s")]
    report = verify(analysis, _plan(StepStatus.FAILED), files)
    assert not report.passed
    assert report.files[0].syntax_ok is False
    assert report.endpoints[0].found is False
    assert report.failed_steps == ["step-1"]
    assert any("FastAPI()" in w for w in report.warnings)


def test_verify_suffix_fallback_warns():
    code = 'from fastapi import APIRouter\nrouter = APIRouter()\n@router.get("/{id}")\ndef f(id: int): ...\n'
    analysis = AnalysisOutput(
        summary="",
        dependencies=[],
        concerns=[],
        endpoints=[Endpoint(method="GET", path="/users/:id", source_file="x", description="")],
    )
    report = verify(analysis, _plan(), [MigratedFile(path="r.py", content=code, step_id="s")])
    assert report.endpoints[0].found
    assert any("suffix" in w for w in report.warnings)


def test_hand_written_expected_sample_passes_verification():
    base = SAMPLES / "expected-fastapi"
    files = [
        MigratedFile(path=str(p.relative_to(base)), content=p.read_text(), step_id="ref") for p in base.rglob("*.py")
    ]
    analysis = AnalysisOutput(
        summary="",
        dependencies=[],
        concerns=[],
        endpoints=[
            *ANALYSIS.endpoints,
            Endpoint(method="GET", path="/health", source_file="server.js", description=""),
        ],
    )
    report = verify(analysis, _plan(), files)
    assert report.passed, report
