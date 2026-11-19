"""Static verification of generated code. Nothing is ever executed or imported."""

from __future__ import annotations

import ast
import re

from .models import (
    AnalysisOutput,
    EndpointCheck,
    FileCheck,
    MigratedFile,
    PlanStep,
    StepStatus,
    VerificationReport,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def check_syntax(code: str) -> str | None:
    """Return None if the code parses, otherwise a short error message."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError line {e.lineno}: {e.msg}"
    return None


def normalize_path(path: str) -> str:
    """Make Express and FastAPI paths comparable: ':id' and '{user_id}' both become '{}'."""
    path = path.strip() or "/"
    path = re.sub(r":[A-Za-z_][A-Za-z0-9_]*\??", "{}", path)
    path = re.sub(r"\{[^}]*\}", "{}", path)
    path = re.sub(r"/+", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return path if path.startswith("/") else "/" + path


def _str_kwarg(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def extract_routes(code: str) -> list[tuple[str, str]]:
    """Find (METHOD, full_path) for decorators like @router.get("/x") in one module.

    Router prefixes declared as `router = APIRouter(prefix="/users")` are applied.
    `app.include_router(..., prefix=...)` is intentionally not resolved (the prompt
    asks the model to put prefixes on APIRouter); see the fallback matching below.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if fname == "APIRouter":
                prefix = _str_kwarg(node.value, "prefix") or ""
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        prefixes[t.id] = prefix

    routes: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            method = dec.func.attr.lower()
            if method not in HTTP_METHODS:
                continue
            owner = dec.func.value.id if isinstance(dec.func.value, ast.Name) else ""
            sub = ""
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                sub = dec.args[0].value
            else:
                sub = _str_kwarg(dec, "path") or ""
            routes.append((method.upper(), prefixes.get(owner, "") + sub))
    return routes


def verify(
    analysis: AnalysisOutput | None,
    plan: list[PlanStep],
    files: list[MigratedFile],
) -> VerificationReport:
    warnings: list[str] = []

    file_checks = [FileCheck(path=f.path, syntax_ok=(err := check_syntax(f.content)) is None, error=err) for f in files]

    routes: list[tuple[str, str]] = []
    for f in files:
        routes.extend(extract_routes(f.content))
    norm_routes = [(m, normalize_path(p), p) for m, p in routes]

    endpoint_checks: list[EndpointCheck] = []
    for ep in analysis.endpoints if analysis else []:
        method, want = ep.method.upper(), normalize_path(ep.path)
        exact = next((r for r in norm_routes if r[0] == method and r[1] == want), None)
        if exact:
            endpoint_checks.append(EndpointCheck(method=method, path=ep.path, found=True, matched_route=exact[2]))
            continue
        # Fallback: a router mounted with include_router(prefix=...) only shows the suffix.
        suffix = next(
            (r for r in norm_routes if r[0] == method and r[1] != "/" and want.endswith(r[1])),
            None,
        )
        if suffix:
            warnings.append(f"{method} {ep.path} matched only by path suffix '{suffix[2]}' (prefix not resolved)")
        endpoint_checks.append(
            EndpointCheck(method=method, path=ep.path, found=bool(suffix), matched_route=suffix[2] if suffix else None)
        )

    failed_steps = [s.id for s in plan if s.status in (StepStatus.FAILED, StepStatus.SKIPPED)]

    if files and not any("FastAPI(" in f.content for f in files):
        warnings.append("No FastAPI() application instance found in generated files")
    for f in files:
        if re.search(r"\bTODO\b|raise NotImplementedError", f.content):
            warnings.append(f"{f.path} contains TODO or NotImplementedError markers")
    if not files:
        warnings.append("No files were generated")

    passed = (
        bool(files)
        and all(fc.syntax_ok for fc in file_checks)
        and all(ec.found for ec in endpoint_checks)
        and not failed_steps
    )
    return VerificationReport(
        passed=passed,
        files=file_checks,
        endpoints=endpoint_checks,
        failed_steps=failed_steps,
        warnings=warnings,
    )
