from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_DIR = Path.home() / ".strava_komoot"
DB_PATH = DB_DIR / "sync.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS synced (
    strava_id       INTEGER PRIMARY KEY,
    komoot_tour_id  INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'synced',
    synced_at       TEXT NOT NULL,
    snapshot        TEXT NOT NULL
);
"""


def get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


class SyncRepo:
    def __init__(self):
        self._conn = get_db()

    def get(self, strava_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM synced WHERE strava_id = ?", (strava_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_snapshot(self, strava_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT snapshot FROM synced WHERE strava_id = ?", (strava_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["snapshot"])

    def upsert(self, strava_id: int, komoot_tour_id: int, status: str, snapshot: dict) -> None:
        self._conn.execute(
            """INSERT INTO synced (strava_id, komoot_tour_id, status, synced_at, snapshot)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(strava_id) DO UPDATE SET
                   komoot_tour_id = excluded.komoot_tour_id,
                   status = excluded.status,
                   synced_at = excluded.synced_at,
                   snapshot = excluded.snapshot""",
            (
                strava_id,
                komoot_tour_id,
                status,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(snapshot),
            ),
        )
        self._conn.commit()

    def delete(self, strava_id: int) -> None:
        self._conn.execute("DELETE FROM synced WHERE strava_id = ?", (strava_id,))
        self._conn.commit()

    def list_all(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM synced ORDER BY strava_id").fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()
