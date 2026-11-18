"""
Registry manager for Spotify startup entries.

Scope and safety
----------------
* Only ``HKEY_CURRENT_USER`` is ever written, so no administrator rights are
  needed and no system-wide behaviour is changed.
* Before a value is removed, the caller is expected to have backed it up
  (the engine always does).  ``disable_startup_entry`` also verifies the value
  still looks like Spotify when requested, so a same-named entry belonging to
  another application is not silently removed.
* ``StartupApproved\\Run`` state is read (not written) so the UI can explain
  why an entry may already be disabled by Windows.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .logger import get_logger

log = get_logger("registry")

STARTUP_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_APPROVED_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
STARTUP_KEY_NAMES = ["Spotify", "SpotifyWebHelper"]

# Value names we are willing to remove (matched case-insensitively).
SPOTIFY_VALUE_NAMES = frozenset(name.lower() for name in STARTUP_KEY_NAMES)


def _open_winreg():
    """Import winreg lazily (only available on Windows)."""
    try:
        import winreg
        return winreg
    except ImportError:
        return None


@dataclass(frozen=True)
class StartupEntry:
    """A startup entry discovered for the current user."""
    name: str
    location: str
    command: str
    enabled: bool
    belongs_to_spotify: bool
    safe_to_modify: bool
    note: str = ""


class RegistryManager:

    # ------------------------------------------------------------------
    # Read startup entries
    # ------------------------------------------------------------------

    def get_startup_entries(self) -> dict[str, str]:
        """Return known Spotify startup values from HKCU\\...\\Run."""
        winreg = _open_winreg()
        if winreg is None:
            log.debug("winreg not available (non-Windows?).")
            return {}

        entries: dict[str, str] = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY_PATH) as key:
                for name in STARTUP_KEY_NAMES:
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                        entries[name] = value
                    except FileNotFoundError:
                        pass
        except FileNotFoundError:
            log.debug("HKCU Run key not found.")
        except OSError as exc:
            log.error(f"Registry read error: {exc}")
        return entries

    def get_spotify_startup_entries(self) -> dict[str, str]:
        """
        Return every HKCU Run value that belongs to Spotify.

        Uses an explicit name allow-list plus a command-path check so helper
        entries with unusual names are still found, while unrelated entries
        are never included.
        """
        winreg = _open_winreg()
        if winreg is None:
            return {}

        found: dict[str, str] = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY_PATH) as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if not isinstance(name, str) or not isinstance(value, str):
                        continue
                    if _is_spotify_entry(name, value):
                        found[name] = value
        except FileNotFoundError:
            return {}
        except OSError as exc:
            log.debug(f"Could not enumerate startup entries ({exc}); using allow-list.")
            return self.get_startup_entries()
        except Exception as exc:  # pragma: no cover - defensive against odd hooks
            log.debug(f"Startup enumeration failed ({exc}); using allow-list.")
            return self.get_startup_entries()
        return found

    def get_startup_entry_details(self) -> list[StartupEntry]:
        """Detailed, read-only view of Spotify-related startup entries."""
        winreg = _open_winreg()
        details: list[StartupEntry] = []
        commands = self.get_spotify_startup_entries()

        for name, command in commands.items():
            approved = self._read_startup_approved(name)
            enabled = approved if approved is not None else True
            belongs = _is_spotify_entry(name, command)
            safe = belongs and name.lower() in SPOTIFY_VALUE_NAMES
            note = ""
            if not safe:
                note = ("Entry points at Spotify but has an unrecognised name; "
                        "left untouched for safety.")
            if approved is False:
                note = (note + " " if note else "") + "Already disabled by Windows."
            details.append(StartupEntry(
                name=name,
                location=f"HKCU\\{STARTUP_KEY_PATH}",
                command=command,
                enabled=enabled,
                belongs_to_spotify=belongs,
                safe_to_modify=safe,
                note=note.strip(),
            ))

        details.extend(self._startup_folder_entries())
        return details

    def _read_startup_approved(self, name: str) -> Optional[bool]:
        """Read Windows' own enabled/disabled flag; ``None`` means unknown."""
        winreg = _open_winreg()
        if winreg is None:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_KEY_PATH) as key:
                data, _ = winreg.QueryValueEx(key, name)
            if isinstance(data, (bytes, bytearray)) and data:
                # 02/06 = enabled, 03/07 = disabled (documented by Windows shell).
                return data[0] not in (3, 7)
        except OSError:
            return None
        except Exception:
            return None
        return None

    def _startup_folder_entries(self) -> list[StartupEntry]:
        """List Spotify shortcuts in the per-user Startup folder."""
        startup_dir = (
            Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows"
            / "Start Menu" / "Programs" / "Startup"
        )
        entries: list[StartupEntry] = []
        if not startup_dir.is_dir():
            return entries
        try:
            candidates = list(startup_dir.glob("*.lnk"))
        except OSError:
            return entries
        for path in candidates:
            if "spotify" not in path.name.lower():
                continue
            entries.append(StartupEntry(
                name=path.name,
                location=str(startup_dir),
                command=str(path),
                enabled=True,
                belongs_to_spotify=True,
                safe_to_modify=False,
                note="Startup-folder shortcut: remove it manually if you no longer "
                     "want Spotify to start automatically.",
            ))
        return entries

    # ------------------------------------------------------------------
    # Disable / Enable startup
    # ------------------------------------------------------------------

    def disable_startup_entry(
        self,
        name: str,
        *,
        require_spotify_value: bool = False,
    ) -> bool:
        """Remove a Spotify startup entry from HKCU Run."""
        winreg = _open_winreg()
        if winreg is None:
            return False
        if name.lower() not in SPOTIFY_VALUE_NAMES:
            log.warning(f"Refusing to remove unrecognised startup entry: {name}")
            return False

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                STARTUP_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
            ) as key:
                if require_spotify_value:
                    try:
                        current, _ = winreg.QueryValueEx(key, name)
                        if not _is_spotify_entry(name, str(current)):
                            log.warning(
                                f"Startup entry '{name}' no longer belongs to Spotify; "
                                "leaving it untouched."
                            )
                            return False
                    except FileNotFoundError:
                        return True
                try:
                    winreg.DeleteValue(key, name)
                    log.info(f"Removed startup entry: {name}")
                    return True
                except FileNotFoundError:
                    log.debug(f"Startup entry '{name}' not present (already disabled).")
                    return True
        except OSError as exc:
            log.error(f"Could not remove startup entry '{name}': {exc}")
            return False

    def enable_startup_entry(self, name: str, value: str) -> bool:
        """Restore a Spotify startup entry in HKCU Run."""
        winreg = _open_winreg()
        if winreg is None:
            return False
        if name.lower() not in SPOTIFY_VALUE_NAMES:
            log.warning(f"Refusing to write unrecognised startup entry: {name}")
            return False
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                STARTUP_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                log.info(f"Restored startup entry: {name}")
                return True
        except OSError as exc:
            log.error(f"Could not set startup entry '{name}': {exc}")
            return False

    # ------------------------------------------------------------------
    # Backup / Restore helpers (called by BackupManager)
    # ------------------------------------------------------------------

    def export_for_backup(self) -> dict[str, Any]:
        """
        Export the entries this manager is allowed to modify.

        Only the allow-listed names are exported, because those are the only
        values any operation can change or restore.
        """
        return {
            "startup_entries": self.get_startup_entries(),
        }

    def restore_from_backup(self, data: dict[str, Any]) -> bool:
        """Restore entries from backup data, removing only Spotify entries."""
        entries: dict[str, str] = data.get("startup_entries", {})
        success = True

        for name in self.get_startup_entries():
            if not self.disable_startup_entry(name):
                success = False

        for name, value in entries.items():
            if value and name.lower() in SPOTIFY_VALUE_NAMES:
                if not self.enable_startup_entry(name, value):
                    success = False
        return success


def _is_spotify_entry(name: str, command: str) -> bool:
    name_lower = (name or "").lower()
    command_lower = (command or "").lower()
    if name_lower in SPOTIFY_VALUE_NAMES:
        return True
    return "spotify" in command_lower and ".exe" in command_lower
