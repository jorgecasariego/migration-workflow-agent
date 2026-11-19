"""Runtime configuration, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5"))
    llm_effort: str = field(default_factory=lambda: os.getenv("LLM_EFFORT", "medium"))
    llm_max_tokens: int = field(default_factory=lambda: _int("LLM_MAX_TOKENS", 16000))
    llm_request_timeout_s: int = field(default_factory=lambda: _int("LLM_REQUEST_TIMEOUT_S", 180))

    # Input limits
    max_files: int = field(default_factory=lambda: _int("MAX_FILES", 10))
    max_file_bytes: int = field(default_factory=lambda: _int("MAX_FILE_BYTES", 50_000))
    max_total_bytes: int = field(default_factory=lambda: _int("MAX_TOTAL_BYTES", 150_000))

    # Workflow bounds
    max_plan_steps: int = field(default_factory=lambda: _int("MAX_PLAN_STEPS", 10))
    max_attempts_per_call: int = field(default_factory=lambda: _int("MAX_ATTEMPTS_PER_CALL", 3))
    migration_timeout_s: int = field(default_factory=lambda: _int("MIGRATION_TIMEOUT_S", 900))
    max_concurrent_migrations: int = field(default_factory=lambda: _int("MAX_CONCURRENT_MIGRATIONS", 3))

    # Persistence: when set, each migration is snapshotted as JSON in this directory.
    data_dir: str | None = field(default_factory=lambda: os.getenv("DATA_DIR") or None)

    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:3000"))


def get_settings() -> Settings:
    return Settings()
