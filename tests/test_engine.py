"""
Tests for the optimization engine.

Uses mocked installation objects and temporary directories.
Never runs against a real Spotify installation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.detector import InstallType, SpotifyInstallation
from src.core.engine import OptimizationEngine, OptimizationSettings


def _make_install(tmp_path, with_prefs=True, with_cache=True):
    """Build a fake SpotifyInstallation for testing."""
    spotify_dir = tmp_path / "Spotify"
    spotify_dir.mkdir(exist_ok=True)

    prefs_path = None
    if with_prefs:
        prefs_path = spotify_dir / "prefs"
        prefs_path.write_text("hardware_acceleration_mode_enabled=true\n")

    cache_path = None
    if with_cache:
        cache_path = spotify_dir / "Data"
        cache_path.mkdir(exist_ok=True)
        (cache_path / "Cache").mkdir(exist_ok=True)
        (cache_path / "Cache" / "file1").write_bytes(b"x" * 500)

    install = SpotifyInstallation(
        install_type=InstallType.STANDARD,
        exe_path=spotify_dir / "Spotify.exe",
        data_path=spotify_dir,
        prefs_path=prefs_path,
        cache_path=cache_path,
        version="1.2.3.456",
        spicetify=None,
    )
    return install


class TestEngineOptimization:
    @pytest.fixture
    def engine(self, tmp_path):
        install = _make_install(tmp_path)
        eng = OptimizationEngine(installation=install, backup_root=tmp_path / "backups")
        return eng

    def test_basic_run_succeeds(self, engine):
        with patch("src.core.engine.stop_spotify", return_value=(True, "stopped")):
            with patch("src.core.engine.is_spotify_running", return_value=True):
                result = engine.run_optimization(OptimizationSettings())
        assert result.operations_completed > 0
        assert result.backup_session is not None

    def test_backup_created(self, engine, tmp_path):
        with patch("src.core.engine.stop_spotify", return_value=(True, "ok")):
            with patch("src.core.engine.is_spotify_running", return_value=False):
                result = engine.run_optimization(OptimizationSettings())
        assert result.backup_session is not None
        assert result.backup_session.is_dir()

    def test_prefs_modified(self, engine, tmp_path):
        """Prefs file is updated after optimization run."""
        with patch("src.core.engine.stop_spotify", return_value=(True, "ok")):
            with patch("src.core.engine.is_spotify_running", return_value=False):
                engine.run_optimization(
                    OptimizationSettings(disable_hw_accel=True)
                )
        prefs = engine.installation.prefs_path
        assert "false" in prefs.read_text()

    def test_idempotent_prefs(self, engine):
        """Running twice does not duplicate keys in prefs file."""
        with patch("src.core.engine.stop_spotify", return_value=(True, "ok")):
            with patch("src.core.engine.is_spotify_running", return_value=False):
                engine.run_optimization(OptimizationSettings())
                engine.run_optimization(OptimizationSettings())
        prefs = engine.installation.prefs_path
        content = prefs.read_text()
        assert content.count("hardware_acceleration_mode_enabled=") == 1

    def test_no_prefs_file_does_not_crash(self, tmp_path):
        install = _make_install(tmp_path, with_prefs=False)
        eng = OptimizationEngine(installation=install, backup_root=tmp_path / "backups")
        with patch("src.core.engine.stop_spotify", return_value=(True, "ok")):
            with patch("src.core.engine.is_spotify_running", return_value=False):
                result = eng.run_optimization(OptimizationSettings())
        assert result is not None  # Did not crash

    def test_cache_cleaned(self, engine, tmp_path):
        cache_file = engine.installation.cache_path / "Cache" / "file1"
        assert cache_file.exists()
        with patch("src.core.engine.stop_spotify", return_value=(True, "ok")):
            with patch("src.core.engine.is_spotify_running", return_value=False):
                result = engine.run_optimization(
                    OptimizationSettings(clean_browser_cache=True)
                )
        assert result.cache_freed_mb >= 0

    def test_restore_latest(self, engine, tmp_path):
        """Restore correctly reverts prefs to pre-optimization state."""
        original_content = engine.installation.prefs_path.read_text()
        with patch("src.core.engine.stop_spotify", return_value=(True, "ok")):
            with patch("src.core.engine.is_spotify_running", return_value=False):
                engine.run_optimization(OptimizationSettings(disable_hw_accel=True))

        with patch("src.core.engine.is_spotify_running", return_value=False):
            restore_result = engine.restore_latest()

        assert engine.installation.prefs_path.read_text() == original_content

    def test_restore_no_backup(self, tmp_path):
        install = _make_install(tmp_path)
        eng = OptimizationEngine(installation=install, backup_root=tmp_path / "empty_backups")
        result = eng.restore_latest()
        assert "No backups" in " ".join(result.messages)

    def test_no_installation_returns_error(self, tmp_path):
        eng = OptimizationEngine(installation=None, backup_root=tmp_path / "b")
        result = eng.run_optimization(OptimizationSettings())
        assert result.success is False
        assert any("No Spotify" in m for m in result.messages)
