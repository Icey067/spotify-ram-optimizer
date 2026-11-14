"""
Tests for preference manager.

Uses temp files — never touches real Spotify prefs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.prefs_manager import (
    PrefsManager,
    _parse_prefs,
    _serialize_prefs,
    build_hw_accel_pref,
    build_cache_size_pref,
    build_autostart_pref,
)


class TestPrefsParser:
    def test_parse_simple(self):
        content = "key1=value1\nkey2=value2\n"
        result = _parse_prefs(content)
        assert result == {"key1": "value1", "key2": "value2"}

    def test_parse_ignores_comments(self):
        content = "# comment\nkey=val\n"
        result = _parse_prefs(content)
        assert "key" in result
        assert "#" not in result

    def test_parse_empty_file(self):
        assert _parse_prefs("") == {}

    def test_serialize_roundtrip(self):
        prefs = {"alpha": "1", "beta": "2"}
        serialized = _serialize_prefs(prefs)
        parsed = _parse_prefs(serialized)
        assert parsed == prefs

    def test_no_duplicate_keys_on_roundtrip(self):
        content = "key=old\n"
        prefs = _parse_prefs(content)
        prefs["key"] = "new"
        serialized = _serialize_prefs(prefs)
        result = _parse_prefs(serialized)
        assert result["key"] == "new"
        assert serialized.count("key=") == 1


class TestPrefsManager:
    def test_read_existing_file(self, tmp_path):
        p = tmp_path / "prefs"
        p.write_text("hw=true\nstorage.size=1024\n")
        mgr = PrefsManager(p)
        data = mgr.read_all()
        assert data["hw"] == "true"
        assert data["storage.size"] == "1024"

    def test_read_missing_file_returns_empty(self, tmp_path):
        mgr = PrefsManager(tmp_path / "nonexistent")
        assert mgr.read_all() == {}

    def test_set_values_preserves_existing_keys(self, tmp_path):
        p = tmp_path / "prefs"
        p.write_text("existing_key=keep_me\n")
        mgr = PrefsManager(p)
        mgr.set_values({"new_key": "new_value"})
        result = mgr.read_all()
        assert result["existing_key"] == "keep_me"
        assert result["new_key"] == "new_value"

    def test_set_values_no_duplicates(self, tmp_path):
        p = tmp_path / "prefs"
        p.write_text("my_key=old\n")
        mgr = PrefsManager(p)
        mgr.set_values({"my_key": "new"})
        content = p.read_text()
        assert content.count("my_key=") == 1

    def test_backup_and_restore(self, tmp_path):
        p = tmp_path / "prefs"
        p.write_text("original=value\n")
        mgr = PrefsManager(p)
        backup = tmp_path / "backup" / "prefs"

        assert mgr.backup(backup)
        assert backup.exists()

        # Modify original
        p.write_text("modified=yes\n")
        assert mgr.read_all().get("original") is None

        # Restore
        assert mgr.restore(backup)
        assert mgr.read_all().get("original") == "value"

    def test_idempotent_set(self, tmp_path):
        p = tmp_path / "prefs"
        p.write_text("hw=true\n")
        mgr = PrefsManager(p)
        updates = {"hw": "false"}
        mgr.set_values(updates)
        mgr.set_values(updates)  # second call
        content = p.read_text()
        assert content.count("hw=") == 1


class TestPrefBuilders:
    def test_hw_accel_disable(self):
        result = build_hw_accel_pref(enabled=False)
        assert result["hardware_acceleration_mode_enabled"] == "false"

    def test_hw_accel_enable(self):
        result = build_hw_accel_pref(enabled=True)
        assert result["hardware_acceleration_mode_enabled"] == "true"

    def test_cache_size_clamped_high(self):
        result = build_cache_size_pref(99999)
        assert int(result["storage.size"]) <= 10240

    def test_cache_size_clamped_low(self):
        result = build_cache_size_pref(-100)
        assert int(result["storage.size"]) >= 0

    def test_autostart_off(self):
        result = build_autostart_pref("off")
        assert '"off"' in result["app.autostart-mode"]

    def test_autostart_invalid_defaults_to_off(self):
        result = build_autostart_pref("bad_value")
        assert '"off"' in result["app.autostart-mode"]
