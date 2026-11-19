"""Test fixtures. FakeLLM stands in for Claude so tests are fast, free and deterministic.

It is used ONLY in tests; the application always uses AnthropicLLM.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.llm import LLMError
from app.models import (
    AnalysisOutput,
    Dependency,
    Endpoint,
    PlanOutput,
    PlanStepDraft,
    SourceFile,
    StepOutput,
)

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


class FakeLLM:
    """Returns responses per schema. A handler may be a value, an Exception, or a callable(prompt)."""

    def __init__(self, handlers: dict[type, list] | None = None):
        self.handlers = handlers or {}
        self.calls: list[tuple[type, str]] = []

    def structured(self, *, system: str, prompt: str, schema: type):
        self.calls.append((schema, prompt))
        queue = self.handlers.get(schema)
        if not queue:
            raise LLMError(f"FakeLLM has no response for {schema.__name__}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(item):
            item = item(prompt)
        if isinstance(item, Exception):
            raise item
        return item


ANALYSIS = AnalysisOutput(
    summary="Users REST API",
    endpoints=[
        Endpoint(method="GET", path="/users", source_file="routes/users.js", description="list"),
        Endpoint(method="GET", path="/users/:id", source_file="routes/users.js", description="get one"),
        Endpoint(method="POST", path="/users", source_file="routes/users.js", description="create"),
        Endpoint(method="DELETE", path="/users/:id", source_file="routes/users.js", description="delete"),
    ],
    dependencies=[Dependency(name="express", purpose="web framework", python_equivalent="fastapi")],
    concerns=["express.json() body parsing"],
)

PLAN = PlanOutput(
    steps=[
        PlanStepDraft(
            id="step-1",
            title="Models",
            description="Pydantic models",
            source_files=["routes/users.js"],
            target_file="app/schemas.py",
            depends_on=[],
        ),
        PlanStepDraft(
            id="step-2",
            title="Users router",
            description="Router",
            source_files=["routes/users.js"],
            target_file="app/routers/users.py",
            depends_on=["step-1"],
        ),
        PlanStepDraft(
            id="step-3",
            title="App",
            description="main",
            source_files=["server.js"],
            target_file="app/main.py",
            depends_on=["step-2"],
        ),
    ]
)

SCHEMAS_PY = """from pydantic import BaseModel


class UserIn(BaseModel):
    name: str
    email: str


class User(UserIn):
    id: int
"""

ROUTER_PY = """from fastapi import APIRouter, HTTPException

from app.schemas import User, UserIn

router = APIRouter(prefix="/users")
_users: list[User] = []


@router.get("")
def list_users() -> list[User]:
    return _users


@router.get("/{user_id}")
def get_user(user_id: int) -> User:
    for u in _users:
        if u.id == user_id:
            return u
    raise HTTPException(status_code=404, detail="User not found")


@router.post("", status_code=201)
def create_user(body: UserIn) -> User:
    user = User(id=len(_users) + 1, **body.model_dump())
    _users.append(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int) -> None:
    _users[:] = [u for u in _users if u.id != user_id]
"""

MAIN_PY = """from fastapi import FastAPI

from app.routers import users

app = FastAPI()
app.include_router(users.router)
"""


def step_responder(prompt: str) -> StepOutput:
    """Picks generated code based on which file the execution prompt asks for."""
    if "file: app/schemas.py" in prompt:
        return StepOutput(code=SCHEMAS_PY, notes="models")
    if "file: app/routers/users.py" in prompt:
        return StepOutput(code=ROUTER_PY, notes="router")
    return StepOutput(code=MAIN_PY, notes="app")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        max_attempts_per_call=3,
        migration_timeout_s=60,
        data_dir=None,
        max_file_bytes=5_000,
        max_total_bytes=8_000,
        max_files=3,
    )


@pytest.fixture
def happy_llm() -> FakeLLM:
    return FakeLLM({AnalysisOutput: [ANALYSIS], PlanOutput: [PLAN], StepOutput: [step_responder]})


@pytest.fixture
def sample_files() -> list[SourceFile]:
    base = SAMPLES / "express-users"
    return [
        SourceFile(path="server.js", content=(base / "server.js").read_text()),
        SourceFile(path="routes/users.js", content=(base / "routes/users.js").read_text()),
    ]
