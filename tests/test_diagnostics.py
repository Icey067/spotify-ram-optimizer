"""Health-check tests: evidence, severity discipline and report redaction."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.compatibility import Environment, WindowsInfo
from src.core.detector import InstallType, SpotifyInstallation
from src.core.diagnostics import Finding, HealthReport, Severity, run_health_check


def make_env(tmp_path: Path, *, found: bool = True, prefs: bool = True,
             cache: bool = True, startup: dict | None = None,
             spotify_version: str | None = "1.2.3.456") -> Environment:
    spotify = tmp_path / "Spotify"
    spotify.mkdir(exist_ok=True)
    prefs_path = None
    if prefs:
        prefs_path = spotify / "prefs"
        prefs_path.write_text("hardware_acceleration_mode_enabled=true\n")
    cache_path = None
    if cache:
        cache_path = spotify / "Data"
        (cache_path / "Cache").mkdir(parents=True, exist_ok=True)
        (cache_path / "Cache" / "tile").write_bytes(b"x" * 1024)

    install = SpotifyInstallation(
        install_type=InstallType.STANDARD if found else InstallType.NOT_FOUND,
        exe_path=spotify / "Spotify.exe" if found else None,
        data_path=spotify if found else None,
        prefs_path=prefs_path if found else None,
        cache_path=cache_path if found else None,
        version=spotify_version if found else None,
    )
    return Environment(
        windows=WindowsInfo(True, "Windows 11", "11", 22631, "Professional", "AMD64"),
        installation=install,
        spotify_running=False,
        process_count=0,
        prefs_readable=bool(prefs and found),
        prefs_writable=bool(prefs and found),
        cache_readable=bool(cache and found),
        cache_root=cache_path,
        startup_entries=startup or {},
        spicetify_available=False,
    )


def check(tmp_path, env):
    return run_health_check(
        installation=env.installation,
        env=env,
        backup_root=tmp_path / "backups",
        include_measurement=False,
    )


class TestHealthChecks:
    def test_healthy_environment_reports_no_problems(self, tmp_path):
        report = check(tmp_path, make_env(tmp_path))
        assert report.status == "Healthy"
        assert not report.actionable
        assert report.install_type == "Standard"
        assert report.spotify_version == "1.2.3.456"

    def test_missing_installation_is_high_severity(self, tmp_path):
        report = check(tmp_path, make_env(tmp_path, found=False))
        assert report.status == "Issues detected"
        assert any(f.severity is Severity.HIGH for f in report.findings)
        assert any("not detected" in f.observation.lower() for f in report.findings)

    def test_missing_prefs_is_medium(self, tmp_path):
        report = check(tmp_path, make_env(tmp_path, prefs=False))
        assert any(f.severity is Severity.MEDIUM for f in report.findings)

    def test_hardware_acceleration_is_only_informational(self, tmp_path):
        report = check(tmp_path, make_env(tmp_path))
        hw = [f for f in report.findings
              if "hardware acceleration" in f.observation.lower()]
        assert hw
        assert hw[0].severity is Severity.INFO
        assert hw[0].automated_fix == "prefs.hardware_acceleration"

    def test_large_cache_is_flagged_with_evidence(self, tmp_path):
        env = make_env(tmp_path)
        big = Path(env.cache_root) / "Cache" / "huge.tmp"
        big.write_bytes(b"0" * (3 * 1024 * 1024))  # 3 MB is small, so cram via patch
        # Simulate a large eligible cache by patching the threshold check input.
        from src.core import diagnostics
        original = diagnostics.CacheManager

        class FakeCache:
            def __init__(self, *_args, **_kwargs):
                pass

            def eligible_bytes(self):
                return 3 * 1024 ** 3

        diagnostics.CacheManager = FakeCache
        try:
            report = check(tmp_path, env)
        finally:
            diagnostics.CacheManager = original
        cache_findings = [f for f in report.findings if f.category == "Cache"]
        assert cache_findings
        assert cache_findings[0].severity is Severity.MEDIUM
        assert "GB" in cache_findings[0].evidence

    def test_startup_entry_generates_advisory(self, tmp_path):
        env = make_env(tmp_path, startup={"Spotify": r"C:\Spotify\Spotify.exe"})
        report = check(tmp_path, env)
        startup = [f for f in report.findings if f.category == "Startup"]
        assert startup
        assert startup[0].severity is Severity.LOW
        assert startup[0].automated_fix == "startup.run_entry"

    def test_findings_are_sorted_by_severity(self, tmp_path):
        env = make_env(tmp_path, startup={"Spotify": r"C:\Spotify\Spotify.exe"})
        report = check(tmp_path, env)
        order = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2, Severity.INFO: 3}
        severities = [order[f.severity] for f in report.findings]
        assert severities == sorted(severities)

    def test_health_check_does_not_modify_prefs(self, tmp_path):
        env = make_env(tmp_path)
        prefs = Path(env.installation.prefs_path)
        before = prefs.read_bytes()
        check(tmp_path, env)
        assert prefs.read_bytes() == before


class TestReportRendering:
    def test_counts_and_summary(self):
        report = HealthReport(
            generated_at="now",
            status="Needs attention",
            findings=[
                Finding("Cache", "Large cache", Severity.MEDIUM, "3 GB", "impact",
                        "recommendation"),
                Finding("Startup", "Autostart", Severity.LOW, "entry", "impact",
                        "recommendation"),
            ],
        )
        counts = report.counts
        assert counts["medium"] == 1
        assert counts["low"] == 1
        assert "medium" in report.summary_text()

    def test_markdown_includes_all_sections(self):
        report = HealthReport(
            generated_at="now",
            status="Healthy",
            findings=[Finding("Cache", "Check", Severity.INFO, "e", "i", "r")],
            notes=["a note"],
        )
        text = report.to_markdown()
        assert "# Spotify Optimizer — Health Report" in text
        assert "Evidence: e" in text
        assert "a note" in text

    @pytest.mark.parametrize("variable, profile", [
        ("USERPROFILE", r"C:\Users\alice"),
        ("HOME", "/home/alice"),
    ])
    def test_markdown_redacts_the_active_profile(self, monkeypatch, variable, profile):
        monkeypatch.setenv(variable, profile)
        report = HealthReport(
            generated_at="now",
            status="Healthy",
            findings=[Finding("Preferences", "Path", Severity.INFO,
                              f"{profile}/AppData/Roaming/Spotify/prefs", "i", "r")],
        )
        text = report.to_markdown(redact=True)
        assert "alice" not in text
        assert "%USERPROFILE%" in text

    @pytest.mark.parametrize("path", [
        r"C:\Users\bob\AppData\Roaming\Spotify\prefs",
        r"D:\Users\bob\Music",
        "/home/bob/.config/spotify/prefs",
        "/Users/bob/Library/Application Support/Spotify/prefs",
    ])
    def test_nested_profile_paths_are_redacted_without_environment(
        self, monkeypatch, path
    ):
        monkeypatch.delenv("USERPROFILE", raising=False)
        monkeypatch.setenv("HOME", "/tmp/not-bob")
        report = HealthReport(
            generated_at="now",
            status="Healthy",
            findings=[Finding("Preferences", "Nested", Severity.INFO,
                              f"Root: {path} (nested)", "i", "r")],
        )
        text = report.to_markdown(redact=True)
        assert "bob" not in text
        assert "%USERPROFILE%" in text

    def test_finding_serialises_to_dict(self):
        finding = Finding("Cache", "Check", Severity.LOW, "e", "i", "r", "cache.browser")
        data = finding.to_dict()
        assert data["severity"] == "low"
        assert data["automated_fix"] == "cache.browser"
