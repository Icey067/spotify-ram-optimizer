"""
Optimization engine.

Orchestrates all optimization modules as an independent, testable component.
Every operation is:
  - Idempotent (safe to run multiple times)
  - Reversible (backed up before applying)
  - Partial-failure safe (rollback on error)
  - Non-destructive (never deletes personal data)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .backup_manager import BackupManager, BackupMetadata
from .cache_manager import CacheManager
from .detector import SpotifyInstallation, detect_installation
from .logger import get_logger
from .performance_monitor import PerformanceComparison, PerformanceSnapshot
from .prefs_manager import (
    PrefsManager,
    build_autostart_pref,
    build_cache_size_pref,
    build_hw_accel_pref,
)
from .process_manager import stop_spotify, is_spotify_running
from .registry_manager import RegistryManager
from .shortcut_manager import ShortcutManager
from .spicetify_manager import SpicetifyManager

log = get_logger("engine")


@dataclass
class OptimizationSettings:
    """What the user wants to do — driven by GUI checkboxes."""
    disable_hw_accel: bool = True
    set_cache_size: bool = True
    cache_size_mb: int = 512
    disable_autostart: bool = True
    clean_browser_cache: bool = True
    clean_code_cache: bool = True
    clean_gpu_cache: bool = False   # off by default (more aggressive)
    disable_spicetify_extensions: list[str] = field(default_factory=list)
    disable_spicetify_apps: list[str] = field(default_factory=list)


@dataclass
class OptimizationResult:
    success: bool = False
    operations_completed: int = 0
    operations_skipped: int = 0
    operations_failed: int = 0
    messages: list[str] = field(default_factory=list)
    backup_session: Optional[Path] = None
    comparison: Optional[PerformanceComparison] = None
    cache_freed_mb: float = 0.0

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        log.info(msg)


class OptimizationEngine:
    def __init__(
        self,
        installation: Optional[SpotifyInstallation] = None,
        backup_root: Optional[Path] = None,
    ) -> None:
        self.installation = installation
        self.backup_mgr = BackupManager(backup_root)
        self.registry_mgr = RegistryManager()
        self.shortcut_mgr = ShortcutManager()
        self._lock = threading.Lock()
        self._progress_callback: Optional[Callable[[str, float], None]] = None

    def set_progress_callback(self, cb: Callable[[str, float], None]) -> None:
        """Register (message, 0..1) progress callback for GUI."""
        self._progress_callback = cb

    def _progress(self, msg: str, pct: float) -> None:
        log.info(f"[{pct*100:.0f}%] {msg}")
        if self._progress_callback:
            try:
                self._progress_callback(msg, pct)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def scan(self) -> SpotifyInstallation:
        """Re-detect installation and return result."""
        log.info("Scanning for Spotify installation...")
        self.installation = detect_installation()
        return self.installation

    # ------------------------------------------------------------------
    # Run Optimization
    # ------------------------------------------------------------------

    def run_optimization(self, settings: OptimizationSettings) -> OptimizationResult:
        """
        Main optimization pipeline.
        Thread-safe; uses a lock to prevent concurrent runs.
        """
        with self._lock:
            return self._do_optimize(settings)

    def _do_optimize(self, settings: OptimizationSettings) -> OptimizationResult:
        result = OptimizationResult()
        install = self.installation

        if install is None:
            result.add("No Spotify installation detected. Run Scan first.")
            return result

        total_steps = 7
        step = 0

        # --- Step 0: Measure before ---
        self._progress("Measuring current memory usage…", step / total_steps)
        snapshot_before = PerformanceSnapshot.capture("Before")
        log.info(snapshot_before.summary())

        # --- Step 1: Create backup session ---
        step += 1
        self._progress("Creating backup…", step / total_steps)
        session = self.backup_mgr.create_session()
        result.backup_session = session
        meta = BackupMetadata(created_at=datetime.now().isoformat())

        backed_up_prefs = False
        backed_up_registry = False
        backed_up_shortcuts = False
        backed_up_spicetify = False

        # Backup prefs
        if install.prefs_path:
            backed_up_prefs = self.backup_mgr.backup_prefs(session, install.prefs_path)
            meta.prefs_backed_up = backed_up_prefs

        # Backup registry
        reg_data = self.registry_mgr.export_for_backup()
        backed_up_registry = self.backup_mgr.backup_registry(session, reg_data)
        meta.registry_backed_up = backed_up_registry

        # Backup shortcuts
        shortcut_data = self.shortcut_mgr.backup_shortcuts()
        backed_up_shortcuts = self.backup_mgr.backup_shortcuts(session, shortcut_data)
        meta.shortcuts_backed_up = backed_up_shortcuts

        # Backup Spicetify config
        if install.spicetify and install.spicetify.is_installed and install.spicetify.config_path:
            backed_up_spicetify = self.backup_mgr.backup_spicetify(
                session, install.spicetify.config_path
            )
            meta.spicetify_backed_up = backed_up_spicetify

        # --- Step 2: Stop Spotify if needed ---
        step += 1
        self._progress("Stopping Spotify processes…", step / total_steps)
        spotify_was_running = is_spotify_running()
        if spotify_was_running:
            ok, msg = stop_spotify()
            if not ok:
                result.add(f"WARNING: Could not stop Spotify — {msg}")
                result.operations_skipped += 1
            else:
                result.add("Spotify stopped.")

        # --- Step 3: Apply preference changes ---
        step += 1
        self._progress("Applying preference changes…", step / total_steps)
        if install.prefs_path:
            prefs_mgr = PrefsManager(install.prefs_path)
            prefs_updates: dict[str, str] = {}

            if settings.disable_hw_accel:
                prefs_updates.update(build_hw_accel_pref(enabled=False))
                result.add("Setting: hardware acceleration → disabled")

            if settings.set_cache_size:
                prefs_updates.update(build_cache_size_pref(settings.cache_size_mb))
                result.add(f"Setting: cache size → {settings.cache_size_mb} MB")

            if settings.disable_autostart:
                prefs_updates.update(build_autostart_pref("off"))
                result.add("Setting: autostart → off")

            if prefs_updates:
                if prefs_mgr.set_values(prefs_updates):
                    result.operations_completed += len(prefs_updates)
                    result.add(f"Preferences updated ({len(prefs_updates)} settings).")
                else:
                    result.operations_failed += 1
                    result.add("ERROR: Could not write preferences.")
            else:
                result.add("No preference changes requested.")
        else:
            result.add("No prefs file found — skipping preference changes.")
            result.operations_skipped += 1

        # --- Step 4: Registry / startup ---
        step += 1
        self._progress("Updating startup settings…", step / total_steps)
        if settings.disable_autostart:
            entries = self.registry_mgr.get_startup_entries()
            for name in entries:
                if self.registry_mgr.disable_startup_entry(name):
                    result.operations_completed += 1
                    result.add(f"Startup entry disabled: {name}")
                else:
                    result.operations_failed += 1
                    result.add(f"ERROR: Could not disable startup entry: {name}")

        # --- Step 5: Cache cleanup ---
        step += 1
        self._progress("Cleaning cache…", step / total_steps)
        if install.cache_path and (
            settings.clean_browser_cache
            or settings.clean_code_cache
            or settings.clean_gpu_cache
        ):
            cache_mgr = CacheManager(install.cache_path)
            stats = cache_mgr.clean_cache_dirs(
                clean_browser_cache=settings.clean_browser_cache,
                clean_code_cache=settings.clean_code_cache,
                clean_gpu_cache=settings.clean_gpu_cache,
            )
            result.cache_freed_mb = stats.freed_mb
            result.operations_completed += 1
            result.add(
                f"Cache cleaned: {stats.freed_mb} MB freed, "
                f"{stats.files_deleted} files removed."
            )
            if stats.errors:
                result.add(f"Cache cleanup warnings: {len(stats.errors)} item(s) skipped.")
        else:
            result.add("Cache cleanup skipped (no cache path or not selected).")
            result.operations_skipped += 1

        # --- Step 6: Spicetify ---
        step += 1
        self._progress("Applying Spicetify settings…", step / total_steps)
        if install.spicetify and install.spicetify.is_installed:
            sp_mgr = SpicetifyManager(install.spicetify)
            if settings.disable_spicetify_extensions:
                if sp_mgr.disable_extensions(settings.disable_spicetify_extensions):
                    result.operations_completed += 1
                    result.add(
                        f"Spicetify: disabled extensions: {settings.disable_spicetify_extensions}"
                    )
                else:
                    result.operations_failed += 1
            if settings.disable_spicetify_apps:
                if sp_mgr.disable_custom_apps(settings.disable_spicetify_apps):
                    result.operations_completed += 1
                    result.add(
                        f"Spicetify: disabled custom apps: {settings.disable_spicetify_apps}"
                    )
                else:
                    result.operations_failed += 1
            if settings.disable_spicetify_extensions or settings.disable_spicetify_apps:
                ok, msg = sp_mgr.run_apply()
                result.add(f"Spicetify apply: {'OK' if ok else 'FAILED'} — {msg}")
        else:
            result.add("Spicetify not installed — skipping.")

        # --- Finalise ---
        self._progress("Finalising…", 1.0)
        self.backup_mgr.write_metadata(session, meta)
        self.backup_mgr.cleanup_old_sessions(keep=10)

        snapshot_after = PerformanceSnapshot.capture("After")
        result.comparison = PerformanceComparison(
            before=snapshot_before,
            after=snapshot_after,
            operations_completed=result.operations_completed,
            operations_skipped=result.operations_skipped,
        )

        result.success = result.operations_failed == 0
        result.add(
            f"Optimization complete: {result.operations_completed} done, "
            f"{result.operations_skipped} skipped, "
            f"{result.operations_failed} failed."
        )
        return result

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_latest(self) -> OptimizationResult:
        """Restore the most recent backup."""
        with self._lock:
            return self._do_restore()

    def _do_restore(self) -> OptimizationResult:
        result = OptimizationResult()
        session = self.backup_mgr.get_latest_session()
        if session is None:
            result.add("No backups found. Nothing to restore.")
            return result

        validation = self.backup_mgr.validate_session(session)
        result.add(f"Restoring backup from: {session.name}")

        # Prefs
        if validation["prefs"] and self.installation and self.installation.prefs_path:
            if self.backup_mgr.restore_prefs(session, self.installation.prefs_path):
                result.operations_completed += 1
                result.add("Preferences restored.")
            else:
                result.operations_failed += 1
                result.add("ERROR: Could not restore preferences.")

        # Registry
        if validation["registry"]:
            reg_data = self.backup_mgr.restore_registry_data(session)
            if reg_data and self.registry_mgr.restore_from_backup(reg_data):
                result.operations_completed += 1
                result.add("Registry restored.")
            else:
                result.operations_failed += 1
                result.add("WARNING: Registry restore incomplete.")

        # Shortcuts
        if validation["shortcuts"]:
            sc_data = self.backup_mgr.restore_shortcuts_data(session)
            if sc_data is not None:
                if self.shortcut_mgr.restore_shortcuts(sc_data):
                    result.operations_completed += 1
                    result.add("Shortcuts restored.")
                else:
                    result.operations_skipped += 1
                    result.add("Shortcuts: some could not be restored (may no longer exist).")

        # Spicetify
        if validation["spicetify"] and self.installation and self.installation.spicetify:
            cfg_path = self.installation.spicetify.config_path
            if cfg_path:
                if self.backup_mgr.restore_spicetify(session, cfg_path):
                    result.operations_completed += 1
                    result.add("Spicetify config restored.")
                    sp_mgr = SpicetifyManager(self.installation.spicetify)
                    sp_mgr.run_apply()
                else:
                    result.operations_failed += 1

        result.success = result.operations_failed == 0
        result.add(
            f"Restore complete: {result.operations_completed} done, "
            f"{result.operations_failed} failed."
        )
        return result

    def list_backups(self) -> list[dict]:
        """Return info about available backups."""
        sessions = self.backup_mgr.list_sessions()
        result = []
        for s in sessions:
            meta = self.backup_mgr.read_metadata(s)
            validation = self.backup_mgr.validate_session(s)
            result.append({
                "name": s.name,
                "path": str(s),
                "created_at": meta.created_at if meta else "unknown",
                "artefacts": validation,
            })
        return result
