"""
Health check / diagnostics engine.

Produces a list of *findings*.  Each finding is an observation backed by
evidence, with an honest description of the likely impact and a recommended
action.  Nothing is applied automatically.

False-positive policy
---------------------
Normal Spotify behaviour is never reported as a problem:

* Spotify keeping several helper processes is normal — only unusual counts are
  mentioned, and only as an observation.
* CPU use while audio is playing is normal.  Because playback state cannot be
  read reliably, high CPU is capped at *low* severity and labelled as
  unverified.
* An enabled hardware-acceleration preference is Spotify's default, so it is an
  informational advisory, not a defect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from . import benchmark
from .backup_manager import BackupManager
from .cache_manager import CacheManager
from .compatibility import Environment, detect_environment
from .detector import SpotifyInstallation
from .logger import get_logger
from .prefs_manager import PrefsManager

log = get_logger("diagnostics")

LARGE_CACHE_BYTES = 2 * 1024 ** 3      # 2 GiB
HUGE_CACHE_BYTES = 5 * 1024 ** 3       # 5 GiB
HIGH_MEMORY_MB = 2000.0
VERY_HIGH_MEMORY_MB = 3500.0
MANY_PROCESSES = 12
EXCESSIVE_PROCESSES = 20


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Finding:
    category: str
    observation: str
    severity: Severity
    evidence: str
    impact: str
    recommendation: str
    automated_fix: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "observation": self.observation,
            "severity": self.severity.value,
            "evidence": self.evidence,
            "impact": self.impact,
            "recommendation": self.recommendation,
            "automated_fix": self.automated_fix,
        }


@dataclass
class HealthReport:
    generated_at: str
    status: str
    findings: list[Finding] = field(default_factory=list)
    install_type: str = "Not Found"
    spotify_version: Optional[str] = None
    measured_memory_mb: Optional[float] = None
    measured_cpu: Optional[float] = None
    process_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = {severity.value: 0 for severity in Severity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts

    @property
    def actionable(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in (Severity.MEDIUM, Severity.HIGH)]

    def summary_text(self) -> str:
        counts = self.counts
        return (
            f"{self.status}. {counts['high']} high, {counts['medium']} medium, "
            f"{counts['low']} low, {counts['info']} informational finding(s)."
        )

    def to_markdown(self, *, redact: bool = True) -> str:
        from .app_paths import redact_text

        lines = [
            "# Spotify Optimizer — Health Report",
            "",
            f"- Generated: {self.generated_at}",
            f"- Status: **{self.status}**",
            f"- Installation: {self.install_type}",
            f"- Spotify version: {self.spotify_version or 'unknown'}",
            f"- Processes: {self.process_count}",
        ]
        if self.measured_memory_mb is not None:
            lines.append(f"- Working set: {self.measured_memory_mb:.1f} MB")
        if self.measured_cpu is not None:
            lines.append(f"- CPU (sampled): {self.measured_cpu:.1f}%")
        lines.append("")
        if not self.findings:
            lines.append("No findings.")
        for finding in self.findings:
            lines.append(f"## [{finding.severity.value.upper()}] {finding.observation}")
            lines.append(f"- Category: {finding.category}")
            lines.append(f"- Evidence: {finding.evidence}")
            lines.append(f"- Impact: {finding.impact}")
            lines.append(f"- Recommendation: {finding.recommendation}")
            if finding.automated_fix:
                lines.append(f"- Available action: {finding.automated_fix}")
            lines.append("")
        for note in self.notes:
            lines.append(f"> {note}")
        text = "\n".join(lines)
        if redact:
            text = redact_text(text)
        return text


def _status_for(findings: list[Finding]) -> str:
    if any(f.severity is Severity.HIGH for f in findings):
        return "Issues detected"
    if any(f.severity is Severity.MEDIUM for f in findings):
        return "Needs attention"
    if any(f.severity is Severity.LOW for f in findings):
        return "Minor observations"
    return "Healthy"


def run_health_check(
    *,
    installation: Optional[SpotifyInstallation] = None,
    env: Optional[Environment] = None,
    backup_root: Optional[Path] = None,
    sample_seconds: float = 1.0,
    include_measurement: bool = True,
) -> HealthReport:
    """Inspect the environment and return a read-only report."""
    environment = env or detect_environment(installation)
    install = environment.installation
    findings: list[Finding] = []
    notes: list[str] = []

    # --- Platform -----------------------------------------------------
    if not environment.windows.is_windows:
        findings.append(Finding(
            category="Platform",
            observation="Not running on Windows",
            severity=Severity.HIGH,
            evidence=f"Platform: {environment.windows.label}",
            impact="Spotify preference and startup operations require Windows APIs.",
            recommendation="Run the optimizer on Windows 10 or Windows 11.",
        ))
    elif environment.windows.build and environment.windows.build < 10240:
        findings.append(Finding(
            category="Platform",
            observation="Unsupported Windows build",
            severity=Severity.MEDIUM,
            evidence=f"{environment.windows.label}, build {environment.windows.build}",
            impact="Some APIs used for startup and process inspection may behave differently.",
            recommendation="Windows 10 (build 10240) or newer is recommended.",
        ))

    # --- Installation -------------------------------------------------
    if not environment.spotify_found:
        findings.append(Finding(
            category="Installation",
            observation="Spotify was not detected",
            severity=Severity.HIGH,
            evidence="No Spotify.exe found in %APPDATA%\\Spotify or Store package locations.",
            impact="No optimisation can run without a detected installation.",
            recommendation="Install Spotify Desktop, or launch Spotify once and re-run the scan.",
        ))
        return _finalise(findings, environment, None, None, notes)

    if install is not None and install.install_type.value == "Microsoft Store":
        findings.append(Finding(
            category="Installation",
            observation="Microsoft Store installation detected",
            severity=Severity.INFO,
            evidence=f"Executable: {install.exe_path}",
            impact=(
                "Store installs can keep preference files inside the packaged sandbox; "
                "preference-based operations may be unavailable."
            ),
            recommendation="Cache and startup operations remain available.",
        ))
    if install is not None and not install.version:
        findings.append(Finding(
            category="Installation",
            observation="Spotify version could not be read",
            severity=Severity.LOW,
            evidence="Executable version metadata was empty or unreadable.",
            impact="Compatibility notes cannot be version-specific.",
            recommendation="No action required; behaviour is unaffected.",
        ))

    # --- Preferences --------------------------------------------------
    prefs_path = install.prefs_path if install else None
    if prefs_path is None:
        findings.append(Finding(
            category="Preferences",
            observation="Spotify preference file was not found",
            severity=Severity.MEDIUM,
            evidence="Expected a 'prefs' file in %APPDATA%\\Spotify.",
            impact="Preference operations (hardware acceleration, cache size) are unavailable.",
            recommendation="Launch Spotify once so it creates its profile, then re-scan.",
        ))
    else:
        prefs = PrefsManager(prefs_path)
        values = prefs.read_all()
        if not values:
            findings.append(Finding(
                category="Preferences",
                observation="Spotify preferences are unreadable or empty",
                severity=Severity.MEDIUM,
                evidence=f"File: {prefs_path}",
                impact="Preference changes cannot be planned safely.",
                recommendation="Close Spotify and retry; check file permissions if it persists.",
            ))
        elif values.get("hardware_acceleration_mode_enabled") == "true":
            findings.append(Finding(
                category="Preferences",
                observation="Hardware acceleration is enabled (Spotify default)",
                severity=Severity.INFO,
                evidence="hardware_acceleration_mode_enabled=true",
                impact=(
                    "Normal spotify behaviour. Disabling it may reduce GPU memory use on "
                    "some drivers, but is not guaranteed to help."
                ),
                recommendation="Only change this if you see GPU-related stutter or high GPU memory use.",
                automated_fix="prefs.hardware_acceleration",
            ))

    # --- Cache --------------------------------------------------------
    if environment.cache_root and environment.cache_readable:
        cache = CacheManager(environment.cache_root)
        eligible = cache.eligible_bytes()
        if eligible >= HUGE_CACHE_BYTES:
            severity, fix = Severity.HIGH, "cache.browser"
        elif eligible >= LARGE_CACHE_BYTES:
            severity, fix = Severity.MEDIUM, "cache.browser"
        else:
            severity, fix = Severity.INFO, None
        if severity is not Severity.INFO:
            findings.append(Finding(
                category="Cache",
                observation="Disposable Spotify cache is large",
                severity=severity,
                evidence=f"{eligible / (1024 ** 3):.2f} GB of removable cache files",
                impact=(
                    "Large caches slow cold starts and consume disk space. They do not "
                    "directly consume RAM."
                ),
                recommendation="Clear the web and code caches while Spotify is closed.",
                automated_fix=fix,
            ))
    else:
        findings.append(Finding(
            category="Cache",
            observation="Spotify cache directory was not found",
            severity=Severity.LOW,
            evidence="Neither %APPDATA%\\Spotify\\Data nor %LOCALAPPDATA%\\Spotify\\Storage exists.",
            impact="Cache inspection and cleanup are unavailable.",
            recommendation="Launch Spotify once so it creates its cache.",
        ))

    # --- Startup ------------------------------------------------------
    if environment.startup_entries:
        names = ", ".join(sorted(environment.startup_entries))
        findings.append(Finding(
            category="Startup",
            observation="Spotify starts automatically with Windows",
            severity=Severity.LOW,
            evidence=f"HKCU Run entries: {names}",
            impact=(
                "Spotify may consume memory before you use it. This is expected if you "
                "enabled autostart yourself."
            ),
            recommendation="Disable the startup entry if you prefer to launch Spotify manually.",
            automated_fix="startup.run_entry",
        ))

    # --- Spicetify ----------------------------------------------------
    if environment.spicetify_available and install is not None and install.spicetify:
        extensions = install.spicetify.extensions
        if len(extensions) >= 4:
            findings.append(Finding(
                category="Spicetify",
                observation=f"{len(extensions)} Spicetify extensions are active",
                severity=Severity.LOW,
                evidence=", ".join(extensions[:8]),
                impact="Each extension runs inside the Spotify renderer and adds overhead.",
                recommendation="Disable extensions you do not actively use.",
                automated_fix="spicetify.extensions",
            ))

    # --- Measurement --------------------------------------------------
    measured_memory = None
    measured_cpu = None
    if include_measurement:
        result = benchmark.measure(
            label="Health check",
            duration=max(0.6, min(sample_seconds, 5.0)),
            interval=0.3,
            cache_root=environment.cache_root,
            spotify_version=environment.spotify_version,
        )
        if result.spotify_running:
            measured_memory = result.working_set_mb
            measured_cpu = result.cpu_mean
            notes.extend(result.notes)
            if measured_memory is not None:
                if measured_memory >= VERY_HIGH_MEMORY_MB:
                    severity = Severity.MEDIUM
                elif measured_memory >= HIGH_MEMORY_MB:
                    severity = Severity.LOW
                else:
                    severity = None
                if severity:
                    findings.append(Finding(
                        category="Performance",
                        observation="Spotify working set is high",
                        severity=severity,
                        evidence=(
                            f"{measured_memory:.1f} MB across {result.process_count} "
                            f"process(es), sampled over {result.duration_seconds:.1f}s"
                        ),
                        impact=(
                            "High memory use may be normal for long sessions or large "
                            "playlists; it is not proof of a leak."
                        ),
                        recommendation=(
                            "Restart Spotify to release accumulated memory, then compare "
                            "measurements on the Performance page."
                        ),
                    ))
                if result.process_count >= EXCESSIVE_PROCESSES:
                    findings.append(Finding(
                        category="Processes",
                        observation="Unusually high Spotify process count",
                        severity=Severity.MEDIUM,
                        evidence=f"{result.process_count} Spotify processes",
                        impact="Many helper processes can indicate a stuck renderer.",
                        recommendation="Restart Spotify and re-check the process monitor.",
                    ))
                elif result.process_count >= MANY_PROCESSES:
                    findings.append(Finding(
                        category="Processes",
                        observation="Several Spotify helper processes are running",
                        severity=Severity.INFO,
                        evidence=f"{result.process_count} Spotify processes",
                        impact="Normal for Chromium-based applications (renderer, GPU, utility).",
                        recommendation="No action required.",
                    ))
                if measured_cpu is not None and measured_cpu >= 15.0:
                    findings.append(Finding(
                        category="Performance",
                        observation="Elevated Spotify CPU usage",
                        severity=Severity.LOW,
                        evidence=f"{measured_cpu:.1f}% mean CPU while sampling",
                        impact=(
                            "Playback state is unknown; decoding audio legitimately uses CPU. "
                            "Treat this as unverified."
                        ),
                        recommendation="Re-check while Spotify is paused to compare.",
                    ))
        else:
            notes.append(
                "Spotify is not running, so no live performance measurement was taken."
            )

    # --- Backups ------------------------------------------------------
    backups = BackupManager(backup_root)
    sessions = backups.list_sessions()
    if not sessions:
        findings.append(Finding(
            category="Backups",
            observation="No backup snapshots yet",
            severity=Severity.INFO,
            evidence=f"Backup folder: {backups.root}",
            impact="Nothing to restore yet; a backup is created automatically before changes.",
            recommendation="No action required.",
        ))
    else:
        integrity = backups.verify_integrity(sessions[0])
        if not integrity.ok and (integrity.missing or integrity.mismatched):
            findings.append(Finding(
                category="Backups",
                observation="The most recent backup failed its integrity check",
                severity=Severity.HIGH,
                evidence=integrity.summary(),
                impact="Restoring from this snapshot may not reproduce the original state.",
                recommendation="Create a fresh backup before making further changes.",
            ))
        else:
            findings.append(Finding(
                category="Backups",
                observation=f"{len(sessions)} backup session(s) available",
                severity=Severity.INFO,
                evidence=f"Newest: {sessions[0].name}",
                impact="Changes can be rolled back.",
                recommendation="No action required.",
            ))

    return _finalise(findings, environment, measured_memory, measured_cpu, notes)


def _finalise(
    findings: list[Finding],
    environment: Environment,
    memory: Optional[float],
    cpu: Optional[float],
    notes: list[str],
) -> HealthReport:
    from .app_paths import redact_path

    report = HealthReport(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        status=_status_for(findings),
        findings=sorted(
            findings,
            key=lambda f: {Severity.HIGH: 0, Severity.MEDIUM: 1,
                           Severity.LOW: 2, Severity.INFO: 3}[f.severity],
        ),
        install_type=environment.install_type,
        spotify_version=environment.spotify_version,
        measured_memory_mb=memory,
        measured_cpu=cpu,
        process_count=environment.process_count,
        notes=notes,
    )
    log.info(f"Health check: {redact_path(report.summary_text())}")
    return report
