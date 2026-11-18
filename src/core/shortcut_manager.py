"""
Shortcut manager.

Finds Spotify shortcuts in:
  - Start Menu (user and common)
  - Desktop (standard and OneDrive-redirected)
  - Taskbar pinned items (best-effort)

Reads and writes the Target / Arguments fields of .lnk files
using the Windows Shell COM API (via pywin32).

Preserves ALL existing arguments; never overwrites without backup.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .detector import get_desktop_paths
from .logger import get_logger

log = get_logger("shortcuts")


@dataclass
class ShortcutInfo:
    path: str                     # full path to .lnk file
    target: str                   # original TargetPath
    arguments: str                # original Arguments
    description: str = ""
    working_dir: str = ""
    icon_location: str = ""


def _get_shell():
    """
    Return a win32com Shell object, or ``None`` when unavailable.

    COM is initialised per calling thread: the engine runs optimisations on a
    worker thread, where an uninitialised apartment would make every shortcut
    operation fail silently.
    """
    try:
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            # Already initialised or COM unavailable; Dispatch below decides.
            pass
        import win32com.client
        return win32com.client.Dispatch("WScript.Shell")
    except Exception:
        return None


class ShortcutManager:

    def find_spotify_shortcuts(self) -> list[ShortcutInfo]:
        """Find all .lnk files pointing to Spotify.exe."""
        locations = _search_locations()
        found: list[ShortcutInfo] = []
        for lnk in locations:
            info = _read_shortcut(lnk)
            if info and "spotify" in info.target.lower():
                found.append(info)
                log.debug(f"Found Spotify shortcut: {lnk}")
        return found

    def backup_shortcuts(self) -> list[dict]:
        """Return serialisable list of shortcut dicts for backup."""
        shortcuts = self.find_spotify_shortcuts()
        return [
            {
                "path": s.path,
                "target": s.target,
                "arguments": s.arguments,
                "description": s.description,
                "working_dir": s.working_dir,
                "icon_location": s.icon_location,
            }
            for s in shortcuts
        ]

    def restore_shortcuts(self, backup_data: list[dict]) -> bool:
        """Restore shortcut arguments from backup."""
        success = True
        for item in backup_data:
            path = Path(item["path"])
            if not path.exists():
                log.warning(f"Shortcut no longer exists: {path}")
                continue
            ok = _write_shortcut_arguments(
                path=path,
                arguments=item["arguments"],
            )
            if not ok:
                success = False
        return success

    def add_launch_args(self, shortcut_path: Path, extra_args: str) -> bool:
        """
        Append extra_args to a shortcut's Arguments, avoiding duplicates.
        """
        info = _read_shortcut(shortcut_path)
        if info is None:
            return False
        existing = info.arguments.strip()
        # Avoid adding args that are already present
        new_args = _merge_args(existing, extra_args)
        if new_args == existing:
            log.debug(f"Args already present in {shortcut_path}, skipping.")
            return True
        return _write_shortcut_arguments(shortcut_path, new_args)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _search_locations() -> list[Path]:
    lnk_files: list[Path] = []

    # Desktop (including OneDrive)
    for desktop in get_desktop_paths():
        lnk_files += list(desktop.glob("*.lnk"))

    # Start Menu
    for start_menu in [
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]:
        lnk_files += list(start_menu.rglob("*.lnk"))

    # Taskbar pinned shortcuts
    taskbar = (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft" / "Internet Explorer" / "Quick Launch"
        / "User Pinned" / "TaskBar"
    )
    if taskbar.exists():
        lnk_files += list(taskbar.glob("*.lnk"))

    # Deduplicate
    seen = set()
    result = []
    for f in lnk_files:
        key = str(f).lower()
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result


def _read_shortcut(lnk_path: Path) -> Optional[ShortcutInfo]:
    shell = _get_shell()
    if shell is None:
        log.warning("win32com not available; cannot read shortcut.")
        return None
    try:
        sc = shell.CreateShortCut(str(lnk_path))
        return ShortcutInfo(
            path=str(lnk_path),
            target=sc.TargetPath or "",
            arguments=sc.Arguments or "",
            description=sc.Description or "",
            working_dir=sc.WorkingDirectory or "",
            icon_location=sc.IconLocation or "",
        )
    except Exception as e:
        log.debug(f"Could not read shortcut {lnk_path}: {e}")
        return None


def _write_shortcut_arguments(path: Path, arguments: str) -> bool:
    shell = _get_shell()
    if shell is None:
        log.warning("win32com not available; cannot write shortcut.")
        return False
    try:
        sc = shell.CreateShortCut(str(path))
        sc.Arguments = arguments
        sc.Save()
        log.info(f"Shortcut updated: {path} → args={arguments!r}")
        return True
    except Exception as e:
        log.error(f"Could not write shortcut {path}: {e}")
        return False


def _merge_args(existing: str, new_args: str) -> str:
    """Add new_args to existing without duplicating flags."""
    existing_flags = set(existing.split())
    new_flags = [f for f in new_args.split() if f not in existing_flags]
    if not new_flags:
        return existing
    return (existing + " " + " ".join(new_flags)).strip()
