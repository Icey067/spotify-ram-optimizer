"""
Tests for Spotify detection logic.

Uses temporary directories and mocked paths — never touches the real system.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure src is importable
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.detector import (
    InstallType,
    SpotifyInstallation,
    _detect_standard,
    _detect_store,
    _detect_spicetify,
    _find_prefs,
    _find_cache,
    get_desktop_paths,
)


# ---------------------------------------------------------------------------
# Standard installation detection
# ---------------------------------------------------------------------------

class TestStandardDetection:
    def test_found(self, tmp_path):
        """Standard install found when Spotify.exe exists in APPDATA/Spotify."""
        spotify_dir = tmp_path / "Spotify"
        spotify_dir.mkdir()
        exe = spotify_dir / "Spotify.exe"
        exe.write_text("fake")

        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            with patch("src.core.detector._get_version", return_value="1.2.3"):
                result = _detect_standard()

        assert result is not None
        assert result.install_type == InstallType.STANDARD
        assert result.exe_path == exe

    def test_not_found(self, tmp_path):
        """Returns None when Spotify.exe is absent."""
        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            result = _detect_standard()
        assert result is None

    def test_prefs_detected(self, tmp_path):
        """Prefs file is correctly detected alongside install."""
        spotify_dir = tmp_path / "Spotify"
        spotify_dir.mkdir()
        (spotify_dir / "Spotify.exe").write_text("x")
        prefs = spotify_dir / "prefs"
        prefs.write_text("hardware_acceleration_mode_enabled=true\n")

        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            with patch("src.core.detector._get_version", return_value=None):
                result = _detect_standard()

        assert result is not None
        assert result.prefs_path == prefs

    def test_prefs_missing(self, tmp_path):
        """Prefs file missing returns None for prefs_path, not an error."""
        spotify_dir = tmp_path / "Spotify"
        spotify_dir.mkdir()
        (spotify_dir / "Spotify.exe").write_text("x")

        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            with patch("src.core.detector._get_version", return_value=None):
                result = _detect_standard()

        assert result is not None
        assert result.prefs_path is None


# ---------------------------------------------------------------------------
# Store installation detection
# ---------------------------------------------------------------------------

class TestStoreDetection:
    def test_store_found_in_packages(self, tmp_path):
        """Store install found in LOCALAPPDATA/Packages/SpotifyAB.SpotifyMusic_xxx."""
        packages = tmp_path / "Packages"
        pkg = packages / "SpotifyAB.SpotifyMusic_zxcv"
        local_cache = pkg / "LocalCache" / "Spotify"
        local_cache.mkdir(parents=True)
        exe = local_cache / "Spotify.exe"
        exe.write_text("store")

        # Also set up the APPDATA Spotify dir for prefs
        appdata_spotify = tmp_path / "Spotify"
        appdata_spotify.mkdir()
        (appdata_spotify / "prefs").write_text("")

        with patch.dict(os.environ, {
            "LOCALAPPDATA": str(tmp_path),
            "APPDATA": str(tmp_path),
            # Point PROGRAMFILES to tmp_path so there's no real WindowsApps to scan
            "PROGRAMFILES": str(tmp_path),
            "PROGRAMFILES(X86)": str(tmp_path),
        }):
            with patch("src.core.detector._get_version", return_value=None):
                result = _detect_store()

        assert result is not None
        assert result.install_type == InstallType.STORE

    def test_store_not_found(self, tmp_path):
        """Returns None when no store install present."""
        with patch.dict(os.environ, {
            "LOCALAPPDATA": str(tmp_path),
            "APPDATA": str(tmp_path),
            "PROGRAMFILES": str(tmp_path),
            "PROGRAMFILES(X86)": str(tmp_path),
        }):
            result = _detect_store()
        assert result is None


# ---------------------------------------------------------------------------
# Spicetify detection
# ---------------------------------------------------------------------------

class TestSpicetifyDetection:
    def test_spicetify_not_found(self):
        """Returns SpicetifyInfo(is_installed=False) when no spicetify exe."""
        with patch("shutil.which", return_value=None):
            with patch.dict(os.environ, {"APPDATA": "C:\\FakeNoExist", "LOCALAPPDATA": "C:\\FakeNoExist"}):
                result = _detect_spicetify()
        assert result.is_installed is False

    def test_spicetify_found_via_which(self, tmp_path):
        """Detects spicetify when shutil.which returns a path."""
        fake_exe = tmp_path / "spicetify.exe"
        fake_exe.write_text("x")
        config_dir = tmp_path / "spicetify"
        config_dir.mkdir()
        config_file = config_dir / "config-xpui.ini"
        config_file.write_text(
            "[Setting]\ncurrent_theme=Default\n[AdditionalOptions]\nextensions=ext1.js|ext2.js\ncustom_apps=app1\n"
        )

        with patch("shutil.which", return_value=str(fake_exe)):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="2.27.3\n",
                    stderr=""
                )
                # Patch path finding to return config_dir
                with patch("src.core.detector._find_spicetify_config_dir", return_value=config_dir):
                    result = _detect_spicetify()

        assert result.is_installed is True
        assert result.version == "2.27.3"
        assert "ext1.js" in result.extensions
        assert "app1" in result.custom_apps


# ---------------------------------------------------------------------------
# Desktop path detection
# ---------------------------------------------------------------------------

class TestDesktopPaths:
    def test_includes_standard_desktop(self, tmp_path):
        """Standard Desktop is always included if it exists."""
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        with patch("pathlib.Path.home", return_value=tmp_path):
            paths = get_desktop_paths()
        assert any("Desktop" in str(p) for p in paths)

    def test_includes_onedrive_desktop(self, tmp_path):
        """OneDrive Desktop is included when env var is set."""
        od_desktop = tmp_path / "OneDrive" / "Desktop"
        od_desktop.mkdir(parents=True)
        with patch.dict(os.environ, {"OneDrive": str(tmp_path / "OneDrive")}):
            with patch("pathlib.Path.home", return_value=tmp_path):
                # Create standard desktop too
                (tmp_path / "Desktop").mkdir(exist_ok=True)
                paths = get_desktop_paths()
        assert any("OneDrive" in str(p) for p in paths)
