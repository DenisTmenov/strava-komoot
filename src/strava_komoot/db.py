from __future__ import annotations

import json
import sqlite3
import threading
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
    snapshot        TEXT NOT NULL,
    sync_media      INTEGER NOT NULL DEFAULT 0,
    media_hash      TEXT
);

CREATE TABLE IF NOT EXISTS activities_cache (
    cache_key   TEXT PRIMARY KEY,
    activities  TEXT NOT NULL,
    sport_types TEXT,
    updated_at  TEXT NOT NULL
);
"""

MIGRATIONS = [
    "ALTER TABLE synced ADD COLUMN sync_media INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE synced ADD COLUMN media_hash TEXT",
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
    conn.commit()


def get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _run_migrations(conn)
    return conn


class SyncRepo:
    def __init__(self, db_path: Path | None = None):
        if db_path:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            _run_migrations(self._conn)
        else:
            self._conn = get_db()
        self._lock = threading.Lock()
        self._pending_media: dict[int, bool] = {}

    def _execute(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, params)

    def _commit(self):
        with self._lock:
            self._conn.commit()

    def get(self, strava_id: int) -> dict | None:
        row = self._execute(
            "SELECT * FROM synced WHERE strava_id = ?", (strava_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_snapshot(self, strava_id: int) -> dict | None:
        row = self._execute(
            "SELECT snapshot FROM synced WHERE strava_id = ?", (strava_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["snapshot"])

    def upsert(self, strava_id: int, komoot_tour_id: int, status: str, snapshot: dict) -> None:
        sync_media_val = self._pending_media.pop(strava_id, None)
        if sync_media_val is not None:
            media_flag = 1 if sync_media_val else 0
            self._execute(
                """INSERT INTO synced (strava_id, komoot_tour_id, status, synced_at, snapshot, sync_media)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(strava_id) DO UPDATE SET
                       komoot_tour_id = excluded.komoot_tour_id,
                       status = excluded.status,
                       synced_at = excluded.synced_at,
                       snapshot = excluded.snapshot,
                       sync_media = excluded.sync_media""",
                (
                    strava_id,
                    komoot_tour_id,
                    status,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(snapshot),
                    media_flag,
                ),
            )
        else:
            self._execute(
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
        self._commit()

    def delete(self, strava_id: int) -> None:
        self._execute("DELETE FROM synced WHERE strava_id = ?", (strava_id,))
        self._commit()

    def list_all(self) -> list[dict]:
        rows = self._execute("SELECT * FROM synced ORDER BY strava_id").fetchall()
        return [dict(r) for r in rows]

    def set_sync_media(self, strava_id: int, sync_media: bool) -> None:
        row = self._execute(
            "SELECT 1 FROM synced WHERE strava_id = ?", (strava_id,)
        ).fetchone()
        if row:
            self._execute(
                "UPDATE synced SET sync_media = ? WHERE strava_id = ?",
                (1 if sync_media else 0, strava_id),
            )
            self._commit()
        else:
            self._pending_media[strava_id] = sync_media

    def get_sync_media(self, strava_id: int) -> bool:
        row = self._execute(
            "SELECT sync_media FROM synced WHERE strava_id = ?", (strava_id,)
        ).fetchone()
        if row:
            return bool(row["sync_media"])
        return self._pending_media.get(strava_id, False)

    def pop_pending_media(self, strava_id: int) -> bool | None:
        return self._pending_media.pop(strava_id, None)

    def get_media_hash(self, strava_id: int) -> str | None:
        row = self._execute(
            "SELECT media_hash FROM synced WHERE strava_id = ?", (strava_id,)
        ).fetchone()
        return row["media_hash"] if row else None

    def update_media_hash(self, strava_id: int, media_hash: str | None) -> None:
        self._execute(
            "UPDATE synced SET media_hash = ? WHERE strava_id = ?",
            (media_hash, strava_id),
        )
        self._commit()

    def get_cached_activities(self, cache_key: str, ttl_seconds: int = 300) -> list[dict] | None:
        row = self._execute(
            "SELECT activities, updated_at FROM activities_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        updated = datetime.fromisoformat(row["updated_at"])
        if (datetime.now(timezone.utc) - updated).total_seconds() > ttl_seconds:
            self._execute("DELETE FROM activities_cache WHERE cache_key = ?", (cache_key,))
            self._commit()
            return None
        return json.loads(row["activities"])

    def set_cached_activities(self, cache_key: str, activities: list[dict], sport_types: list[str] | None = None) -> None:
        self._execute(
            """INSERT INTO activities_cache (cache_key, activities, sport_types, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(cache_key) DO UPDATE SET
                   activities = excluded.activities,
                   sport_types = excluded.sport_types,
                   updated_at = excluded.updated_at""",
            (cache_key, json.dumps(activities), json.dumps(sport_types) if sport_types else None, datetime.now(timezone.utc).isoformat()),
        )
        self._commit()

    def get_cached_sport_types(self, cache_key: str, ttl_seconds: int = 300) -> list[str] | None:
        row = self._execute(
            "SELECT sport_types, updated_at FROM activities_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None or row["sport_types"] is None:
            return None
        updated = datetime.fromisoformat(row["updated_at"])
        if (datetime.now(timezone.utc) - updated).total_seconds() > ttl_seconds:
            return None
        return json.loads(row["sport_types"])

    def invalidate_activity_cache(self, cache_key: str) -> None:
        self._execute("DELETE FROM activities_cache WHERE cache_key = ?", (cache_key,))
        self._commit()

    def close(self):
        with self._lock:
            self._conn.close()
