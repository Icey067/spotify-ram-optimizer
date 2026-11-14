"""
Registry manager for Spotify startup entries.

Only modifies HKCU (current user) — no admin rights needed.
Backs up all values before changing them.
Never touches system-wide or HKLM keys.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .logger import get_logger

log = get_logger("registry")

# Spotify startup key paths (HKCU only)
STARTUP_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_KEY_NAMES = ["Spotify", "SpotifyWebHelper"]


def _open_winreg():
    """Import winreg lazily (only available on Windows)."""
    try:
        import winreg
        return winreg
    except ImportError:
        return None


class RegistryManager:

    # ------------------------------------------------------------------
    # Read startup entries
    # ------------------------------------------------------------------

    def get_startup_entries(self) -> dict[str, str]:
        """Return Spotify-related startup entries in HKCU\\...\\Run."""
        winreg = _open_winreg()
        if winreg is None:
            log.warning("winreg not available (non-Windows?)")
            return {}

        entries: dict[str, str] = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY_PATH) as k:
                for name in STARTUP_KEY_NAMES:
                    try:
                        val, _ = winreg.QueryValueEx(k, name)
                        entries[name] = val
                        log.debug(f"Startup entry found: {name} = {val}")
                    except FileNotFoundError:
                        pass
        except FileNotFoundError:
            log.debug("HKCU Run key not found.")
        except Exception as e:
            log.error(f"Registry read error: {e}")
        return entries

    # ------------------------------------------------------------------
    # Disable / Enable startup
    # ------------------------------------------------------------------

    def disable_startup_entry(self, name: str) -> bool:
        """Remove a Spotify startup entry from HKCU Run."""
        winreg = _open_winreg()
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                STARTUP_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE
            ) as k:
                try:
                    winreg.DeleteValue(k, name)
                    log.info(f"Removed startup entry: {name}")
                    return True
                except FileNotFoundError:
                    log.debug(f"Startup entry '{name}' not present (already disabled).")
                    return True
        except Exception as e:
            log.error(f"Could not remove startup entry '{name}': {e}")
            return False

    def enable_startup_entry(self, name: str, value: str) -> bool:
        """Restore a Spotify startup entry in HKCU Run."""
        winreg = _open_winreg()
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                STARTUP_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE
            ) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
                log.info(f"Restored startup entry: {name} = {value}")
                return True
        except Exception as e:
            log.error(f"Could not set startup entry '{name}': {e}")
            return False

    # ------------------------------------------------------------------
    # Backup / Restore helpers (called by BackupManager)
    # ------------------------------------------------------------------

    def export_for_backup(self) -> dict[str, Any]:
        """Export current state for backup."""
        return {
            "startup_entries": self.get_startup_entries(),
        }

    def restore_from_backup(self, data: dict[str, Any]) -> bool:
        """Restore entries from backup data dict."""
        entries: dict[str, str] = data.get("startup_entries", {})
        success = True
        # First remove any currently set entries
        current = self.get_startup_entries()
        for name in current:
            if not self.disable_startup_entry(name):
                success = False

        # Restore backed-up values
        for name, value in entries.items():
            if value:  # non-empty means it was set
                if not self.enable_startup_entry(name, value):
                    success = False
        return success
