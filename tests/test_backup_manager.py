"""
Tests for backup and restore system.

All paths are temporary — no real backup directories are created or modified.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.backup_manager import BackupManager, BackupMetadata


class TestBackupManager:
    @pytest.fixture
    def mgr(self, tmp_path):
        return BackupManager(backup_root=tmp_path / "backups")

    def test_create_session_makes_directory(self, mgr):
        session = mgr.create_session()
        assert session.is_dir()

    def test_backup_prefs(self, tmp_path, mgr):
        prefs = tmp_path / "prefs"
        prefs.write_text("key=value\n")
        session = mgr.create_session()
        assert mgr.backup_prefs(session, prefs)
        assert (session / "prefs").exists()

    def test_backup_prefs_missing_file(self, tmp_path, mgr):
        session = mgr.create_session()
        result = mgr.backup_prefs(session, tmp_path / "nonexistent_prefs")
        assert result is False

    def test_restore_prefs(self, tmp_path, mgr):
        prefs = tmp_path / "prefs"
        prefs.write_text("key=original\n")
        session = mgr.create_session()
        mgr.backup_prefs(session, prefs)

        prefs.write_text("key=modified\n")
        assert mgr.restore_prefs(session, prefs)
        assert "original" in prefs.read_text()

    def test_restore_prefs_missing_backup(self, tmp_path, mgr):
        session = mgr.create_session()
        result = mgr.restore_prefs(session, tmp_path / "prefs")
        assert result is False

    def test_backup_registry(self, mgr):
        session = mgr.create_session()
        data = {"startup_entries": {"Spotify": "C:\\Spotify\\Spotify.exe --minimized"}}
        assert mgr.backup_registry(session, data)
        loaded = mgr.restore_registry_data(session)
        assert loaded == data

    def test_registry_backup_missing(self, mgr):
        session = mgr.create_session()
        result = mgr.restore_registry_data(session)
        assert result is None

    def test_backup_shortcuts(self, mgr):
        session = mgr.create_session()
        shortcuts = [{"path": "C:\\x.lnk", "arguments": "--arg1"}]
        assert mgr.backup_shortcuts(session, shortcuts)
        loaded = mgr.restore_shortcuts_data(session)
        assert loaded == shortcuts

    def test_shortcuts_missing(self, mgr):
        session = mgr.create_session()
        result = mgr.restore_shortcuts_data(session)
        assert result is None

    def test_spicetify_backup_restore(self, tmp_path, mgr):
        config = tmp_path / "config-xpui.ini"
        config.write_text("[Setting]\ncurrent_theme=Default\n")
        session = mgr.create_session()
        assert mgr.backup_spicetify(session, config)
        config.write_text("[Setting]\ncurrent_theme=Modified\n")
        assert mgr.restore_spicetify(session, config)
        assert "Default" in config.read_text()

    def test_write_and_read_metadata(self, mgr):
        session = mgr.create_session()
        meta = BackupMetadata(
            created_at=datetime.now().isoformat(),
            prefs_backed_up=True,
            registry_backed_up=True,
        )
        mgr.write_metadata(session, meta)
        loaded = mgr.read_metadata(session)
        assert loaded is not None
        assert loaded.prefs_backed_up is True

    def test_list_sessions_sorted_newest_first(self, mgr):
        s1 = mgr.create_session()
        mgr.write_metadata(s1, BackupMetadata(created_at="2024-01-01"))
        import time; time.sleep(0.01)
        s2 = mgr.create_session()
        mgr.write_metadata(s2, BackupMetadata(created_at="2024-01-02"))
        sessions = mgr.list_sessions()
        assert sessions[0] == s2  # newest first

    def test_get_latest_session(self, mgr):
        s1 = mgr.create_session()
        mgr.write_metadata(s1, BackupMetadata(created_at="x"))
        import time; time.sleep(0.01)
        s2 = mgr.create_session()
        mgr.write_metadata(s2, BackupMetadata(created_at="y"))
        assert mgr.get_latest_session() == s2

    def test_get_latest_session_empty(self, mgr):
        assert mgr.get_latest_session() is None

    def test_validate_session(self, tmp_path, mgr):
        prefs = tmp_path / "prefs"
        prefs.write_text("x=1\n")
        session = mgr.create_session()
        mgr.backup_prefs(session, prefs)
        mgr.backup_registry(session, {})
        mgr.write_metadata(session, BackupMetadata(created_at="now"))
        v = mgr.validate_session(session)
        assert v["prefs"] is True
        assert v["registry"] is True
        assert v["metadata"] is True
        assert v["shortcuts"] is False

    def test_cleanup_old_sessions(self, mgr):
        """Keep only the N most recent sessions; older ones are removed."""
        import time as _time
        # Create 5 sessions with guaranteed unique names by adding a counter suffix
        for i in range(5):
            ts = f"20240101_{i:06d}"
            session = mgr.root / ts
            session.mkdir(parents=True, exist_ok=True)
            mgr.write_metadata(session, BackupMetadata(created_at=f"2024-01-01T{i:02d}:00:00"))
        mgr.cleanup_old_sessions(keep=3)
        assert len(mgr.list_sessions()) == 3
