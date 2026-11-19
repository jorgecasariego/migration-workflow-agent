"""Minimal job store: in-memory dict, optionally snapshotted to JSON files.

Limitations (by design, for a lab): single process only, no locking across
workers, and migrations still running when the process stops are marked failed
when reloaded.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .models import TERMINAL_STATUSES, ErrorEntry, Migration, MigrationStatus

log = logging.getLogger(__name__)


class MigrationStore:
    def __init__(self, data_dir: str | None = None):
        self._items: dict[str, Migration] = {}
        self._lock = threading.Lock()
        self._dir = Path(data_dir) if data_dir else None
        if self._dir:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._load()

    def _load(self) -> None:
        assert self._dir
        for path in self._dir.glob("*.json"):
            try:
                m = Migration.model_validate_json(path.read_text())
            except Exception:  # noqa: BLE001 - skip corrupt snapshots
                log.warning("Skipping unreadable snapshot %s", path)
                continue
            if m.status not in TERMINAL_STATUSES:
                m.errors.append(ErrorEntry(phase=m.status, message="Server restarted while migration was running"))
                m.status = MigrationStatus.FAILED
            self._items[m.id] = m

    def save(self, migration: Migration) -> None:
        snapshot = migration.model_copy(deep=True)
        with self._lock:
            self._items[snapshot.id] = snapshot
            if self._dir:
                (self._dir / f"{snapshot.id}.json").write_text(snapshot.model_dump_json())

    def get(self, migration_id: str) -> Migration | None:
        with self._lock:
            m = self._items.get(migration_id)
            return m.model_copy(deep=True) if m else None

    def count_active(self) -> int:
        with self._lock:
            return sum(1 for m in self._items.values() if m.status not in TERMINAL_STATUSES)
