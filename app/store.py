"""
Snapshot history in SQLite.

One row per day, replaced on re-sync: the phone is the source of truth and
re-reads the same day many times as data lands late (a watch syncing at
night, a scale in the morning).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import HealthSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    date        TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Store:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def put(self, snap: HealthSnapshot) -> None:
        with closing(self._connect()) as db:
            db.execute(
                "INSERT INTO snapshots (date, payload, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(date) DO UPDATE SET payload=excluded.payload, "
                "updated_at=excluded.updated_at",
                (snap.date, snap.model_dump_json()),
            )
            db.commit()

    def recent(self, limit: int = 14) -> list[HealthSnapshot]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT payload FROM snapshots ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
        out: list[HealthSnapshot] = []
        for r in rows:
            try:
                out.append(HealthSnapshot(**json.loads(r["payload"])))
            except Exception:
                # A row written by an older schema should not break the app.
                continue
        return list(reversed(out))
