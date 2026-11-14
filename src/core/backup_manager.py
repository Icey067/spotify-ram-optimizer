"""
Backup and Restore system.

Every optimization must be reversible.
Backup schema:
  backups/<timestamp>/
    metadata.json       -- what was backed up and when
    prefs               -- copy of Spotify prefs file
    registry.json       -- exported registry values
    shortcuts.json      -- original shortcut arguments
    spicetify_config.ini -- original Spicetify config
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .logger import get_logger

log = get_logger("backup")

BACKUP_ROOT = Path(os.environ.get("APPDATA", ".")) / "SpotifyOptimizer" / "backups"


@dataclass
class BackupMetadata:
    created_at: str
    version: str = "1.0"
    prefs_backed_up: bool = False
    registry_backed_up: bool = False
    shortcuts_backed_up: bool = False
    spicetify_backed_up: bool = False
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class BackupManager:
    def __init__(self, backup_root: Optional[Path] = None) -> None:
        self.root = backup_root or BACKUP_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Create a new backup session
    # ------------------------------------------------------------------

    def create_session(self) -> Path:
        """Create a timestamped backup directory and return its path."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        session = self.root / ts
        session.mkdir(parents=True, exist_ok=True)
        log.info(f"Backup session created: {session}")
        return session

    # ------------------------------------------------------------------
    # Prefs
    # ------------------------------------------------------------------

    def backup_prefs(self, session: Path, prefs_path: Path) -> bool:
        dest = session / "prefs"
        try:
            if prefs_path.exists():
                shutil.copy2(prefs_path, dest)
                log.info(f"Prefs backed up → {dest}")
                return True
            else:
                log.warning(f"Prefs not found, skipping backup: {prefs_path}")
                return False
        except Exception as e:
            log.error(f"Prefs backup error: {e}")
            return False

    def restore_prefs(self, session: Path, prefs_path: Path) -> bool:
        src = session / "prefs"
        if not src.exists():
            log.error(f"Prefs backup missing in {session}")
            return False
        try:
            shutil.copy2(src, prefs_path)
            log.info(f"Prefs restored ← {src}")
            return True
        except Exception as e:
            log.error(f"Prefs restore error: {e}")
            return False

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def backup_registry(self, session: Path, reg_data: dict[str, Any]) -> bool:
        dest = session / "registry.json"
        try:
            dest.write_text(json.dumps(reg_data, indent=2), encoding="utf-8")
            log.info(f"Registry backed up → {dest}")
            return True
        except Exception as e:
            log.error(f"Registry backup error: {e}")
            return False

    def restore_registry_data(self, session: Path) -> Optional[dict[str, Any]]:
        src = session / "registry.json"
        if not src.exists():
            log.error(f"Registry backup missing in {session}")
            return None
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            log.info(f"Registry data loaded from {src}")
            return data
        except Exception as e:
            log.error(f"Registry backup read error: {e}")
            return None

    # ------------------------------------------------------------------
    # Shortcuts
    # ------------------------------------------------------------------

    def backup_shortcuts(self, session: Path, shortcuts_data: list[dict]) -> bool:
        dest = session / "shortcuts.json"
        try:
            dest.write_text(json.dumps(shortcuts_data, indent=2), encoding="utf-8")
            log.info(f"Shortcuts backed up → {dest}")
            return True
        except Exception as e:
            log.error(f"Shortcuts backup error: {e}")
            return False

    def restore_shortcuts_data(self, session: Path) -> Optional[list[dict]]:
        src = session / "shortcuts.json"
        if not src.exists():
            log.error(f"Shortcuts backup missing in {session}")
            return None
        try:
            return json.loads(src.read_text(encoding="utf-8"))
        except Exception as e:
            log.error(f"Shortcuts backup read error: {e}")
            return None

    # ------------------------------------------------------------------
    # Spicetify config
    # ------------------------------------------------------------------

    def backup_spicetify(self, session: Path, config_path: Path) -> bool:
        dest = session / "spicetify_config.ini"
        try:
            if config_path.exists():
                shutil.copy2(config_path, dest)
                log.info(f"Spicetify config backed up → {dest}")
                return True
            return False
        except Exception as e:
            log.error(f"Spicetify backup error: {e}")
            return False

    def restore_spicetify(self, session: Path, config_path: Path) -> bool:
        src = session / "spicetify_config.ini"
        if not src.exists():
            log.error(f"Spicetify config backup missing in {session}")
            return False
        try:
            shutil.copy2(src, config_path)
            log.info(f"Spicetify config restored ← {src}")
            return True
        except Exception as e:
            log.error(f"Spicetify restore error: {e}")
            return False

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def write_metadata(self, session: Path, meta: BackupMetadata) -> None:
        try:
            dest = session / "metadata.json"
            dest.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")
        except Exception as e:
            log.warning(f"Could not write backup metadata: {e}")

    def read_metadata(self, session: Path) -> Optional[BackupMetadata]:
        src = session / "metadata.json"
        if not src.exists():
            return None
        try:
            d = json.loads(src.read_text(encoding="utf-8"))
            return BackupMetadata(**{k: v for k, v in d.items() if k in BackupMetadata.__dataclass_fields__})
        except Exception as e:
            log.warning(f"Could not read backup metadata: {e}")
            return None

    # ------------------------------------------------------------------
    # Session discovery
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[Path]:
        """Return backup sessions sorted newest first."""
        sessions = []
        if not self.root.exists():
            return sessions
        for item in self.root.iterdir():
            if item.is_dir() and (item / "metadata.json").exists():
                sessions.append(item)
        return sorted(sessions, reverse=True)

    def get_latest_session(self) -> Optional[Path]:
        sessions = self.list_sessions()
        return sessions[0] if sessions else None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_session(self, session: Path) -> dict[str, bool]:
        """Check which backup artefacts exist in a session."""
        return {
            "prefs": (session / "prefs").exists(),
            "registry": (session / "registry.json").exists(),
            "shortcuts": (session / "shortcuts.json").exists(),
            "spicetify": (session / "spicetify_config.ini").exists(),
            "metadata": (session / "metadata.json").exists(),
        }

    def cleanup_old_sessions(self, keep: int = 10) -> None:
        """Keep only the most recent `keep` sessions."""
        sessions = self.list_sessions()
        for old in sessions[keep:]:
            try:
                shutil.rmtree(old)
                log.info(f"Removed old backup: {old.name}")
            except Exception as e:
                log.warning(f"Could not remove backup {old}: {e}")
