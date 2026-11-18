"""
Backup and restore system (schema v2).

Layout of a session::

    backups/<timestamp>/
        metadata.json          -- what happened, versions, post-write hashes
        manifest.json          -- SHA-256 + size for every artefact
        prefs                  -- copy of Spotify's prefs file
        registry.json          -- exported HKCU startup values
        shortcuts.json         -- original shortcut arguments
        spicetify_config.ini   -- original Spicetify config

Guarantees
----------
* Every artefact is hashed and recorded in a manifest; the manifest can be
  re-verified at any time (``verify_integrity``).
* Restores detect that the live file changed after the optimisation
  (``conflict``) instead of silently overwriting newer Spotify state.
* ``cleanup_old_sessions`` never runs unless a positive retention count is
  explicitly requested; the engine defaults to keeping everything.
* Deleting a session is containment-checked and refuses paths outside the
  backup root.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .app_paths import backups_dir, is_within
from .logger import get_logger

log = get_logger("backup")

BACKUP_ROOT = backups_dir()
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 2

ARTIFACTS = ("prefs", "registry.json", "shortcuts.json", "spicetify_config.ini")


@dataclass
class BackupMetadata:
    created_at: str
    version: str = "2.0"
    prefs_backed_up: bool = False
    registry_backed_up: bool = False
    shortcuts_backed_up: bool = False
    spicetify_backed_up: bool = False
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    app_version: str = ""
    spotify_version: str = ""
    profile: str = ""
    operations: list[str] = field(default_factory=list)
    # sha256 of the live file *after* the optimisation wrote it — used to
    # detect external changes before a restore.
    post_write_hashes: dict[str, str] = field(default_factory=dict)
    integrity_ok: Optional[bool] = None


@dataclass
class IntegrityReport:
    ok: bool
    checked: int = 0
    missing: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)
    detail: str = ""

    def summary(self) -> str:
        if not self.checked and not self.missing and not self.mismatched:
            return "No manifest recorded for this session."
        if self.ok:
            return f"Integrity verified ({self.checked} artefact(s))."
        parts = []
        if self.missing:
            parts.append(f"missing: {', '.join(self.missing)}")
        if self.mismatched:
            parts.append(f"hash mismatch: {', '.join(self.mismatched)}")
        return "Integrity check failed — " + "; ".join(parts)


def _sha256_file(path: Path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 256), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _atomic_copy(src: Path, dest: Path) -> None:
    """Copy via a temporary file in the destination directory, then replace."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def restore_file_checked(src: Path, dest: Path) -> tuple[bool, str]:
    """
    Restore ``src`` over ``dest`` and verify the bytes actually landed.

    Returns ``(ok, message)``.
    """
    if not src.is_file():
        return False, f"backup file missing: {src.name}"
    expected = _sha256_file(src)
    if expected is None:
        return False, "backup file is unreadable"
    try:
        _atomic_copy(src, dest)
    except OSError as exc:
        return False, f"could not write {dest.name}: {exc}"
    actual = _sha256_file(dest)
    if actual != expected:
        return False, "verification failed: restored file does not match backup"
    return True, "restored and verified"


