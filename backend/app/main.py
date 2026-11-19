"""FastAPI entry point: POST /migrate, GET /migrations/{id}, GET /health."""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .llm import AnthropicLLM, LLMClient
from .models import MigrateRequest, MigrateResponse, Migration
from .orchestrator import MigrationOrchestrator
from .store import MigrationStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = MigrationStore(settings.data_dir)
    # The LLM client is created lazily so the app can start (and /health works)
    # before an API key is configured.
    llm_holder: dict[str, LLMClient] = {}
    if llm is not None:
        llm_holder["llm"] = llm

    def get_llm() -> LLMClient:
        if "llm" not in llm_holder:
            llm_holder["llm"] = AnthropicLLM(settings)
        return llm_holder["llm"]

    app = FastAPI(title="Migration Workflow Agent", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.store = store
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/migrate", response_model=MigrateResponse, status_code=202)
    def migrate(req: MigrateRequest, background: BackgroundTasks) -> MigrateResponse:
        if len(req.files) > settings.max_files:
            raise HTTPException(413, f"Too many files (max {settings.max_files})")
        paths = [f.path for f in req.files]
        if len(set(paths)) != len(paths):
            raise HTTPException(422, "File paths must be unique")
        total = 0
        for f in req.files:
            size = len(f.content.encode())
            if size == 0:
                raise HTTPException(422, f"{f.path} is empty")
            if size > settings.max_file_bytes:
                raise HTTPException(413, f"{f.path} exceeds {settings.max_file_bytes} bytes")
            total += size
        if total > settings.max_total_bytes:
            raise HTTPException(413, f"Total input exceeds {settings.max_total_bytes} bytes")
        if store.count_active() >= settings.max_concurrent_migrations:
            raise HTTPException(429, "Too many migrations running; try again shortly")

        try:
            llm_client = get_llm()
        except Exception as e:  # e.g. missing ANTHROPIC_API_KEY
            raise HTTPException(503, f"LLM client not configured: {e}") from e

        m = Migration(
            source_framework=req.source_framework,
            target_framework=req.target_framework,
            source_files=req.files,
        )
        store.save(m)
        orchestrator = MigrationOrchestrator(llm_client, store, settings)
        # Sync function -> Starlette runs it in a worker thread after the response is sent.
        background.add_task(orchestrator.run, m.id)
        return MigrateResponse(id=m.id, status=m.status)

    @app.get("/migrations/{migration_id}", response_model=Migration)
    def get_migration(migration_id: str) -> Migration:
        m = store.get(migration_id)
        if m is None:
            raise HTTPException(404, "Migration not found")
        return m

    return app


app = create_app()
