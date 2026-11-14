"""
Centralized logging module for Spotify RAM Optimizer.
Writes to both file and in-memory log for GUI display.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


LOG_DIR = Path(os.environ.get("APPDATA", ".")) / "SpotifyOptimizer" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_log_file = LOG_DIR / f"optimizer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# File handler
_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)

_root = logging.getLogger("SpotifyOptimizer")
_root.setLevel(logging.DEBUG)
_root.addHandler(_file_handler)

# Console handler (DEBUG builds)
if os.environ.get("SPOTIFY_OPT_DEBUG"):
    _ch = logging.StreamHandler()
    _ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    _root.addHandler(_ch)

# In-memory ring buffer for GUI
_gui_entries: list[tuple[str, str, str]] = []  # (timestamp, level, message)
_gui_lock = threading.Lock()
_gui_callbacks: list[Callable[[str, str, str], None]] = []


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"SpotifyOptimizer.{name}")


def _emit_gui(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    entry = (ts, level, msg)
    with _gui_lock:
        _gui_entries.append(entry)
        if len(_gui_entries) > 2000:
            _gui_entries.pop(0)
        callbacks = list(_gui_callbacks)
    for cb in callbacks:
        try:
            cb(*entry)
        except Exception:
            pass


def register_gui_callback(cb: Callable[[str, str, str], None]) -> None:
    """Register a function called with (timestamp, level, message) for each log entry."""
    with _gui_lock:
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


class GUILogHandler(logging.Handler):
    """Bridges Python logging → GUI callback."""

    def emit(self, record: logging.LogRecord) -> None:
        level = record.levelname
        msg = self.format(record)
        _emit_gui(level, msg)


_gui_handler = GUILogHandler()
_gui_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
_root.addHandler(_gui_handler)


# Convenience wrappers
def info(msg: str) -> None:
    _root.info(msg)
    _emit_gui("INFO", msg)


def warning(msg: str) -> None:
    _root.warning(msg)
    _emit_gui("WARNING", msg)


def error(msg: str) -> None:
    _root.error(msg)
    _emit_gui("ERROR", msg)


def debug(msg: str) -> None:
    _root.debug(msg)
    _emit_gui("DEBUG", msg)


def success(msg: str) -> None:
    _root.info(f"[OK] {msg}")
    _emit_gui("SUCCESS", f"[OK] {msg}")
