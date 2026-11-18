"""
Centralised application path resolution.

Every module that needs to know where the application stores its own data
(config, backups, logs, performance history) goes through this module.

Rules:
  - Never hardcode a user profile directory.
  - Honour the ``SPOTIFY_OPTIMIZER_HOME`` override so tests and portable
    deployments can relocate all application state in one place.
  - All paths are plain :class:`pathlib.Path` objects; nothing is created
    as an import side effect.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_DIR_NAME = "SpotifyOptimizer"
HOME_ENV_VAR = "SPOTIFY_OPTIMIZER_HOME"


def app_data_dir() -> Path:
    """Root directory for all application-owned state."""
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override).expanduser()
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME
    # Non-Windows / unusual environments.
    return Path.home() / f".{APP_DIR_NAME.lower()}"


def backups_dir() -> Path:
    return app_data_dir() / "backups"


def logs_dir() -> Path:
    return app_data_dir() / "logs"


def config_file() -> Path:
    return app_data_dir() / "config.json"


def history_db() -> Path:
    return app_data_dir() / "history.db"


def resource_path(relative: str) -> Path:
    """Locate a bundled read-only resource (icon, theme asset) at runtime."""
    bundle = getattr(sys, "_MEIPASS", None)
    base = Path(bundle) if bundle else Path(__file__).resolve().parent.parent.parent
    return base / relative


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_within(child: Path, parent: Path) -> bool:
    """
    True only when ``child`` really lives inside ``parent``.

    Uses resolved paths so ``..`` segments, symlinks and Windows junctions
    cannot be used to escape the intended directory.
    """
    try:
        resolved_child = child.resolve()
        resolved_parent = parent.resolve()
    except (OSError, RuntimeError):
        return False
    if resolved_child == resolved_parent:
        return True
    try:
        resolved_child.relative_to(resolved_parent)
        return True
    except ValueError:
        return False


# Windows and POSIX profile directories, matched anywhere in a string so a
# nested path cannot leak the account name just because it is not the prefix
# of the text being redacted.
_WINDOWS_PROFILE = re.compile(
    r"[A-Za-z]:\\Users\\[^\\/:*?\"<>|\r\n]+", re.IGNORECASE
)
_POSIX_PROFILE = re.compile(r"/(?:home|Users)/[^/\s:\"'<>]+")


def _profile_candidates() -> list[str]:
    values = []
    for env_var in ("USERPROFILE", "HOME"):
        value = os.environ.get(env_var)
        if value:
            values.append(value)
    return sorted(set(values), key=len, reverse=True)


def redact_text(text: str) -> str:
    """
    Replace user-profile paths with ``%USERPROFILE%`` anywhere in ``text``.

    Handles the current ``USERPROFILE`` and ``HOME`` prefixes, plus
    Windows-style (``C:\\Users\\name``) and POSIX-style
    (``/home/name``, ``/Users/name``) profile paths found later in the text.
    Redaction is only ever additive: a value that is not a profile path is
    returned unchanged.
    """
    result = str(text)
    for candidate in _profile_candidates():
        result = re.sub(
            re.escape(candidate), "%USERPROFILE%", result, flags=re.IGNORECASE
        )
    result = _WINDOWS_PROFILE.sub("%USERPROFILE%", result)
    result = _POSIX_PROFILE.sub("%USERPROFILE%", result)
    return result


def redact_path(path: str | os.PathLike[str]) -> str:
    """
    Replace the current user profile prefix with ``%USERPROFILE%``.

    Used when producing diagnostic reports the user may share publicly.
    """
    return redact_text(str(path))
