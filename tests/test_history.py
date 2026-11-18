"""SQLite performance-history tests (temporary database, no user data)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.history import HistoryStore


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "history.db")


class TestSamples:
    def test_record_and_read(self, store):
        assert store.available
        assert store.record_sample(total_mb=512.5, cpu_percent=3.2,
                                   process_count=4, spotify_running=True)
        samples = store.samples(hours=1)
        assert len(samples) == 1
        assert samples[0]["total_mb"] == 512.5
        assert samples[0]["spotify_running"] is True

    def test_min_interval_throttles_writes(self, store):
        assert store.record_sample(total_mb=100.0, min_interval=30)
        assert store.record_sample(total_mb=200.0, min_interval=30) is False
        assert len(store.samples(hours=1)) == 1

    def test_min_interval_allows_after_window(self, store):
        now = time.time()
        assert store.record_sample(total_mb=100.0, ts=now - 60, min_interval=30)
        assert store.record_sample(total_mb=200.0, ts=now, min_interval=30)
        assert len(store.samples(hours=1)) == 2

    def test_samples_are_ordered_oldest_first(self, store):
        now = time.time()
        store.record_sample(total_mb=1.0, ts=now - 100)
        store.record_sample(total_mb=2.0, ts=now - 50)
        store.record_sample(total_mb=3.0, ts=now - 10)
        values = [s["total_mb"] for s in store.samples(hours=1)]
        assert values == [1.0, 2.0, 3.0]

    def test_latest_sample(self, store):
        now = time.time()
        store.record_sample(total_mb=1.0, ts=now - 100)
        store.record_sample(total_mb=9.0, ts=now - 5)
        latest = store.latest_sample()
        assert latest is not None
        assert latest["total_mb"] == 9.0

    def test_latest_sample_empty(self, store):
        assert store.latest_sample() is None


class TestSessions:
    def test_record_session(self, store):
        session_id = store.record_session(
            started_at="2024-01-01T10:00:00",
            finished_at="2024-01-01T10:01:00",
            profile="safe",
            operations_completed=3,
            operations_skipped=1,
            operations_failed=0,
            cache_freed_mb=12.5,
            before_mb=500.0,
            after_mb=480.0,
            comparable=1,
            spotify_version="1.2.3",
            notes="test",
        )
        assert session_id is not None
        sessions = store.sessions()
        assert len(sessions) == 1
        assert sessions[0]["profile"] == "safe"
        assert sessions[0]["operations_completed"] == 3
        assert sessions[0]["comparable"] == 1

    def test_sessions_newest_first(self, store):
        store.record_session(started_at="old")
        store.record_session(started_at="new")
        sessions = store.sessions()
        assert sessions[0]["started_at"] == "new"


class TestMaintenance:
    def test_prune_removes_old_samples_only(self, store):
        old = time.time() - 10 * 86400
        store.record_sample(total_mb=1.0, ts=old)
        store.record_sample(total_mb=2.0)
        store.record_session(started_at="ancient")
        removed = store.prune(retention_days=5)
        assert removed == 1
        assert len(store.samples(hours=24 * 365)) == 1
        assert len(store.sessions()) == 1, "session records are not pruned with samples"

    def test_prune_disabled_for_zero_days(self, store):
        store.record_sample(total_mb=1.0, ts=time.time() - 10 * 86400)
        assert store.prune(0) == 0
        assert len(store.samples(hours=24 * 365)) == 1

    def test_clear_all(self, store):
        store.record_sample(total_mb=1.0)
        store.record_session(started_at="x")
        assert store.clear_all() is True
        assert store.stats() == {"samples": 0, "sessions": 0}

    def test_stats(self, store):
        store.record_sample(total_mb=1.0)
        store.record_sample(total_mb=2.0)
        store.record_session(started_at="x")
        assert store.stats() == {"samples": 2, "sessions": 1}
