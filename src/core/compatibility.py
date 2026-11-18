"""
Compatibility detection.

Answers one question honestly: *what can this machine actually support?*

The engine never runs an operation without first evaluating the requirements
against an :class:`Environment` produced here.  Detection is read-only and
uses cheap APIs (no PowerShell subprocesses).
"""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .detector import SpotifyInstallation, detect_installation
from .logger import get_logger
from .prefs_manager import PrefsManager
from .process_manager import get_spotify_process_count
from .registry_manager import RegistryManager

log = get_logger("compat")


class SupportLevel(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially supported"
    UNSUPPORTED = "unsupported"
    REQUIRES_RESTART = "requires Spotify restart"
    REQUIRES_CONFIRMATION = "requires user confirmation"
    SKIPPED = "skipped safely"


@dataclass(frozen=True)
class WindowsInfo:
    is_windows: bool
    label: str
    release: Optional[str]
    build: Optional[int]
    edition: Optional[str]
    architecture: str


@dataclass
class Environment:
    """Snapshot of everything compatibility decisions depend on."""
    windows: WindowsInfo
    installation: Optional[SpotifyInstallation]
    spotify_running: bool = False
    process_count: int = 0
    prefs_readable: bool = False
    prefs_writable: bool = False
    cache_readable: bool = False
    cache_root: Optional[Path] = None
    startup_entries: dict[str, str] = field(default_factory=dict)
    spicetify_available: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def spotify_found(self) -> bool:
        install = self.installation
        return install is not None and install.install_type.value != "Not Found"

    @property
    def install_type(self) -> str:
        return self.installation.install_type.value if self.installation else "Not Found"

    @property
    def spotify_version(self) -> Optional[str]:
        return self.installation.version if self.installation else None


def detect_windows() -> WindowsInfo:
    if sys.platform != "win32":
        return WindowsInfo(
            is_windows=False,
            label=f"{platform.system() or 'Unknown'} (unsupported)",
            release=None,
            build=None,
            edition=None,
            architecture=platform.machine() or "unknown",
        )

    try:
        version = sys.getwindowsversion()
        build = int(version.build)
        release = _windows_release(build)
    except Exception:  # pragma: no cover - defensive
        build = None
        release = None

    edition = _read_edition()
    label = f"Windows {release}" if release else "Windows"
    return WindowsInfo(
        is_windows=True,
        label=label,
        release=release,
        build=build,
        edition=edition,
        architecture=platform.machine() or "unknown",
    )


def _windows_release(build: int) -> str:
    if build >= 22000:
        return "11"
    if build >= 10240:
        return "10"
    return "10 (older build)"


def _read_edition() -> Optional[str]:
    """Read the Windows edition from HKLM (read-only, no elevation needed)."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ) as key:
            edition, _ = winreg.QueryValueEx(key, "EditionID")
            return str(edition)
    except OSError:
        return None


def _folder_writable(path: Path) -> bool:
    """
    Check write access without creating files inside Spotify's profile.

    Uses the OS access check rather than a probe file: the optimizer must not
    leave artefacts inside a directory it does not own.
    """
    if not path.is_dir():
        return False
    return os.access(path, os.W_OK)


def detect_environment(
    installation: Optional[SpotifyInstallation] = None,
    *,
    registry: Optional[RegistryManager] = None,
) -> Environment:
    """Build a fresh environment snapshot."""
    install = installation if installation is not None else detect_installation()
    windows = detect_windows()
    process_count = get_spotify_process_count()

    env = Environment(
        windows=windows,
        installation=install,
        spotify_running=process_count > 0,
        process_count=process_count,
    )

    if install is not None:
        if install.prefs_path:
            prefs = PrefsManager(install.prefs_path)
            env.prefs_readable = prefs.is_readable()
            env.prefs_writable = env.prefs_readable and _folder_writable(
                Path(install.prefs_path).parent
            )
        if install.cache_path:
            env.cache_root = Path(install.cache_path)
            env.cache_readable = Path(install.cache_path).is_dir()
        env.spicetify_available = bool(
            install.spicetify and install.spicetify.is_installed
            and install.spicetify.config_path
        )

    manager = registry or RegistryManager()
    try:
        env.startup_entries = manager.get_spotify_startup_entries()
    except Exception as exc:  # pragma: no cover - registry is best-effort
        log.debug(f"Could not read startup entries: {exc}")
        env.startup_entries = {}

    if not windows.is_windows:
        env.notes.append("Not running on Windows: Spotify preference and registry "
                         "operations are unavailable on this platform.")
    if install is None or install.install_type.value == "Not Found":
        env.notes.append("Spotify installation was not detected.")
    if install is not None and install.install_type.value == "Microsoft Store":
        env.notes.append("Microsoft Store installation detected: preference files may be "
                         "inside the packaged sandbox and not always available.")
    if install is not None and not install.version:
        env.notes.append("Spotify version could not be read from the executable metadata.")

    return env


@dataclass(frozen=True)
class CompatibilityVerdict:
    level: SupportLevel
    reason: str

    @property
    def usable(self) -> bool:
        """
        Whether the operation can be planned.

        ``REQUIRES_CONFIRMATION`` is a prompt, not a blocker: the engine asks
        the user, closes Spotify and proceeds.  Only ``UNSUPPORTED`` and
        ``SKIPPED`` prevent planning.
        """
        return self.level in (
            SupportLevel.SUPPORTED,
            SupportLevel.PARTIALLY_SUPPORTED,
            SupportLevel.REQUIRES_RESTART,
            SupportLevel.REQUIRES_CONFIRMATION,
        )


def evaluate_requirements(
    env: Environment,
    *,
    requires_prefs: bool = False,
    requires_cache: bool = False,
    requires_registry: bool = False,
    requires_spicetify: bool = False,
    requires_spotify_closed: bool = False,
    unverified: bool = False,
) -> CompatibilityVerdict:
    """Decide whether an operation can run, and say why not."""
    if requires_prefs and not env.spotify_found:
        return CompatibilityVerdict(
            SupportLevel.UNSUPPORTED, "Spotify installation not detected."
        )
    if requires_prefs and not env.installation.prefs_path:  # type: ignore[union-attr]
        return CompatibilityVerdict(
            SupportLevel.UNSUPPORTED,
            "Spotify preference file not found (Store installs may hide it).",
        )
    if requires_prefs and not env.prefs_readable:
        return CompatibilityVerdict(
            SupportLevel.UNSUPPORTED, "Spotify preference file is not readable."
        )
    if requires_cache and not env.cache_readable:
        return CompatibilityVerdict(
            SupportLevel.UNSUPPORTED, "Spotify cache directory not found."
        )
    if requires_registry and not env.windows.is_windows:
        return CompatibilityVerdict(
            SupportLevel.UNSUPPORTED, "Registry access requires Windows."
        )
    if requires_registry and not env.spotify_found:
        return CompatibilityVerdict(
            SupportLevel.UNSUPPORTED, "Spotify installation not detected."
        )
    if requires_spicetify and not env.spicetify_available:
        return CompatibilityVerdict(
            SupportLevel.UNSUPPORTED, "Spicetify is not installed or its config is missing."
        )

    if unverified:
        return CompatibilityVerdict(
            SupportLevel.PARTIALLY_SUPPORTED,
            "This setting is not officially documented by Spotify; it is off by "
            "default and may have no effect on your version.",
        )
    if requires_spotify_closed and env.spotify_running:
        return CompatibilityVerdict(
            SupportLevel.REQUIRES_CONFIRMATION,
            "Spotify is running and must be closed for this change.",
        )
    if requires_prefs or requires_spicetify:
        return CompatibilityVerdict(
            SupportLevel.REQUIRES_RESTART,
            "Takes effect the next time Spotify starts.",
        )
    return CompatibilityVerdict(SupportLevel.SUPPORTED, "Supported on this system.")
