"""
Persistent performance history (SQLite).

Design notes
------------
* Local only.  Nothing is transmitted anywhere.
* One short-lived connection per operation, guarded by a lock, so the GUI
  worker thread and the main thread cannot interleave writes.
* Writes are throttled by the caller (the GUI samples every N seconds) and
  rows are small: a year of 5-minute samples is a few megabytes.
* Retention is configurable; ``prune`` deletes old *samples* only, never
  optimisation session records, unless the user explicitly clears everything.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .app_paths import ensure_dir, history_db
from .logger import get_logger

log = get_logger("history")

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS samples (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            REAL    NOT NULL,
        total_mb      REAL,
        private_mb    REAL,
        cpu_percent   REAL,
        process_count INTEGER,
        spotify_running INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts)",
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at          TEXT NOT NULL,
        finished_at         TEXT,
        profile             TEXT,
        operations_completed INTEGER DEFAULT 0,
        operations_skipped   INTEGER DEFAULT 0,
        operations_failed    INTEGER DEFAULT 0,
        cache_freed_mb       REAL DEFAULT 0,
        before_mb            REAL,
        after_mb             REAL,
        comparable           INTEGER,
        spotify_version      TEXT,
        notes                TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at)",
)


class HistoryStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.path = Path(db_path) if db_path else history_db()
        self._lock = threading.Lock()
        self._last_sample_ts: Optional[float] = None
        self.available = False
        try:
            ensure_dir(self.path.parent)
            with self._connect() as conn:
                for statement in SCHEMA:
                    conn.execute(statement)
            self.available = True
        except sqlite3.Error as exc:
            log.warning(f"Performance history unavailable: {exc}")

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Samples
    # ------------------------------------------------------------------

    def record_sample(
        self,
        *,
        total_mb: float,
        private_mb: Optional[float] = None,
        cpu_percent: Optional[float] = None,
        process_count: int = 0,
        spotify_running: bool = False,
        ts: Optional[float] = None,
        min_interval: float = 0.0,
    ) -> bool:
        """
        Persist one measurement.

        ``min_interval`` skips the write when the previous sample is newer than
        that many seconds — this keeps disk writes bounded even if the GUI is
        refreshed often.
        """
        if not self.available:
            return False
        now = time.time() if ts is None else ts
        with self._lock:
            if (
                min_interval > 0
                and self._last_sample_ts is not None
                and (now - self._last_sample_ts) < min_interval
            ):
                return False
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO samples "
                        "(ts, total_mb, private_mb, cpu_percent, process_count, spotify_running) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (now, float(total_mb), private_mb, cpu_percent,
                         int(process_count), int(bool(spotify_running))),
                    )
                self._last_sample_ts = now
                return True
            except sqlite3.Error as exc:
                log.debug(f"Could not record sample: {exc}")
                return False

    def samples(self, hours: float = 24.0, limit: int = 2000) -> list[dict[str, Any]]:
        """Most recent samples (oldest first) inside the time window."""
        if not self.available:
            return []
        since = time.time() - hours * 3600
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT ts, total_mb, private_mb, cpu_percent, process_count, spotify_running "
                    "FROM samples WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                    (since, int(limit)),
                ).fetchall()
        except sqlite3.Error as exc:
            log.debug(f"Could not read samples: {exc}")
            return []
        rows.reverse()
        return [
            {
                "ts": row[0],
                "total_mb": row[1],
                "private_mb": row[2],
                "cpu_percent": row[3],
                "process_count": row[4],
                "spotify_running": bool(row[5]),
            }
            for row in rows
        ]

    def latest_sample(self) -> Optional[dict[str, Any]]:
        rows = self.samples(hours=24 * 365, limit=1)
        return rows[-1] if rows else None

    # ------------------------------------------------------------------
    # Optimization sessions
    # ------------------------------------------------------------------

    def record_session(self, **fields: Any) -> Optional[int]:
        if not self.available:
            return None
        columns = (
            "started_at", "finished_at", "profile", "operations_completed",
            "operations_skipped", "operations_failed", "cache_freed_mb",
            "before_mb", "after_mb", "comparable", "spotify_version", "notes",
        )
        values = [fields.get(column) for column in columns]
        placeholders = ", ".join("?" for _ in columns)
        try:
            with self._lock, self._connect() as conn:
                cursor = conn.execute(
                    f"INSERT INTO sessions ({', '.join(columns)}) VALUES ({placeholders})",
                    values,
                )
                return int(cursor.lastrowid)
        except sqlite3.Error as exc:
            log.debug(f"Could not record session: {exc}")
            return None

    def sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.available:
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, started_at, finished_at, profile, operations_completed, "
                    "operations_skipped, operations_failed, cache_freed_mb, before_mb, "
                    "after_mb, comparable, spotify_version, notes "
                    "FROM sessions ORDER BY id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        except sqlite3.Error as exc:
            log.debug(f"Could not read sessions: {exc}")
            return []
        keys = (
            "id", "started_at", "finished_at", "profile", "operations_completed",
            "operations_skipped", "operations_failed", "cache_freed_mb", "before_mb",
            "after_mb", "comparable", "spotify_version", "notes",
        )
        return [dict(zip(keys, row)) for row in rows]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune(self, retention_days: int) -> int:
        """
        Delete samples older than ``retention_days``.

        ``retention_days <= 0`` disables pruning.  Returns rows removed.
        """
        if not self.available or retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        try:
            with self._lock, self._connect() as conn:
                cursor = conn.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
                return cursor.rowcount or 0
        except sqlite3.Error as exc:
            log.debug(f"Could not prune history: {exc}")
            return 0

    def clear_samples(self) -> bool:
        return self._delete("DELETE FROM samples")

    def clear_sessions(self) -> bool:
        return self._delete("DELETE FROM sessions")

    def clear_all(self) -> bool:
        return self._delete("DELETE FROM samples") and self._delete("DELETE FROM sessions")

    def _delete(self, statement: str) -> bool:
        if not self.available:
            return False
        try:
            with self._lock, self._connect() as conn:
                conn.execute(statement)
            return True
        except sqlite3.Error as exc:
            log.debug(f"Could not clear history: {exc}")
            return False

    def stats(self) -> dict[str, int]:
        if not self.available:
            return {"samples": 0, "sessions": 0}
        try:
            with self._connect() as conn:
                samples = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
                sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            return {"samples": int(samples), "sessions": int(sessions)}
        except sqlite3.Error:
            return {"samples": 0, "sessions": 0}
