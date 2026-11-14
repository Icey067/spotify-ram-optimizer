"""
Spicetify integration module.

Detects, reads, and optionally modifies Spicetify configuration.
Never removes all customizations automatically.
Provides reversible actions only.
"""
from __future__ import annotations

import configparser
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .detector import SpicetifyInfo
from .logger import get_logger

log = get_logger("spicetify")


class SpicetifyManager:
    def __init__(self, info: SpicetifyInfo) -> None:
        self.info = info

    @property
    def is_available(self) -> bool:
        return self.info.is_installed and self.info.exe_path is not None

    # ------------------------------------------------------------------
    # Read config
    # ------------------------------------------------------------------

    def read_config(self) -> Optional[configparser.ConfigParser]:
        """Parse and return the Spicetify config-xpui.ini as ConfigParser."""
        if not self.info.config_path or not self.info.config_path.exists():
            return None
        try:
            cfg = configparser.ConfigParser(strict=False)
            cfg.read(str(self.info.config_path), encoding="utf-8")
            return cfg
        except Exception as e:
            log.error(f"Could not read Spicetify config: {e}")
            return None

    # ------------------------------------------------------------------
    # Apply (run spicetify apply)
    # ------------------------------------------------------------------

    def run_apply(self) -> tuple[bool, str]:
        """Run `spicetify apply` to apply pending changes."""
        if not self.is_available:
            return False, "Spicetify not found."
        try:
            result = subprocess.run(
                [str(self.info.exe_path), "apply"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                log.info("spicetify apply succeeded.")
                return True, result.stdout.strip()
            else:
                msg = result.stderr.strip() or result.stdout.strip()
                log.warning(f"spicetify apply failed: {msg}")
                return False, msg
        except subprocess.TimeoutExpired:
            return False, "spicetify apply timed out."
        except Exception as e:
            return False, str(e)

    def run_restore(self) -> tuple[bool, str]:
        """Run `spicetify restore` to revert Spicetify changes."""
        if not self.is_available:
            return False, "Spicetify not found."
        try:
            result = subprocess.run(
                [str(self.info.exe_path), "restore"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                log.info("spicetify restore succeeded.")
                return True, result.stdout.strip()
            else:
                return False, result.stderr.strip() or result.stdout.strip()
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # Disable optional extensions / custom apps
    # ------------------------------------------------------------------

    def disable_extensions(self, extensions: list[str]) -> bool:
        """
        Remove specific extensions from Spicetify config.
        Only removes items the user explicitly chose.
        """
        cfg = self.read_config()
        if cfg is None:
            return False
        try:
            if cfg.has_option("AdditionalOptions", "extensions"):
                current = cfg.get("AdditionalOptions", "extensions")
                parts = [p.strip() for p in current.split("|") if p.strip()]
                remaining = [p for p in parts if p not in extensions]
                cfg.set("AdditionalOptions", "extensions", "|".join(remaining))
            self._write_config(cfg)
            log.info(f"Disabled extensions: {extensions}")
            return True
        except Exception as e:
            log.error(f"Could not disable extensions: {e}")
            return False

    def disable_custom_apps(self, apps: list[str]) -> bool:
        cfg = self.read_config()
        if cfg is None:
            return False
        try:
            if cfg.has_option("AdditionalOptions", "custom_apps"):
                current = cfg.get("AdditionalOptions", "custom_apps")
                parts = [p.strip() for p in current.split("|") if p.strip()]
                remaining = [p for p in parts if p not in apps]
                cfg.set("AdditionalOptions", "custom_apps", "|".join(remaining))
            self._write_config(cfg)
            log.info(f"Disabled custom apps: {apps}")
            return True
        except Exception as e:
            log.error(f"Could not disable custom apps: {e}")
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_config(self, cfg: configparser.ConfigParser) -> None:
        if self.info.config_path is None:
            raise RuntimeError("No config path available.")
        with self.info.config_path.open("w", encoding="utf-8") as f:
            cfg.write(f)
        log.debug(f"Spicetify config written: {self.info.config_path}")