class BackupManager:
    def __init__(self, backup_root: Optional[Path] = None) -> None:
        self.root = Path(backup_root) if backup_root else BACKUP_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self.last_conflict: Optional[str] = None

    # ------------------------------------------------------------------
    # Create a new backup session
    # ------------------------------------------------------------------

    def create_session(self) -> Path:
        """Create a unique timestamped backup directory and return it."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session = self.root / stamp
        counter = 1
        while session.exists():
            session = self.root / f"{stamp}_{counter:02d}"
            counter += 1
        session.mkdir(parents=True, exist_ok=False)
        log.info(f"Backup session created: {session}")
        return session

    # ------------------------------------------------------------------
    # Prefs
    # ------------------------------------------------------------------

    def backup_prefs(self, session: Path, prefs_path: Path) -> bool:
        dest = session / "prefs"
        try:
            if prefs_path.exists():
                _atomic_copy(prefs_path, dest)
                return True
            log.warning(f"Prefs not found, skipping backup: {prefs_path}")
            return False
        except OSError as exc:
            log.error(f"Prefs backup error: {exc}")
            return False

    def restore_prefs(
        self,
        session: Path,
        prefs_path: Path,
        *,
        allow_conflict: bool = False,
    ) -> bool:
        """Restore prefs; refuses when Spotify changed them after optimisation."""
        src = session / "prefs"
        if not src.exists():
            log.error(f"Prefs backup missing in {session}")
            return False
        self.last_conflict = None
        if not allow_conflict and self.has_conflict(session, "prefs", prefs_path):
            self.last_conflict = (
                "Spotify preferences changed since this backup was taken."
            )
            log.warning(self.last_conflict)
            return False
        ok, message = restore_file_checked(src, prefs_path)
        if not ok:
            log.error(f"Prefs restore failed: {message}")
        return ok

    def has_conflict(self, session: Path, artifact: str, live_path: Path) -> bool:
        """
        True when the live file no longer matches what the optimisation wrote.

        A session without recorded post-write hashes cannot prove a conflict,
        so it reports ``False`` rather than blocking a legitimate restore.
        """
        metadata = self.read_metadata(session)
        if metadata is None:
            return False
        expected = metadata.post_write_hashes.get(artifact)
        if not expected:
            return False
        actual = _sha256_file(live_path)
        if actual is None:
            return False
        return actual != expected

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def backup_registry(self, session: Path, reg_data: dict[str, Any]) -> bool:
        dest = session / "registry.json"
        try:
            dest.write_text(json.dumps(reg_data, indent=2), encoding="utf-8")
            return True
        except OSError as exc:
            log.error(f"Registry backup error: {exc}")
            return False

    def restore_registry_data(self, session: Path) -> Optional[dict[str, Any]]:
        return self._read_json(session / "registry.json", expect=dict)

    # ------------------------------------------------------------------
    # Shortcuts
    # ------------------------------------------------------------------

    def backup_shortcuts(self, session: Path, shortcuts_data: list[dict]) -> bool:
        dest = session / "shortcuts.json"
        try:
            dest.write_text(json.dumps(shortcuts_data, indent=2), encoding="utf-8")
            return True
        except OSError as exc:
            log.error(f"Shortcuts backup error: {exc}")
            return False

    def restore_shortcuts_data(self, session: Path) -> Optional[list[dict]]:
        return self._read_json(session / "shortcuts.json", expect=list)

    # ------------------------------------------------------------------
    # Spicetify config
    # ------------------------------------------------------------------

    def backup_spicetify(self, session: Path, config_path: Path) -> bool:
        dest = session / "spicetify_config.ini"
        try:
            if config_path.exists():
                _atomic_copy(config_path, dest)
                return True
            return False
        except OSError as exc:
            log.error(f"Spicetify backup error: {exc}")
            return False

    def restore_spicetify(self, session: Path, config_path: Path) -> bool:
        src = session / "spicetify_config.ini"
        if not src.exists():
            log.error(f"Spicetify config backup missing in {session}")
            return False
        ok, message = restore_file_checked(src, config_path)
        if not ok:
            log.error(f"Spicetify restore failed: {message}")
        return ok

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def write_metadata(self, session: Path, meta: BackupMetadata) -> None:
        try:
            dest = session / "metadata.json"
            dest.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning(f"Could not write backup metadata: {exc}")

    def read_metadata(self, session: Path) -> Optional[BackupMetadata]:
        data = self._read_json(session / "metadata.json", expect=dict)
        if data is None:
            return None
        try:
            allowed = BackupMetadata.__dataclass_fields__
            return BackupMetadata(**{k: v for k, v in data.items() if k in allowed})
        except (TypeError, ValueError) as exc:
            log.warning(f"Could not parse backup metadata: {exc}")
            return None

    def update_post_write_hash(self, session: Path, artifact: str, digest: str) -> None:
        meta = self.read_metadata(session)
        if meta is None:
            return
        meta.post_write_hashes[artifact] = digest
        self.write_metadata(session, meta)

    # ------------------------------------------------------------------
    # Manifest / integrity
    # ------------------------------------------------------------------

    def write_manifest(self, session: Path) -> bool:
        """Hash every artefact currently present and write manifest.json."""
        files: dict[str, dict[str, Any]] = {}
        for name in ARTIFACTS:
            path = session / name
            if not path.is_file():
                continue
            digest = _sha256_file(path)
            if digest is None:
                continue
            files[name] = {"sha256": digest, "size": path.stat().st_size}
        if not files:
            return False
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "files": files,
        }
        try:
            (session / MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            return True
        except OSError as exc:
            log.error(f"Could not write backup manifest: {exc}")
            return False

    def verify_integrity(self, session: Path) -> IntegrityReport:
        """Re-hash artefacts and compare with the recorded manifest."""
        manifest = self._read_json(session / MANIFEST_NAME, expect=dict)
        if not manifest or "files" not in manifest:
            return IntegrityReport(ok=False, detail="No manifest recorded for this session.")

        report = IntegrityReport(ok=True)
        for name, info in manifest["files"].items():
            path = session / name
            report.checked += 1
            if not path.is_file():
                report.missing.append(name)
                continue
            if _sha256_file(path) != info.get("sha256"):
                report.mismatched.append(name)

        report.ok = not report.missing and not report.mismatched
        report.detail = report.summary()
        if not report.ok:
            log.warning(f"Backup integrity check failed for {session.name}: {report.detail}")
        return report

    # ------------------------------------------------------------------
    # Session discovery / reporting
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[Path]:
        """Return backup sessions sorted newest first."""
        sessions: list[Path] = []
        if not self.root.exists():
            return sessions
        for item in self.root.iterdir():
            if item.is_dir() and (item / "metadata.json").exists():
                sessions.append(item)
        return sorted(sessions, reverse=True)

    def get_latest_session(self) -> Optional[Path]:
        sessions = self.list_sessions()
        return sessions[0] if sessions else None

    def session_summary(self, session: Path) -> dict[str, Any]:
        """Everything the Backups page needs about one session."""
        meta = self.read_metadata(session)
        validation = self.validate_session(session)
        integrity = self.verify_integrity(session)
        size = 0
        for name in ARTIFACTS + ("metadata.json", MANIFEST_NAME):
            path = session / name
            if path.is_file():
                try:
                    size += path.stat().st_size
                except OSError:
                    pass
        return {
            "name": session.name,
            "path": str(session),
            "created_at": meta.created_at if meta else "unknown",
            "operations": list(meta.operations) if meta else [],
            "spotify_version": meta.spotify_version if meta else "",
            "profile": meta.profile if meta else "",
            "size_bytes": size,
            "artefacts": validation,
            "integrity_ok": integrity.ok,
            "integrity_detail": integrity.summary(),
            "has_manifest": (session / MANIFEST_NAME).is_file(),
        }

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

    def cleanup_old_sessions(self, keep: int = 0) -> None:
        """
        Remove old sessions, keeping the newest ``keep``.

        ``keep <= 0`` means "keep everything" — the default, because deleting a
        user's recovery snapshots is never an optimisation.
        """
        if keep <= 0:
            return
        sessions = self.list_sessions()
        for old in sessions[keep:]:
            try:
                if not is_within(old, self.root) or old.resolve() == self.root.resolve():
                    log.warning(f"Refusing to delete unexpected path: {old}")
                    continue
                shutil.rmtree(old)
                log.info(f"Removed old backup (retention={keep}): {old.name}")
            except OSError as exc:
                log.warning(f"Could not remove backup {old}: {exc}")

    def delete_session(self, session: Path) -> bool:
        """Explicitly delete one session (containment-checked)."""
        try:
            if not is_within(session, self.root) or session.resolve() == self.root.resolve():
                log.warning(f"Refusing to delete path outside backup root: {session}")
                return False
            shutil.rmtree(session)
            log.info(f"Deleted backup session: {session.name}")
            return True
        except OSError as exc:
            log.error(f"Could not delete backup session {session}: {exc}")
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _read_json(path: Path, expect: type) -> Any:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning(f"Could not read {path.name}: {exc}")
            return None
        if not isinstance(data, expect):
            log.warning(f"Unexpected structure in {path.name}")
            return None
        return data
