"""API tests, including an end-to-end smoke scenario through HTTP with the fake LLM."""

import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Migration, MigrationStatus
from app.store import MigrationStore


def _client(settings, llm):
    return TestClient(create_app(settings=settings, llm=llm))


def test_e2e_smoke_migrate_sample_and_poll(settings, happy_llm, sample_files):
    client = _client(settings, happy_llm)
    payload = {
        "source_framework": "express",
        "target_framework": "fastapi",
        "files": [f.model_dump() for f in sample_files],
    }
    r = client.post("/migrate", json=payload)
    assert r.status_code == 202
    mid = r.json()["id"]

    # TestClient runs background tasks before returning, but poll like a real client would.
    for _ in range(50):
        body = client.get(f"/migrations/{mid}").json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)

    assert body["status"] == "completed", body["errors"]
    assert len(body["plan"]) == 3 and all(s["status"] == "completed" for s in body["plan"])
    assert body["verification"]["passed"] is True
    assert any(f["path"] == "app/main.py" for f in body["migrated_files"])
    assert body["source_files"][0]["content"] == sample_files[0].content


def test_unknown_migration_404(settings, happy_llm):
    assert _client(settings, happy_llm).get("/migrations/nope").status_code == 404


def test_unsupported_framework_rejected(settings, happy_llm):
    r = _client(settings, happy_llm).post(
        "/migrate",
        json={"source_framework": "django", "target_framework": "fastapi", "files": [{"path": "a.js", "content": "x"}]},
    )
    assert r.status_code == 422


def test_size_limits(settings, happy_llm):
    client = _client(settings, happy_llm)
    big = {"files": [{"path": "a.js", "content": "x" * (settings.max_file_bytes + 1)}]}
    assert client.post("/migrate", json=big).status_code == 413
    many = {"files": [{"path": f"{i}.js", "content": "x"} for i in range(settings.max_files + 1)]}
    assert client.post("/migrate", json=many).status_code == 413
    total = {"files": [{"path": f"{i}.js", "content": "x" * 3000} for i in range(3)]}
    assert client.post("/migrate", json=total).status_code == 413
    assert client.post("/migrate", json={"files": []}).status_code == 422
    assert client.post("/migrate", json={"files": [{"path": "a.js", "content": ""}]}).status_code == 422


def test_path_traversal_rejected(settings, happy_llm):
    r = _client(settings, happy_llm).post("/migrate", json={"files": [{"path": "../etc/passwd", "content": "x"}]})
    assert r.status_code == 422


def test_store_persists_and_marks_interrupted_runs_failed(tmp_path, sample_files):
    store = MigrationStore(str(tmp_path))
    m = Migration(
        source_framework="express",
        target_framework="fastapi",
        source_files=sample_files,
        status=MigrationStatus.EXECUTING,
    )
    store.save(m)
    reloaded = MigrationStore(str(tmp_path)).get(m.id)
    assert reloaded.status == MigrationStatus.FAILED
    assert "restarted" in reloaded.errors[-1].message
