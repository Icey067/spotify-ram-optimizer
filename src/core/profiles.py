"""
Custom optimization profiles (versioned JSON).

A profile is *data only*: a list of known operation ids plus a cache size.  It
can never carry a command, a path, a script or an arbitrary setting, because
validation rejects anything that is not an explicitly known field with an
explicitly known value.

This is the security boundary for importing a profile a user downloaded from
somewhere else: the worst a malicious file can do is name a different subset of
operations the application already implements.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .app_paths import app_data_dir, ensure_dir, is_within
from .logger import get_logger
from .optimizations import OPERATIONS_BY_ID

log = get_logger("profiles")

SCHEMA_VERSION = 1
MAX_NAME_LENGTH = 64
MAX_FILE_BYTES = 64 * 1024
ALLOWED_KEYS = frozenset({"schema_version", "name", "operations", "cache_size_mb", "notes"})
_INVALID_NAME_CHARS = set('<>:"/\\|?*')


class ProfileError(ValueError):
    """Raised when a profile file is malformed or unsafe."""


@dataclass
class Profile:
    name: str
    operations: list[str] = field(default_factory=list)
    cache_size_mb: int = 512
    schema_version: int = SCHEMA_VERSION
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "operations": list(self.operations),
            "cache_size_mb": int(self.cache_size_mb),
            "notes": self.notes,
        }


def profiles_dir() -> Path:
    return app_data_dir() / "profiles"


def validate_profile(data: Any) -> Profile:
    """Validate untrusted JSON and return a :class:`Profile`."""
    if not isinstance(data, dict):
        raise ProfileError("Profile must be a JSON object.")

    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        raise ProfileError(
            f"Unsupported field(s) in profile: {', '.join(sorted(unknown))}. "
            "Profiles may only describe known optimisation settings."
        )

    version = data.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise ProfileError(
            f"Unsupported profile schema version: {version!r}. "
            f"This build understands version {SCHEMA_VERSION}."
        )

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProfileError("Profile name must be a non-empty string.")
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH:
        raise ProfileError(f"Profile name must be at most {MAX_NAME_LENGTH} characters.")
    if any(character in _INVALID_NAME_CHARS for character in name):
        raise ProfileError("Profile name contains characters that are not allowed.")

    operations = data.get("operations", [])
    if not isinstance(operations, list) or not all(isinstance(op, str) for op in operations):
        raise ProfileError("Profile operations must be a list of operation ids.")
    unknown_ops = [op for op in operations if op not in OPERATIONS_BY_ID]
    if unknown_ops:
        raise ProfileError(
            "Profile references unknown operation(s): " + ", ".join(unknown_ops)
        )

    cache_size = data.get("cache_size_mb", 512)
    if isinstance(cache_size, bool) or not isinstance(cache_size, int):
        raise ProfileError("cache_size_mb must be an integer.")
    if not 0 <= cache_size <= 10240:
        raise ProfileError("cache_size_mb must be between 0 and 10240.")

    notes = data.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 500:
        raise ProfileError("notes must be a string of at most 500 characters.")

    # De-duplicate while keeping registry order for determinism.
    ordered = [op for op in OPERATIONS_BY_ID if op in set(operations)]
    return Profile(
        name=name,
        operations=ordered,
        cache_size_mb=cache_size,
        schema_version=SCHEMA_VERSION,
        notes=notes,
    )


def import_profile(path: Path) -> Profile:
    """Read and validate a profile file. Raises :class:`ProfileError`."""
    file_path = Path(path)
    try:
        if file_path.stat().st_size > MAX_FILE_BYTES:
            raise ProfileError("Profile file is too large to be a valid profile.")
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"Could not read profile: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProfileError(f"Profile is not valid JSON: {exc}") from exc
    return validate_profile(data)


def export_profile(profile: Profile, path: Path) -> None:
    """Write a profile atomically. Raises :class:`ProfileError` on failure."""
    # Validate what we are about to write, so an internal bug cannot produce a
    # file this application would refuse to import.
    validated = validate_profile(profile.to_dict())
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(validated.to_dict(), handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        raise ProfileError(f"Could not write profile: {exc}") from exc


def save_profile(profile: Profile) -> Path:
    """Save a profile into the application's own profile store."""
    validated = validate_profile(profile.to_dict())
    directory = ensure_dir(profiles_dir())
    target = directory / f"{validated.name}.json"
    export_profile(validated, target)
    return target


def list_saved_profiles() -> list[Profile]:
    """Load every valid profile from the application store."""
    directory = profiles_dir()
    if not directory.is_dir():
        return []
    result: list[Profile] = []
    for path in sorted(directory.glob("*.json")):
        try:
            result.append(import_profile(path))
        except ProfileError as exc:
            log.warning(f"Skipping invalid saved profile {path.name}: {exc}")
    return result


def delete_saved_profile(name: str) -> bool:
    """Delete a saved profile by name (containment-checked)."""
    directory = profiles_dir()
    candidate = directory / f"{name}.json"
    if not is_within(candidate, directory) or candidate.parent.resolve() != directory.resolve():
        return False
    try:
        candidate.unlink()
        return True
    except OSError:
        return False
