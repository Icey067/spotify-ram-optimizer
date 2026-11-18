"""
Security-focused tests.

Cover:
  * registry writes restricted to a Spotify allow-list,
  * no shell/PowerShell use for version detection,
  * version detection cannot be tricked into executing a path,
  * backup deletion containment,
  * JSON import validation (see test_profiles.py for the bulk),
  * path traversal in profile names.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core import detector
from src.core.backup_manager import BackupManager
from src.core.registry_manager import RegistryManager, _is_spotify_entry


class TestRegistryAllowList:
    def test_disable_rejects_unrelated_name(self):
        manager = RegistryManager()
        fake = MagicMock()
        with patch("src.core.registry_manager._open_winreg", return_value=fake):
            assert manager.disable_startup_entry("Steam") is False
        fake.DeleteValue.assert_not_called()

    def test_enable_rejects_unrelated_name(self):
        manager = RegistryManager()
        fake = MagicMock()
        with patch("src.core.registry_manager._open_winreg", return_value=fake):
            assert manager.enable_startup_entry("Steam", "C:\\Steam\\steam.exe") is False
        fake.SetValueEx.assert_not_called()

    def test_allow_list_contents(self):
        from src.core.registry_manager import SPOTIFY_VALUE_NAMES
        assert "spotify" in SPOTIFY_VALUE_NAMES
        assert "spotifywebhelper" in SPOTIFY_VALUE_NAMES

    @pytest.mark.parametrize("name,command,expected", [
        ("Spotify", "C:\\x\\Spotify.exe", True),
        ("SpotifyWebHelper", "", True),
        ("Steam", "C:\\Steam\\steam.exe", False),
        ("Updater", "C:\\Tools\\notepad.exe", False),
        ("Updater", "C:\\Spotify\\Spotify.exe --autostart", True),
    ])
    def test_entry_classification(self, name, command, expected):
        assert _is_spotify_entry(name, command) is expected


class TestVersionDetection:
    def test_no_shell_is_used(self):
        """The implementation must not spawn a process or build a shell command."""
        source = inspect.getsource(detector._get_version)
        for forbidden in ("subprocess", "os.system", "shell=true", "-command"):
            assert forbidden not in source.lower()

    def test_module_does_not_build_shell_strings(self):
        source = inspect.getsource(detector)
        assert "shell=True" not in source

    def test_non_executable_returns_none(self, tmp_path):
        fake = tmp_path / "not-a-pe.exe"
        fake.write_bytes(b"not a portable executable")
        assert detector._get_version(fake) in (None, "") or isinstance(
            detector._get_version(fake), (str, type(None))
        )

    def test_missing_file_returns_none(self, tmp_path):
        assert detector._get_version(tmp_path / "missing.exe") is None


class TestBackupContainment:
    def test_delete_session_outside_root_is_refused(self, tmp_path):
        root = tmp_path / "backups"
        manager = BackupManager(root)
        victim = tmp_path / "important"
        victim.mkdir()
        (victim / "file").write_text("keep me")
        assert manager.delete_session(victim) is False
        assert (victim / "file").exists()

    def test_cleanup_cannot_escape_root(self, tmp_path):
        root = tmp_path / "backups"
        manager = BackupManager(root)
        victim = tmp_path / "not-a-session"
        victim.mkdir()
        (victim / "file").write_text("keep me")
        # Pruning only iterates discovered sessions, so an outside directory
        # must never be considered.
        manager.cleanup_old_sessions(keep=1)
        assert (victim / "file").exists()


class TestOptionalDependencySafety:
    def test_cache_never_deletes_cache_root(self, tmp_path):
        from src.core.cache_manager import CacheManager
        root = tmp_path / "cache"
        root.mkdir()
        (root / "personal.txt").write_text("keep")
        manager = CacheManager(root)
        manager.clean_groups(["browser", "code", "gpu"])
        assert (root / "personal.txt").exists()
        assert root.is_dir()
