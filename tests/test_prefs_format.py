"""
Preference-file preserving edits.

The Spotify prefs file is a user file: comments, unknown keys, ordering and
line endings must survive an edit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.prefs_manager import PrefsManager, _apply_to_text


SAMPLE = (
    "# Spotify preferences\r\n"
    "app.autostart-mode=\"off\"\r\n"
    "hardware_acceleration_mode_enabled=true\r\n"
    "some.future.setting=unknown-value\r\n"
    "storage.size=1024\r\n"
)


@pytest.fixture
def prefs(tmp_path):
    path = tmp_path / "prefs"
    path.write_bytes(SAMPLE.encode("utf-8"))
    return path


class TestFormatPreservation:
    def test_order_and_comments_preserved(self, prefs):
        manager = PrefsManager(prefs)
        assert manager.set_values({"storage.size": "512"})
        # Read bytes: read_text() would normalise CRLF to LF and hide the result.
        text = prefs.read_bytes().decode("utf-8")
        assert text.startswith("# Spotify preferences\r\n")
        assert text.index("app.autostart-mode") < text.index("hardware_acceleration")
        assert "some.future.setting=unknown-value" in text
        assert "storage.size=512" in text

    def test_crlf_line_endings_preserved(self, prefs):
        manager = PrefsManager(prefs)
        manager.set_values({"storage.size": "256"})
        raw = prefs.read_bytes()
        assert b"\r\n" in raw
        # No bare LF introduced by the rewrite.
        assert raw.replace(b"\r\n", b"").count(b"\n") == 0

    def test_new_key_is_appended(self, prefs):
        manager = PrefsManager(prefs)
        manager.set_values({"brand.new.key": "1"})
        lines = prefs.read_text(encoding="utf-8").splitlines()
        assert lines[-1] == "brand.new.key=1"

    def test_removing_a_key_removes_only_that_line(self, prefs):
        manager = PrefsManager(prefs)
        assert manager.remove_keys(["storage.size"])
        text = prefs.read_text(encoding="utf-8")
        assert "storage.size" not in text
        assert "hardware_acceleration_mode_enabled=true" in text

    def test_verify_reports_mismatch(self, prefs):
        manager = PrefsManager(prefs)
        result = manager.verify({"storage.size": "999"})
        assert result["storage.size"] is False
        manager.set_values({"storage.size": "999"})
        assert manager.verify({"storage.size": "999"})["storage.size"] is True

    def test_no_op_write_keeps_file_identical(self, prefs):
        manager = PrefsManager(prefs)
        before = prefs.read_bytes()
        assert manager.set_values({"storage.size": "1024"})
        assert prefs.read_bytes() == before

    def test_missing_file_returns_false(self, tmp_path):
        manager = PrefsManager(tmp_path / "prefs")
        assert manager.set_values({"a": "b"}) is False
        assert manager.read_all() == {}

    def test_sha256_changes_after_write(self, prefs):
        manager = PrefsManager(prefs)
        before = manager.sha256()
        manager.set_values({"storage.size": "1"})
        assert manager.sha256() != before


class TestInjectionResistance:
    def test_newline_in_value_is_rejected(self, prefs):
        manager = PrefsManager(prefs)
        before = prefs.read_bytes()
        assert manager.set_values({"storage.size": "1\nEVIL=1"}) is False
        assert prefs.read_bytes() == before

    def test_newline_in_key_is_rejected(self, prefs):
        manager = PrefsManager(prefs)
        assert manager.set_values({"bad\nkey": "1"}) is False

    def test_equals_in_key_is_rejected(self, prefs):
        manager = PrefsManager(prefs)
        assert manager.set_values({"bad=key": "1"}) is False

    def test_non_string_value_is_rejected(self, prefs):
        manager = PrefsManager(prefs)
        assert manager.set_values({"storage.size": 512}) is False  # type: ignore[arg-type]

    def test_blank_value_is_allowed(self, prefs):
        manager = PrefsManager(prefs)
        assert manager.set_values({"storage.size": ""})


class TestApplyToText:
    def test_preserves_line_without_equals(self):
        text = "weird line without equals\nkey=value\n"
        result = _apply_to_text(text, {"key": "new"})
        assert "weird line without equals" in result
        assert "key=new" in result

    def test_duplicate_keys_are_all_updated(self):
        text = "key=one\nkey=two\n"
        result = _apply_to_text(text, {"key": "three"})
        assert result.count("key=three") == 2
        assert "one" not in result and "two" not in result

    def test_missing_trailing_newline_is_handled(self):
        result = _apply_to_text("key=value", {"new": "1"})
        assert result.rstrip().endswith("new=1")
        assert "key=value" in result
