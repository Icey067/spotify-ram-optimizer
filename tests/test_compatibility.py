"""
Compatibility layer tests.

All environments are constructed in memory; nothing reads or writes the real
registry, Spotify profile or process table.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.compatibility import (
    CompatibilityVerdict,
    Environment,
    SupportLevel,
    WindowsInfo,
    detect_windows,
    evaluate_requirements,
)


def _windows(**overrides) -> WindowsInfo:
    base = dict(is_windows=True, label="Windows 11", release="11", build=22631,
                edition="Professional", architecture="AMD64")
    base.update(overrides)
    return WindowsInfo(**base)


def _install(tmp_path: Path, *, prefs=True, cache=True, spicetify=False):
    from src.core.detector import InstallType, SpotifyInstallation, SpicetifyInfo

    spotify_dir = tmp_path / "Spotify"
    spotify_dir.mkdir(exist_ok=True)
    prefs_path = None
    if prefs:
        prefs_path = spotify_dir / "prefs"
        prefs_path.write_text("hardware_acceleration_mode_enabled=true\n")
    cache_path = None
    if cache:
        cache_path = spotify_dir / "Data"
        cache_path.mkdir(exist_ok=True)
    sp = None
    if spicetify:
        cfg = tmp_path / "config-xpui.ini"
        cfg.write_text("[AdditionalOptions]\nextensions=a.js\n")
        sp = SpicetifyInfo(is_installed=True, exe_path=tmp_path / "spicetify.exe",
                           config_path=cfg)
    return SpotifyInstallation(
        install_type=InstallType.STANDARD,
        exe_path=spotify_dir / "Spotify.exe",
        data_path=spotify_dir,
        prefs_path=prefs_path,
        cache_path=cache_path,
        version="1.2.3.456",
        spicetify=sp,
    )


def _env(tmp_path: Path, **overrides) -> Environment:
    install = overrides.pop("installation", _install(tmp_path))
    env = Environment(
        windows=overrides.pop("windows", _windows()),
        installation=install,
        spotify_running=overrides.pop("spotify_running", False),
        process_count=overrides.pop("process_count", 0),
        prefs_readable=overrides.pop("prefs_readable", install.prefs_path is not None),
        prefs_writable=True,
        cache_readable=overrides.pop("cache_readable", install.cache_path is not None),
        cache_root=install.cache_path,
        spicetify_available=overrides.pop("spicetify_available", False),
        startup_entries=overrides.pop("startup_entries", {}),
    )
    return env


class TestWindowsDetection:
    def test_returns_windows_info(self):
        info = detect_windows()
        assert isinstance(info, WindowsInfo)
        if sys.platform == "win32":
            assert info.is_windows is True
            assert info.label.startswith("Windows")
            assert info.build is None or info.build > 0
        else:
            assert info.is_windows is False


class TestRequirementEvaluation:
    def test_supported_when_everything_present(self, tmp_path):
        verdict = evaluate_requirements(_env(tmp_path), requires_prefs=True)
        assert verdict.usable
        assert verdict.level in (SupportLevel.SUPPORTED, SupportLevel.REQUIRES_RESTART)

    def test_missing_installation_is_unsupported(self, tmp_path):
        from src.core.detector import InstallType, SpotifyInstallation
        empty = SpotifyInstallation(install_type=InstallType.NOT_FOUND)
        env = _env(tmp_path, installation=empty, prefs_readable=False, cache_readable=False)
        verdict = evaluate_requirements(env, requires_prefs=True)
        assert verdict.level is SupportLevel.UNSUPPORTED
        assert not verdict.usable

    def test_missing_prefs_is_unsupported(self, tmp_path):
        install = _install(tmp_path, prefs=False)
        env = _env(tmp_path, installation=install, prefs_readable=False)
        verdict = evaluate_requirements(env, requires_prefs=True)
        assert verdict.level is SupportLevel.UNSUPPORTED
        assert "preference" in verdict.reason.lower()

    def test_missing_cache_is_unsupported(self, tmp_path):
        install = _install(tmp_path, cache=False)
        env = _env(tmp_path, installation=install, cache_readable=False)
        verdict = evaluate_requirements(env, requires_cache=True)
        assert verdict.level is SupportLevel.UNSUPPORTED

    def test_registry_requires_windows(self, tmp_path):
        env = _env(tmp_path, windows=_windows(is_windows=False, label="Linux",
                                              release=None, build=None))
        verdict = evaluate_requirements(env, requires_registry=True)
        assert verdict.level is SupportLevel.UNSUPPORTED

    def test_missing_spicetify(self, tmp_path):
        env = _env(tmp_path, spicetify_available=False)
        verdict = evaluate_requirements(env, requires_spicetify=True)
        assert verdict.level is SupportLevel.UNSUPPORTED

    def test_requires_restart_when_spotify_running_and_closing_needed(self, tmp_path):
        env = _env(tmp_path, spotify_running=True, process_count=3)
        verdict = evaluate_requirements(
            env, requires_prefs=True, requires_spotify_closed=True
        )
        assert verdict.level is SupportLevel.REQUIRES_CONFIRMATION
        assert "close" in verdict.reason.lower()

    def test_unverified_is_partially_supported(self, tmp_path):
        verdict = evaluate_requirements(_env(tmp_path), requires_prefs=True,
                                        unverified=True)
        assert verdict.level is SupportLevel.PARTIALLY_SUPPORTED
        assert "not officially documented" in verdict.reason.lower()

    def test_verdict_is_immutable(self):
        verdict = CompatibilityVerdict(SupportLevel.SUPPORTED, "ok")
        with pytest.raises(Exception):
            verdict.level = SupportLevel.UNSUPPORTED  # type: ignore[misc]
