"""
Spotify preferences manager.

Reads and writes Spotify's `prefs` file safely.
Supports:
  - hardware_acceleration_mode_enabled
  - storage.size (cache size)
  - app.autostart-mode
  - audio.sync_clock_enabled  (optional)

Rules:
  - Always back up before modifying.
  - Never duplicate keys.
  - Preserve unknown keys unchanged.
  - Use atomic write (temp file → rename).
  - Skip unsupported settings gracefully.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from .logger import get_logger

log = get_logger("prefs")

# Map of preference keys to their supported values / types
SUPPORTED_PREFS: dict[str, dict] = {
    "hardware_acceleration_mode_enabled": {
        "type": "bool",
        "default": True,
        "description": "Enable/disable GPU hardware acceleration",
    },
    "storage.size": {
        "type": "int",
        "default": 1024,
        "description": "Spotify cache size in MB",
        "min": 0,
        "max": 10240,
    },
    "app.autostart-mode": {
        "type": "str",
        "default": "off",
        "choices": ["off", "minimized"],
        "description": "Spotify autostart mode",
    },
    "audio.sync_clock_enabled": {
        "type": "bool",
        "default": True,
        "description": "Audio sync clock (disable may help on some systems)",
    },
}


class PrefsManager:
    def __init__(self, prefs_path: Path) -> None:
        self.path = prefs_path

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_all(self) -> dict[str, str]:
        """Return all key=value pairs from prefs as raw strings."""
        if not self.path.exists():
            log.warning(f"Prefs file not found: {self.path}")
            return {}
        try:
            content = self.path.read_text(encoding="utf-8", errors="replace")
            return _parse_prefs(content)
        except Exception as e:
            log.error(f"Could not read prefs: {e}")
            return {}

    def get(self, key: str) -> Optional[str]:
        return self.read_all().get(key)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set_values(self, updates: dict[str, str]) -> bool:
        """
        Merge `updates` into existing prefs.
        Returns True on success.
        """
        existing = self.read_all()
        merged = {**existing, **updates}
        return self._write(merged)

    def _write(self, prefs: dict[str, str]) -> bool:
        try:
            content = _serialize_prefs(prefs)
            _atomic_write(self.path, content, encoding="utf-8")
            log.info(f"Prefs written to {self.path}")
            return True
        except Exception as e:
            log.error(f"Could not write prefs: {e}")
            return False

    # ------------------------------------------------------------------
    # Backup / Restore
    # ------------------------------------------------------------------

    def backup(self, backup_path: Path) -> bool:
        try:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, backup_path)
            log.info(f"Prefs backed up to {backup_path}")
            return True
        except Exception as e:
            log.error(f"Prefs backup failed: {e}")
            return False

    def restore(self, backup_path: Path) -> bool:
        if not backup_path.exists():
            log.error(f"Backup not found: {backup_path}")
            return False
        try:
            shutil.copy2(backup_path, self.path)
            log.info(f"Prefs restored from {backup_path}")
            return True
        except Exception as e:
            log.error(f"Prefs restore failed: {e}")
            return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_prefs(content: str) -> dict[str, str]:
    """Parse Spotify prefs format: key=value, one per line."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _serialize_prefs(prefs: dict[str, str]) -> str:
    """Serialize prefs dict back to Spotify prefs format."""
    lines = []
    for key in sorted(prefs.keys()):
        lines.append(f"{key}={prefs[key]}")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write to a temp file then rename for atomicity."""
    dir_ = path.parent
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        # On Windows, replace requires the target to not exist in some edge cases
        if path.exists():
            os.replace(tmp_path, path)
        else:
            os.rename(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Preference value builders
# ---------------------------------------------------------------------------

def build_hw_accel_pref(enabled: bool) -> dict[str, str]:
    return {"hardware_acceleration_mode_enabled": "true" if enabled else "false"}


def build_cache_size_pref(size_mb: int) -> dict[str, str]:
    # Clamp to safe range
    size_mb = max(0, min(size_mb, 10240))
    return {"storage.size": str(size_mb)}


def build_autostart_pref(mode: str) -> dict[str, str]:
    if mode not in ("off", "minimized"):
        mode = "off"
    return {"app.autostart-mode": f'"{mode}"'}
