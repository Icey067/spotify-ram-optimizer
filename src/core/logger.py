"""
Centralised logging.

* One file per application session inside ``%APPDATA%\\SpotifyOptimizer\\logs``
  (or ``$SPOTIFY_OPTIMIZER_HOME``).
* Old session logs are pruned at start-up so the folder cannot grow without
  bound.  Only files this application created (``optimizer_*.log``) are
  considered.
* A bounded in-memory ring buffer feeds the Activity page; it never grows past
  ``MAX_BUFFER_ENTRIES`` no matter how long the app runs.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .app_paths import ensure_dir, logs_dir

MAX_BUFFER_ENTRIES = 2000
DEFAULT_RETENTION_DAYS = 14
DEFAULT_MAX_FILES = 40

LOG_DIR = ensure_dir(logs_dir())


def _prune_old_logs(retention_days: int = DEFAULT_RETENTION_DAYS,
                    max_files: int = DEFAULT_MAX_FILES) -> None:
    """Delete stale session logs. Best-effort; never raises."""
    try:
        files = sorted(
            (p for p in LOG_DIR.glob("optimizer_*.log") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return

    cutoff = datetime.now().timestamp() - retention_days * 86400
    for index, path in enumerate(files):
        try:
            too_many = index >= max_files
            too_old = path.stat().st_mtime < cutoff
            if too_many or too_old:
                path.unlink()
        except OSError:
            continue


_prune_old_logs()

_log_file = LOG_DIR / f"optimizer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)

_root = logging.getLogger("SpotifyOptimizer")
_root.setLevel(logging.DEBUG)
_root.addHandler(_file_handler)

if os.environ.get("SPOTIFY_OPT_DEBUG"):
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    _root.addHandler(_console_handler)

# In-memory ring buffer for the GUI
_gui_entries: list[tuple[str, str, str]] = []
_gui_lock = threading.Lock()
_gui_callbacks: list[Callable[[str, str, str], None]] = []


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"SpotifyOptimizer.{name}")


def _emit_gui(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    entry = (ts, level, msg)
    with _gui_lock:
        _gui_entries.append(entry)
        if len(_gui_entries) > MAX_BUFFER_ENTRIES:
            del _gui_entries[: len(_gui_entries) - MAX_BUFFER_ENTRIES]
        callbacks = list(_gui_callbacks)
    for callback in callbacks:
        try:
            callback(*entry)
        except Exception:
            # A GUI callback must never break logging.
            pass


def register_gui_callback(cb: Callable[[str, str, str], None]) -> None:
    """Register ``fn(timestamp, level, message)`` for each log entry."""
    with _gui_lock:
        if cb not in _gui_callbacks:
            _gui_callbacks.append(cb)


def unregister_gui_callback(cb: Callable[[str, str, str], None]) -> None:
    with _gui_lock:
        try:
            _gui_callbacks.remove(cb)
        except ValueError:
            pass


def get_recent_entries(n: int = 200) -> list[tuple[str, str, str]]:
    with _gui_lock:
        return list(_gui_entries[-n:])


def get_log_file_path() -> Path:
    return _log_file


def get_log_dir() -> Path:
    return LOG_DIR


def clear_log_buffer() -> None:
    """Empty the in-memory buffer (the file log is kept)."""
    with _gui_lock:
        _gui_entries.clear()


def delete_session_logs() -> int:
    """
    Delete this application's log files and start a fresh one.

    Returns the number of files removed.  The active log file is re-opened.
    """
    global _log_file, _file_handler
    removed = 0
    try:
        _root.removeHandler(_file_handler)
        _file_handler.close()
    except Exception:
        pass
    for path in LOG_DIR.glob("optimizer_*.log"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    _log_file = LOG_DIR / f"optimizer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    _file_handler = logging.FileHandler(_log_file, encoding="utf-8")
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    _root.addHandler(_file_handler)
    return removed


class GUILogHandler(logging.Handler):
    """Bridge Python logging → GUI callback."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _emit_gui(record.levelname, self.format(record))
        except Exception:
            pass


_gui_handler = GUILogHandler()
_gui_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
_root.addHandler(_gui_handler)


# Convenience wrappers -------------------------------------------------------

def info(msg: str) -> None:
    _root.info(msg)


def warning(msg: str) -> None:
    _root.warning(msg)


def error(msg: str) -> None:
    _root.error(msg)


def debug(msg: str) -> None:
    _root.debug(msg)


def success(msg: str) -> None:
    _root.info(f"[OK] {msg}")
