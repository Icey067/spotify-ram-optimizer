"""
Custom profile import/export tests — including hostile inputs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.profiles import (
    MAX_FILE_BYTES,
    Profile,
    ProfileError,
    delete_saved_profile,
    export_profile,
    import_profile,
    list_saved_profiles,
    save_profile,
    validate_profile,
)


class TestValidation:
    def test_minimal_valid_profile(self):
        profile = validate_profile({
            "schema_version": 1,
            "name": "My profile",
            "operations": ["prefs.hardware_acceleration"],
            "cache_size_mb": 256,
        })
        assert profile.name == "My profile"
        assert profile.operations == ["prefs.hardware_acceleration"]
        assert profile.cache_size_mb == 256

    def test_operations_are_ordered_and_deduplicated(self):
        profile = validate_profile({
            "name": "x",
            "operations": ["cache.code", "prefs.hardware_acceleration", "cache.code"],
        })
        assert profile.operations == ["prefs.hardware_acceleration", "cache.code"]

    def test_unknown_operation_is_rejected(self):
        with pytest.raises(ProfileError, match="unknown operation"):
            validate_profile({"name": "x", "operations": ["prefs.evil_tweak"]})

    def test_script_field_is_rejected(self):
        with pytest.raises(ProfileError, match="Unsupported field"):
            validate_profile({
                "name": "x",
                "operations": [],
                "script": "powershell -c Remove-Item C:\\ -Recurse",
            })

    def test_path_field_is_rejected(self):
        with pytest.raises(ProfileError, match="Unsupported field"):
            validate_profile({"name": "x", "operations": [], "path": "C:\\Windows"})

    def test_wrong_schema_version_is_rejected(self):
        with pytest.raises(ProfileError, match="schema version"):
            validate_profile({"schema_version": 99, "name": "x", "operations": []})

    def test_name_traversal_is_rejected(self):
        with pytest.raises(ProfileError):
            validate_profile({"name": "../escape", "operations": []})

    def test_empty_name_is_rejected(self):
        with pytest.raises(ProfileError):
            validate_profile({"name": "   ", "operations": []})

    def test_overlong_name_is_rejected(self):
        with pytest.raises(ProfileError):
            validate_profile({"name": "x" * 200, "operations": []})

    def test_cache_size_bounds(self):
        with pytest.raises(ProfileError):
            validate_profile({"name": "x", "operations": [], "cache_size_mb": 99999})
        with pytest.raises(ProfileError):
            validate_profile({"name": "x", "operations": [], "cache_size_mb": -1})
        with pytest.raises(ProfileError):
            validate_profile({"name": "x", "operations": [], "cache_size_mb": True})

    def test_non_object_is_rejected(self):
        with pytest.raises(ProfileError):
            validate_profile(["not", "an", "object"])

    def test_operations_must_be_strings(self):
        with pytest.raises(ProfileError):
            validate_profile({"name": "x", "operations": [1, 2]})


class TestFileIO:
    def test_export_then_import_round_trip(self, tmp_path):
        profile = Profile(name="Round trip", operations=["cache.browser"],
                          cache_size_mb=128)
        target = tmp_path / "profile.json"
        export_profile(profile, target)
        loaded = import_profile(target)
        assert loaded.name == "Round trip"
        assert loaded.cache_size_mb == 128
        assert loaded.operations == ["cache.browser"]

    def test_exported_file_is_versioned_json(self, tmp_path):
        target = tmp_path / "profile.json"
        export_profile(Profile(name="x", operations=[]), target)
        data = json.loads(target.read_text())
        assert data["schema_version"] == 1
        assert set(data) <= {"schema_version", "name", "operations",
                             "cache_size_mb", "notes"}

    def test_invalid_json_is_rejected(self, tmp_path):
        target = tmp_path / "broken.json"
        target.write_text("{not json")
        with pytest.raises(ProfileError, match="not valid JSON"):
            import_profile(target)

    def test_missing_file_is_rejected(self, tmp_path):
        with pytest.raises(ProfileError, match="Could not read"):
            import_profile(tmp_path / "nope.json")

    def test_oversized_file_is_rejected(self, tmp_path):
        target = tmp_path / "huge.json"
        target.write_text("{" + " " * (MAX_FILE_BYTES + 10) + "}")
        with pytest.raises(ProfileError, match="too large"):
            import_profile(target)

    def test_saved_profiles_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPOTIFY_OPTIMIZER_HOME", str(tmp_path / "app"))
        save_profile(Profile(name="Saved", operations=["cache.code"]))
        profiles = list_saved_profiles()
        assert [p.name for p in profiles] == ["Saved"]

    def test_delete_saved_profile_refuses_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPOTIFY_OPTIMIZER_HOME", str(tmp_path / "app"))
        save_profile(Profile(name="Keep", operations=[]))
        assert delete_saved_profile("../outside") is False
        assert delete_saved_profile("Keep") is True

    def test_invalid_saved_profile_is_skipped(self, tmp_path, monkeypatch):
        home = tmp_path / "app"
        monkeypatch.setenv("SPOTIFY_OPTIMIZER_HOME", str(home))
        save_profile(Profile(name="Good", operations=[]))
        bad = home / "profiles" / "bad.json"
        bad.write_text("{}")
        names = [p.name for p in list_saved_profiles()]
        assert names == ["Good"]
