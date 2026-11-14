r"""
Application configuration and persistent preferences.
Saves user GUI settings and default optimization preferences to %APPDATA%\SpotifyOptimizer\config.json.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .logger import get_logger

log = get_logger("config")

CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "SpotifyOptimizer"
CONFIG_FILE = CONFIG_DIR / "config.json"


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
    extra: dict[str, Any] = field(default_factory=dict)


def load_config() -> AppConfig:
    """Load configuration from disk or return defaults if missing/corrupt."""
    if not CONFIG_FILE.exists():
        return AppConfig()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        valid_fields = AppConfig.__dataclass_fields__
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return AppConfig(**filtered)
    except Exception as e:
        log.warning(f"Could not load config ({e}), using defaults")
        return AppConfig()


def save_config(config: AppConfig) -> bool:
    """Save configuration to disk atomically."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        content = json.dumps(asdict(config), indent=2)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        if CONFIG_FILE.exists():
            os.replace(tmp, CONFIG_FILE)
        else:
            os.rename(tmp, CONFIG_FILE)
        log.debug(f"Saved configuration to {CONFIG_FILE}")
        return True
    except Exception as e:
        log.error(f"Failed to save configuration: {e}")
        return False
