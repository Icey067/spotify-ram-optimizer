"""
Spotify preferences manager.

Spotify stores its settings in a plain ``prefs`` file (``key=value`` lines).
This module edits that file **in place**, preserving:

  - every unknown key and its original value,
  - the original line order,
  - comments / blank lines,
  - the original newline convention (CRLF vs LF),
  - the file encoding (UTF-8).

Writes are atomic: content is written to a temporary file in the same
directory, flushed and fsync'ed, then swapped in with :func:`os.replace`.
A failed write therefore never leaves a half-written ``prefs`` file behind.

Evidence policy
---------------
Only settings we can reasonably attribute to Spotify are offered.  Each key
carries an ``evidence`` note.  ``app.autostart-mode`` is marked *unverified*
and is never written unless the user explicitly opts in.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from .logger import get_logger

log = get_logger("prefs")

# Map of preference keys to their supported values / types.
SUPPORTED_PREFS: dict[str, dict] = {
    "hardware_acceleration_mode_enabled": {
        "type": "bool",
        "default": True,
        "description": "Enable/disable GPU hardware acceleration",
        "evidence": "Present in Spotify's own prefs file; mirrors Spotify's "
                    "'Enable hardware acceleration' setting.",
    },
    "storage.size": {
        "type": "int",
        "default": 1024,
        "description": "Spotify cache size in MB",
        "min": 0,
        "max": 10240,
        "evidence": "Documented by Spotify's cache size setting; enforced on restart.",
    },
    "app.autostart-mode": {
        "type": "str",
        "default": "off",
        "choices": ["off", "minimized"],
        "description": "Spotify autostart mode",
        "evidence": "UNVERIFIED: not officially documented. Disabled by default.",
    },
    "audio.sync_clock_enabled": {
        "type": "bool",
        "default": True,
        "description": "Audio sync clock",
        "evidence": "UNVERIFIED: not officially documented. Not offered by default.",
    },
}


class PrefsManager:
    def __init__(self, prefs_path: Path) -> None:
        self.path = Path(prefs_path)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def raw_text(self) -> Optional[str]:
        """
        Return the file content exactly as stored (``None`` if unreadable).

        Reads bytes and decodes them manually: ``Path.read_text`` applies
        universal-newline translation, which would silently convert CRLF to LF
        and rewrite the whole file on the next save.
        """
        try:
            return self.path.read_bytes().decode("utf-8", errors="replace")
        except FileNotFoundError:
            log.warning(f"Prefs file not found: {self.path}")
            return None
        except OSError as exc:
            log.error(f"Could not read prefs: {exc}")
            return None

    def read_all(self) -> dict[str, str]:
        """Return all key=value pairs from prefs as raw strings."""
        text = self.raw_text()
        if text is None:
            return {}
        return _parse_prefs(text)

    def get(self, key: str) -> Optional[str]:
        return self.read_all().get(key)

    def exists(self) -> bool:
        return self.path.is_file()

    def is_readable(self) -> bool:
        return self.raw_text() is not None

    def sha256(self) -> Optional[str]:
        """SHA-256 of the current file, or ``None`` when unreadable."""
        try:
            return hashlib.sha256(self.path.read_bytes()).hexdigest()
        except OSError:
            return None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set_values(self, updates: dict[str, str]) -> bool:
        """Merge ``updates`` into the existing prefs, preserving formatting."""
        return self.apply_changes(updates)

    def remove_keys(self, keys: list[str] | tuple[str, ...]) -> bool:
        return self.apply_changes({key: None for key in keys})

    def apply_changes(self, updates: dict[str, Optional[str]]) -> bool:
        """
        Apply ``updates`` to the prefs file.

        ``None`` as a value removes the key.  All other lines are untouched.
        Returns ``True`` on success.
        """
        if not updates:
            return True
        problem = _validate_updates(updates)
        if problem:
            log.error(f"Refusing to write preference values: {problem}")
            return False
        text = self.raw_text()
        if text is None:
            return False
        try:
            new_text = _apply_to_text(text, updates)
            if new_text == text:
                log.debug("Prefs already in the requested state; nothing written.")
                return True
            _atomic_write(self.path, new_text, encoding="utf-8")
            log.info(f"Prefs updated ({len(updates)} key(s)) in {self.path}")
            return True
        except OSError as exc:
            log.error(f"Could not write prefs: {exc}")
            return False

    def verify(self, expected: dict[str, str]) -> dict[str, bool]:
        """Re-read the file and report which expected values are present."""
        current = self.read_all()
        return {key: current.get(key) == value for key, value in expected.items()}

    # ------------------------------------------------------------------
    # Backup / Restore
    # ------------------------------------------------------------------

    def backup(self, backup_path: Path) -> bool:
        try:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, backup_path)
            log.info(f"Prefs backed up to {backup_path}")
            return True
        except OSError as exc:
            log.error(f"Prefs backup failed: {exc}")
            return False

    def restore(self, backup_path: Path) -> bool:
        if not backup_path.exists():
            log.error(f"Backup not found: {backup_path}")
            return False
        try:
            shutil.copy2(backup_path, self.path)
            log.info(f"Prefs restored from {backup_path}")
            return True
        except OSError as exc:
            log.error(f"Prefs restore failed: {exc}")
            return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_updates(updates: dict[str, Optional[str]]) -> Optional[str]:
    """Reject keys/values that could inject additional prefs lines."""
    for key, value in updates.items():
        if not isinstance(key, str) or not key:
            return f"invalid key {key!r}"
        if "=" in key or "\n" in key or "\r" in key:
            return f"key {key!r} contains a reserved character"
        if value is None:
            continue
        if not isinstance(value, str):
            return f"value for {key!r} must be a string"
        if "\n" in value or "\r" in value:
            return f"value for {key!r} contains a newline"
    return None


def _newline_for(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _apply_to_text(text: str, updates: dict[str, Optional[str]]) -> str:
    """
    Line-preserving merge.

    Keys already present keep their position; new keys are appended.
    """
    newline = _newline_for(text)
    lines = text.splitlines(keepends=True)
    seen: set[str] = set()
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in updates:
                seen.add(key)
                value = updates[key]
                if value is None:
                    # Drop the whole key line (and its line ending).
                    continue
                ending = line[len(line.rstrip("\r\n")):]
                if not ending:
                    ending = newline
                output.append(f"{key}={value}{ending}")
                continue
        output.append(line)

    missing = [(key, value) for key, value in updates.items()
               if key not in seen and value is not None]
    if missing:
        if output and not output[-1].endswith(("\n", "\r")):
            output.append(newline)
        for key, value in missing:
            output.append(f"{key}={value}{newline}")

    return "".join(output)


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
    """Serialize prefs dict back to Spotify prefs format (sorted)."""
    lines = []
    for key in sorted(prefs.keys()):
        lines.append(f"{key}={prefs[key]}")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write to a temp file in the same directory, fsync, then replace."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
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
    size_mb = max(0, min(int(size_mb), 10240))
    return {"storage.size": str(size_mb)}


def build_autostart_pref(mode: str) -> dict[str, str]:
    if mode not in ("off", "minimized"):
        mode = "off"
    return {"app.autostart-mode": f'"{mode}"'}
