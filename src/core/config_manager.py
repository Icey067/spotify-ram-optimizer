"""
Application configuration and persistent preferences.

Stored as JSON under the application data directory.  Loading is defensive:
unknown keys are ignored, wrong types fall back to defaults, and numeric
values are clamped so a hand-edited file cannot put the UI or the sampler into
an unreasonable state.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .app_paths import config_file, ensure_dir
from .logger import get_logger

log = get_logger("config")

CONFIG_FILE = config_file()
CONFIG_DIR = CONFIG_FILE.parent

PROFILE_CHOICES = ("safe", "balanced", "advanced", "custom")


@dataclass
class AppConfig:
    appearance_mode: str = "Dark"
    ui_scale: str = "100%"
    auto_scan_on_startup: bool = True
    disable_hw_accel: bool = True
    set_cache_size: bool = True
    cache_size_mb: int = 512
    disable_autostart: bool = True
    clean_browser_cache: bool = True
    clean_code_cache: bool = True
    clean_gpu_cache: bool = False
    # --- New in 1.1 -----------------------------------------------------
    profile: str = "safe"
    monitoring_interval_seconds: int = 5
    history_retention_days: int = 90
    backup_retention: int = 0          # 0 = keep every backup
    restart_spotify_after_optimization: bool = True
    log_retention_days: int = 14
    enable_performance_history: bool = True
    confirm_before_apply: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


_BOOL_FIELDS = {
    "auto_scan_on_startup", "disable_hw_accel", "set_cache_size",
    "disable_autostart", "clean_browser_cache", "clean_code_cache",
    "clean_gpu_cache", "restart_spotify_after_optimization",
    "enable_performance_history", "confirm_before_apply",
}
_INT_BOUNDS = {
    "cache_size_mb": (0, 10240),
    "monitoring_interval_seconds": (2, 300),
    "history_retention_days": (0, 3650),
    "backup_retention": (0, 200),
    "log_retention_days": (1, 365),
}
_SCALE_CHOICES = ("90%", "100%", "110%", "125%")


def _coerce(key: str, value: Any) -> Any:
    if key in _BOOL_FIELDS:
        return bool(value) if isinstance(value, bool) else value
    if key in _INT_BOUNDS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be an integer")
        low, high = _INT_BOUNDS[key]
        return max(low, min(value, high))
    if key == "profile":
        return value if value in PROFILE_CHOICES else "safe"
    if key == "ui_scale":
        return value if value in _SCALE_CHOICES else "100%"
    if key == "appearance_mode":
        return value if value in ("Dark", "Light", "System") else "Dark"
    return value


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from disk, falling back to defaults on any problem."""
    target = Path(path) if path else CONFIG_FILE
    if not target.exists():
        return AppConfig()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning(f"Could not load config ({exc}); using defaults")
        return AppConfig()
    if not isinstance(data, dict):
        log.warning("Config file is not a JSON object; using defaults")
        return AppConfig()

    allowed = AppConfig.__dataclass_fields__
    filtered: dict[str, Any] = {}
    for key, value in data.items():
        if key not in allowed or key == "extra":
            continue
        try:
            filtered[key] = _coerce(key, value)
        except (TypeError, ValueError) as exc:
            log.warning(f"Ignoring invalid config value for {key}: {exc}")
    try:
        return AppConfig(**filtered)
    except TypeError as exc:
        log.warning(f"Config had unexpected fields ({exc}); using defaults")
        return AppConfig()


def save_config(config: AppConfig, path: Path | None = None) -> bool:
    """Save configuration atomically."""
    target = Path(path) if path else CONFIG_FILE
    try:
        ensure_dir(target.parent)
        content = json.dumps(asdict(config), indent=2)
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        log.debug(f"Saved configuration to {target}")
        return True
    except OSError as exc:
        log.error(f"Failed to save configuration: {exc}")
        return False
