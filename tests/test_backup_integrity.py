"""
Backup 2.0: manifests, integrity verification, conflict detection and
containment rules.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.backup_manager import (
    BackupManager,
    BackupMetadata,
    restore_file_checked,
)


@pytest.fixture
def mgr(tmp_path):
    manager = BackupManager(backup_root=tmp_path / "backups")
    return manager


def _session_with_prefs(tmp_path, mgr):
    prefs = tmp_path / "prefs"
    prefs.write_text("hardware_acceleration_mode_enabled=true\nstorage.size=1024\n")
    session = mgr.create_session()
    assert mgr.backup_prefs(session, prefs)
    mgr.write_metadata(session, BackupMetadata(created_at="2024-01-01T00:00:00"))
    return session, prefs


class TestManifest:
    def test_manifest_and_integrity_pass(self, tmp_path, mgr):
        session, _ = _session_with_prefs(tmp_path, mgr)
        assert mgr.write_manifest(session)
        report = mgr.verify_integrity(session)
        assert report.ok is True
        assert report.checked == 1

    def test_tampered_artifact_is_detected(self, tmp_path, mgr):
        session, _ = _session_with_prefs(tmp_path, mgr)
        mgr.write_manifest(session)
        (session / "prefs").write_text("tampered=true\n")
        report = mgr.verify_integrity(session)
        assert report.ok is False
        assert "prefs" in report.mismatched

    def test_missing_artifact_is_detected(self, tmp_path, mgr):
        session, _ = _session_with_prefs(tmp_path, mgr)
        mgr.write_manifest(session)
        (session / "prefs").unlink()
        report = mgr.verify_integrity(session)
        assert report.ok is False
        assert "prefs" in report.missing

    def test_session_without_manifest_reports_no_manifest(self, tmp_path, mgr):
        session, _ = _session_with_prefs(tmp_path, mgr)
        report = mgr.verify_integrity(session)
        assert report.ok is False
        assert "No manifest" in report.detail

    def test_manifest_records_sha256_and_size(self, tmp_path, mgr):
        session, _ = _session_with_prefs(tmp_path, mgr)
        mgr.write_manifest(session)
        data = json.loads((session / "manifest.json").read_text())
        entry = data["files"]["prefs"]
        assert len(entry["sha256"]) == 64
        assert entry["size"] > 0


class TestConflictDetection:
    def test_no_conflict_without_recorded_hash(self, tmp_path, mgr):
        session, prefs = _session_with_prefs(tmp_path, mgr)
        prefs.write_text("changed=later\n")
        assert mgr.has_conflict(session, "prefs", prefs) is False

    def test_conflict_when_file_changed_after_optimisation(self, tmp_path, mgr):
        session, prefs = _session_with_prefs(tmp_path, mgr)
        mgr.update_post_write_hash(session, "prefs", "0" * 64)
        assert mgr.has_conflict(session, "prefs", prefs) is True

    def test_restore_refuses_on_conflict(self, tmp_path, mgr):
        session, prefs = _session_with_prefs(tmp_path, mgr)
        mgr.update_post_write_hash(session, "prefs", "0" * 64)
        assert mgr.restore_prefs(session, prefs) is False
        assert mgr.last_conflict
        assert "hardware_acceleration" in prefs.read_text()

    def test_restore_can_override_conflict_explicitly(self, tmp_path, mgr):
        session, prefs = _session_with_prefs(tmp_path, mgr)
        mgr.update_post_write_hash(session, "prefs", "0" * 64)
        assert mgr.restore_prefs(session, prefs, allow_conflict=True) is True
        assert "hardware_acceleration_mode_enabled=true" in prefs.read_text()

    def test_no_conflict_when_hash_matches(self, tmp_path, mgr):
        session, prefs = _session_with_prefs(tmp_path, mgr)
        from src.core.prefs_manager import PrefsManager
        mgr.update_post_write_hash(session, "prefs", PrefsManager(prefs).sha256())
        assert mgr.has_conflict(session, "prefs", prefs) is False


class TestRetentionAndDeletion:
    def test_zero_retention_never_deletes(self, tmp_path, mgr):
        for index in range(3):
            session = mgr.root / f"2024010{index}_120000"
            session.mkdir(parents=True)
            mgr.write_metadata(session, BackupMetadata(created_at=str(index)))
        mgr.cleanup_old_sessions(keep=0)
        assert len(mgr.list_sessions()) == 3
        mgr.cleanup_old_sessions()
        assert len(mgr.list_sessions()) == 3

    def test_explicit_retention_prunes_oldest(self, tmp_path, mgr):
        for index in range(4):
            session = mgr.root / f"2024010{index}_120000"
            session.mkdir(parents=True)
            mgr.write_metadata(session, BackupMetadata(created_at=str(index)))
        mgr.cleanup_old_sessions(keep=2)
        assert len(mgr.list_sessions()) == 2

    def test_delete_refuses_outside_root(self, tmp_path, mgr):
        outside = tmp_path / "not-a-backup"
        outside.mkdir()
        assert mgr.delete_session(outside) is False
        assert outside.exists()

    def test_delete_removes_session(self, tmp_path, mgr):
        session, _ = _session_with_prefs(tmp_path, mgr)
        assert mgr.delete_session(session) is True
        assert not session.exists()

    def test_session_summary_includes_integrity(self, tmp_path, mgr):
        session, _ = _session_with_prefs(tmp_path, mgr)
        mgr.write_manifest(session)
        summary = mgr.session_summary(session)
        assert summary["integrity_ok"] is True
        assert summary["has_manifest"] is True
        assert summary["artefacts"]["prefs"] is True
        assert summary["size_bytes"] > 0


class TestRestoreFileChecked:
    def test_restore_verifies_bytes(self, tmp_path):
        source = tmp_path / "source"
        source.write_text("original\n")
        destination = tmp_path / "dest"
        destination.write_text("newer\n")
        ok, message = restore_file_checked(source, destination)
        assert ok is True
        assert destination.read_text() == "original\n"
        assert "verified" in message

    def test_missing_source_is_reported(self, tmp_path):
        ok, message = restore_file_checked(tmp_path / "missing", tmp_path / "dest")
        assert ok is False
        assert "missing" in message


class TestMalformedMetadata:
    def test_corrupt_metadata_is_ignored(self, tmp_path, mgr):
        session = mgr.create_session()
        (session / "metadata.json").write_text("{not json")
        assert mgr.read_metadata(session) is None
        assert mgr.list_sessions() == [] or mgr.read_metadata(session) is None

    def test_metadata_with_unknown_fields_is_accepted(self, tmp_path, mgr):
        session = mgr.create_session()
        (session / "metadata.json").write_text(json.dumps({
            "created_at": "2024-01-01", "future_field": 123,
        }))
        metadata = mgr.read_metadata(session)
        assert metadata is not None
        assert metadata.created_at == "2024-01-01"
