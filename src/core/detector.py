"""
Spotify installation detector.

Supports:
  - Standard desktop installation (%APPDATA%\\Spotify)
  - Microsoft Store installation (WindowsApps)
  - OneDrive-redirected Desktop folders
  - Spicetify detection
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .logger import get_logger

log = get_logger("detector")


class InstallType(str, Enum):
    STANDARD = "Standard"
    STORE = "Microsoft Store"
    UNKNOWN = "Unknown"
    NOT_FOUND = "Not Found"


@dataclass
class SpotifyInstallation:
    install_type: InstallType = InstallType.NOT_FOUND
    exe_path: Optional[Path] = None
    data_path: Optional[Path] = None          # %APPDATA%\Spotify  or  LocalAppData equivalent
    prefs_path: Optional[Path] = None
    cache_path: Optional[Path] = None
    version: Optional[str] = None
    spicetify: "SpicetifyInfo | None" = None
    store_package_path: Optional[Path] = None


@dataclass
class SpicetifyInfo:
    is_installed: bool = False
    exe_path: Optional[Path] = None
    version: Optional[str] = None
    config_path: Optional[Path] = None
    config_dir: Optional[Path] = None
    themes: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    custom_apps: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_installation() -> SpotifyInstallation:
    """
    Main entry point. Returns the best SpotifyInstallation found.
    Tries standard install first, then Microsoft Store.
    """
    info = SpotifyInstallation()

    # 1) Standard installation
    std = _detect_standard()
    if std:
        info = std
        log.info(f"Standard Spotify detected at {info.exe_path}")
    else:
        # 2) Microsoft Store installation
        store = _detect_store()
        if store:
            info = store
            log.info(f"Store Spotify detected at {info.exe_path}")
        else:
            log.info("No Spotify installation found.")

    # 3) Spicetify (always check, independent of install type)
    info.spicetify = _detect_spicetify()
    return info


# ---------------------------------------------------------------------------
# Standard installation
# ---------------------------------------------------------------------------

def _detect_standard() -> Optional[SpotifyInstallation]:
    appdata = Path(os.environ.get("APPDATA", ""))
    spotify_data = appdata / "Spotify"
    spotify_exe = spotify_data / "Spotify.exe"

    if not spotify_exe.exists():
        log.debug(f"Standard install not found at {spotify_exe}")
        return None

    info = SpotifyInstallation(
        install_type=InstallType.STANDARD,
        exe_path=spotify_exe,
        data_path=spotify_data,
    )
    info.prefs_path = _find_prefs(spotify_data)
    info.cache_path = _find_cache(spotify_data)
    info.version = _get_version(spotify_exe)
    return info


# ---------------------------------------------------------------------------
# Microsoft Store installation
# ---------------------------------------------------------------------------

def _detect_store() -> Optional[SpotifyInstallation]:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    windows_apps = local_app_data / "Microsoft" / "WindowsApps"

    # Try known Spotify Store paths
    candidates: list[Path] = []

    # Pattern 1: WindowsApps direct (usually access-restricted without admin)
    if windows_apps.exists():
        try:
            for item in windows_apps.iterdir():
                if item.is_dir() and "spotify" in item.name.lower():
                    candidates.append(item)
        except (PermissionError, OSError) as exc:
            log.debug(f"Access denied scanning {windows_apps}: {exc}")

    # Pattern 2: Packages folder
    packages_dir = local_app_data / "Packages"
    if packages_dir.exists():
        try:
            for item in packages_dir.iterdir():
                if "spotify" in item.name.lower():
                    candidates.append(item / "LocalCache" / "Spotify")
                    candidates.append(item)
        except (PermissionError, OSError) as exc:
            log.debug(f"Access denied scanning {packages_dir}: {exc}")

    # Pattern 3: Program Files (may require elevated access — handle gracefully)
    for pfx in ["PROGRAMFILES", "PROGRAMFILES(X86)"]:
        pf = Path(os.environ.get(pfx, ""))
        sp = pf / "WindowsApps"
        if sp.exists():
            try:
                for item in sp.iterdir():
                    if "spotify" in item.name.lower():
                        candidates.append(item)
            except PermissionError:
                log.debug(f"Access denied scanning {sp} (expected without admin rights)")

    for candidate in candidates:
        exe = candidate / "Spotify.exe"
        if exe.exists():
            # Find data path (preferences are in AppData even for store version)
            appdata = Path(os.environ.get("APPDATA", ""))
            spotify_data = appdata / "Spotify"
            info = SpotifyInstallation(
                install_type=InstallType.STORE,
                exe_path=exe,
                data_path=spotify_data if spotify_data.exists() else None,
                store_package_path=candidate,
            )
            if spotify_data.exists():
                info.prefs_path = _find_prefs(spotify_data)
                info.cache_path = _find_cache(spotify_data)
            info.version = _get_version(exe)
            return info

    log.debug("Store install not found.")
    return None


# ---------------------------------------------------------------------------
# Preference / cache paths
# ---------------------------------------------------------------------------

def _find_prefs(spotify_data: Path) -> Optional[Path]:
    prefs = spotify_data / "prefs"
    if prefs.exists():
        return prefs
    log.debug(f"prefs file not found at {prefs}")
    return None


def _find_cache(spotify_data: Path) -> Optional[Path]:
    # Cache may be under Data\Local\... or directly in AppData\Local\Spotify\Storage
    candidates = [
        spotify_data / "Data",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Spotify" / "Storage",
    ]
    for c in candidates:
        if c.exists():
            return c
    log.debug("Cache directory not found.")
    return None


# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

def _get_version(exe: Path) -> Optional[str]:
    """
    Read the executable's file version with the Win32 version API.

    Deliberately avoids PowerShell: no shell string is ever built from a path,
    so a directory name containing quotes or shell metacharacters cannot be
    interpreted as a command.  It is also an order of magnitude faster than
    starting a PowerShell process.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover - defensive
        return None

    class VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_ = [
            ("dwSignature", wintypes.DWORD),
            ("dwStrucVersion", wintypes.DWORD),
            ("dwFileVersionMS", wintypes.DWORD),
            ("dwFileVersionLS", wintypes.DWORD),
            ("dwProductVersionMS", wintypes.DWORD),
            ("dwProductVersionLS", wintypes.DWORD),
            ("dwFileFlagsMask", wintypes.DWORD),
            ("dwFileFlags", wintypes.DWORD),
            ("dwFileOS", wintypes.DWORD),
            ("dwFileType", wintypes.DWORD),
            ("dwFileSubtype", wintypes.DWORD),
            ("dwFileDateMS", wintypes.DWORD),
            ("dwFileDateLS", wintypes.DWORD),
        ]

    try:
        path = str(exe)
        version_dll = ctypes.windll.version
        size = version_dll.GetFileVersionInfoSizeW(path, None)
        if not size:
            log.debug(f"No version resource in {path}")
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(path, 0, size, buffer):
            return None
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version_dll.VerQueryValueW(
            buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)
        ):
            return None
        if not pointer.value:
            return None
        info = ctypes.cast(pointer, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        if not ms and not ls:
            return None
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except (OSError, AttributeError, ValueError) as exc:
        log.debug(f"Version detection failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Spicetify detection
# ---------------------------------------------------------------------------

def _detect_spicetify() -> SpicetifyInfo:
    info = SpicetifyInfo()

    # Find spicetify executable
    exe = shutil.which("spicetify")
    if exe is None:
        # Manual check in common locations
        candidates = [
            Path(os.environ.get("APPDATA", "")) / "spicetify" / "spicetify.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "spicetify" / "spicetify.exe",
            Path.home() / ".spicetify" / "spicetify.exe",
        ]
        for c in candidates:
            if c.exists():
                exe = str(c)
                break

    if exe is None:
        log.info("Spicetify not found.")
        return info

    info.is_installed = True
    info.exe_path = Path(exe)
    log.info(f"Spicetify found at {exe}")

    # Version
    try:
        r = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=10)
        ver = r.stdout.strip() or r.stderr.strip()
        if ver:
            info.version = ver.split("\n")[0].strip()
            log.info(f"Spicetify version: {info.version}")
    except Exception as e:
        log.warning(f"Could not get Spicetify version: {e}")

    # Config location
    spicetify_config_dir = _find_spicetify_config_dir(exe)
    if spicetify_config_dir:
        info.config_dir = spicetify_config_dir
        config_file = spicetify_config_dir / "config-xpui.ini"
        if config_file.exists():
            info.config_path = config_file
            _parse_spicetify_config(info, config_file)

    return info


def _find_spicetify_config_dir(exe: str) -> Optional[Path]:
    try:
        r = subprocess.run(
            [exe, "path", "config-dir"],
            capture_output=True, text=True, timeout=10
        )
        p = r.stdout.strip()
        if p:
            return Path(p)
    except Exception:
        pass

    # Fallback locations
    for base in [
        Path(os.environ.get("APPDATA", "")),
        Path(os.environ.get("LOCALAPPDATA", "")),
        Path.home(),
    ]:
        for sub in ["spicetify", ".spicetify"]:
            d = base / sub
            if (d / "config-xpui.ini").exists():
                return d
    return None


def _parse_spicetify_config(info: SpicetifyInfo, config_path: Path) -> None:
    try:
        content = config_path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("current_theme"):
                val = line.split("=", 1)[1].strip() if "=" in line else ""
                if val:
                    info.themes.append(val)
            elif line.startswith("extensions"):
                val = line.split("=", 1)[1].strip() if "=" in line else ""
                if val:
                    info.extensions = [e.strip() for e in val.split("|") if e.strip()]
            elif line.startswith("custom_apps"):
                val = line.split("=", 1)[1].strip() if "=" in line else ""
                if val:
                    info.custom_apps = [a.strip() for a in val.split("|") if a.strip()]
    except Exception as e:
        log.warning(f"Could not parse Spicetify config: {e}")


# ---------------------------------------------------------------------------
# OneDrive Desktop detection
# ---------------------------------------------------------------------------

def get_desktop_paths() -> list[Path]:
    """Return all Desktop paths, including OneDrive-redirected ones."""
    paths: list[Path] = []

    # Standard Desktop
    standard = Path.home() / "Desktop"
    if standard.exists():
        paths.append(standard)

    # OneDrive Desktop
    for env_var in ["OneDrive", "OneDriveConsumer", "OneDriveCommercial"]:
        od = os.environ.get(env_var)
        if od:
            od_desktop = Path(od) / "Desktop"
            if od_desktop.exists() and od_desktop not in paths:
                paths.append(od_desktop)

    # Registry shell folders (most reliable)
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        ) as k:
            try:
                val, _ = winreg.QueryValueEx(k, "Desktop")
                p = Path(os.path.expandvars(val))
                if p.exists() and p not in paths:
                    paths.append(p)
            except FileNotFoundError:
                pass
    except Exception as e:
        log.debug(f"Registry Desktop lookup failed: {e}")

    return paths or [Path.home() / "Desktop"]
