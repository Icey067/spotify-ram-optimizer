"""
Optimization engine.

Pipeline (every stage is explicit and logged):

    1. environment + compatibility detection
    2. plan (dry-run capable, read-only)
    3. sampled "before" measurement
    4. backup session -> manifest -> integrity verification
    5. Spotify process handling (only when the plan requires it)
    6. per-change execution with verification
    7. rollback when a critical change fails
    8. sampled "after" measurement (honest comparability)
    9. history recording + retention

Safety defaults
---------------
* Registry writes are disabled unless ``allow_registry_changes=True`` is
  passed.  The GUI passes ``True``; library/test callers stay read-only unless
  they opt in, so importing the engine can never modify a machine's startup
  configuration by accident.
* Backups are pruned only when a positive retention count is configured.
* Spotify is restarted only when the caller explicitly asks for it.
"""
from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import benchmark
from .backup_manager import BackupManager, BackupMetadata
from .cache_manager import CacheManager
from .compatibility import Environment, detect_environment
from .detector import SpotifyInstallation, detect_installation
from .history import HistoryStore
from .logger import get_logger
from .optimizations import (
    OPERATIONS_BY_ID,
    Plan,
    Optimizer,
    build_plan,
    request_from_settings,
)
from .performance_monitor import PerformanceComparison, PerformanceSnapshot
from .prefs_manager import PrefsManager
from .process_manager import (
    is_spotify_running,
    launch_spotify,
    stop_spotify,
)
from .registry_manager import RegistryManager
from .shortcut_manager import ShortcutManager
from .spicetify_manager import SpicetifyManager

log = get_logger("engine")

APP_VERSION = "1.1.1"


@dataclass
class OptimizationSettings:
    """What the user wants to do — driven by GUI checkboxes."""
    disable_hw_accel: bool = True
    set_cache_size: bool = True
    cache_size_mb: int = 512
    disable_autostart: bool = True
    clean_browser_cache: bool = True
    clean_code_cache: bool = True
    clean_gpu_cache: bool = False
    # Writing app.autostart-mode is unverified, so it is opt-in.
    set_autostart_pref: bool = False
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
    rolled_back: bool = False
    plan: Optional[Plan] = None
    conflicts: list[str] = field(default_factory=list)
    # Which components conflicted, and why — consumed by the restore dialog.
    conflicts_by_component: dict[str, str] = field(default_factory=dict)

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        log.info(msg)


class OptimizationEngine:
    def __init__(
        self,
        installation: Optional[SpotifyInstallation] = None,
        backup_root: Optional[Path] = None,
        *,
        history: Optional[HistoryStore] = None,
    ) -> None:
        self.installation = installation
        self.backup_mgr = BackupManager(backup_root)
        self.registry_mgr = RegistryManager()
        self.shortcut_mgr = ShortcutManager()
        self.history = history
        self.environment: Optional[Environment] = None
        self._lock = threading.Lock()
        self._progress_callback: Optional[Callable[[str, float], None]] = None

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def set_progress_callback(self, cb: Callable[[str, float], None]) -> None:
        """Register ``(message, 0..1)`` progress callback for the GUI."""
        self._progress_callback = cb

    def _progress(self, msg: str, pct: float) -> None:
        log.debug(f"[{pct * 100:.0f}%] {msg}")
        if self._progress_callback:
            try:
                self._progress_callback(msg, pct)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Scan / preview
    # ------------------------------------------------------------------

    def scan(self) -> SpotifyInstallation:
        """Re-detect installation and return the result."""
        log.info("Scanning for Spotify installation…")
        self.installation = detect_installation()
        return self.installation

    def build_environment(self) -> Environment:
        self.environment = detect_environment(
            self.installation, registry=self.registry_mgr
        )
        return self.environment

    def preview(self, settings: OptimizationSettings) -> Plan:
        """
        Dry-run: return the exact plan without modifying anything.

        Requires an installation to have been scanned first; with no
        installation the plan is empty and explains why.
        """
        if self.installation is None:
            self.installation = detect_installation()
        env = self.build_environment()
        return build_plan(
            request_from_settings(settings), env, registry=self.registry_mgr
        )

    # ------------------------------------------------------------------
    # Run optimization
    # ------------------------------------------------------------------

    def run_optimization(
        self,
        settings: OptimizationSettings,
        *,
        restart_spotify: bool = False,
        profile: str = "",
        allow_registry_changes: bool = False,
        backup_retention: int = 0,
        history_retention_days: int = 90,
        measurement_seconds: float = 1.5,
    ) -> OptimizationResult:
        """
        Apply ``settings`` transactionally.

        Thread-safe: a lock prevents two optimisation runs at once.
        """
        with self._lock:
            return self._do_optimize(
                settings,
                restart_spotify=restart_spotify,
                profile=profile,
                allow_registry_changes=allow_registry_changes,
                backup_retention=backup_retention,
                history_retention_days=history_retention_days,
                measurement_seconds=measurement_seconds,
            )

    def _do_optimize(
        self,
        settings: OptimizationSettings,
        *,
        restart_spotify: bool,
        profile: str,
        allow_registry_changes: bool,
        backup_retention: int,
        history_retention_days: int,
        measurement_seconds: float,
    ) -> OptimizationResult:
        result = OptimizationResult()
        install = self.installation
        if install is None:
            result.add("No Spotify installation detected. Run Scan first.")
            return result

        total_steps = 8
        step = 0

        # --- 1. Environment + plan ------------------------------------
        step += 1
        self._progress("Checking compatibility…", step / total_steps)
        env = self.build_environment()
        result.add(
            f"Environment: {env.windows.label}, Spotify {install.install_type.value}"
            + (f" {install.version}" if install.version else "")
        )
        plan = build_plan(
            request_from_settings(settings), env, registry=self.registry_mgr
        )
        result.plan = plan
        result.add(f"Plan: {plan.summary()}")
        for skipped in plan.unsupported:
            result.add(f"Unsupported: {skipped.operation_id} — {skipped.reason}")
        for skipped in plan.skipped:
            result.add(f"Skipped: {skipped.operation_id} — {skipped.reason}")

        if plan.is_empty():
            result.operations_skipped += len(plan.skipped) + len(plan.unsupported)
            result.success = not plan.unsupported
            result.add("Nothing to do — the requested changes are already in place "
                       "or unsupported on this system.")
            return result

        # --- 2. Before measurement ------------------------------------
        step += 1
        self._progress("Measuring Spotify before changes…", step / total_steps)
        before = benchmark.measure(
            label="Before",
            duration=measurement_seconds,
            interval=0.5,
            cache_root=env.cache_root,
            spotify_version=install.version,
        )
        cache_before = _cache_size(env.cache_root)
        spotify_was_running = before.spotify_running

        # --- 3. Backup ------------------------------------------------
        step += 1
        self._progress("Creating and verifying backup…", step / total_steps)
        session = self.backup_mgr.create_session()
        result.backup_session = session
        meta = BackupMetadata(
            created_at=datetime.now().isoformat(timespec="seconds"),
            app_version=APP_VERSION,
            spotify_version=install.version or "",
            profile=profile,
            operations=sorted(plan.request.operations),
        )

        if install.prefs_path:
            meta.prefs_backed_up = self.backup_mgr.backup_prefs(
                session, Path(install.prefs_path)
            )
        meta.registry_backed_up = self.backup_mgr.backup_registry(
            session, self.registry_mgr.export_for_backup()
        )
        meta.shortcuts_backed_up = self.backup_mgr.backup_shortcuts(
            session, self.shortcut_mgr.backup_shortcuts()
        )
        if install.spicetify and install.spicetify.is_installed and install.spicetify.config_path:
            meta.spicetify_backed_up = self.backup_mgr.backup_spicetify(
                session, Path(install.spicetify.config_path)
            )

        self.backup_mgr.write_metadata(session, meta)
        if not self.backup_mgr.write_manifest(session):
            result.operations_failed += 1
            result.add("ERROR: Could not create a verifiable backup — no changes were made.")
            return result
        integrity = self.backup_mgr.verify_integrity(session)
        result.add(f"Backup {integrity.summary()}")
        if not integrity.ok:
            result.operations_failed += 1
            result.add("ERROR: Backup verification failed — no changes were made.")
            return result

        # --- 4. Stop Spotify if required ------------------------------
        step += 1
        stopped_by_us = False
        if plan.requires_spotify_closed:
            if is_spotify_running():
                self._progress("Closing Spotify…", step / total_steps)
                ok, message = stop_spotify()
                if not ok:
                    # Writing prefs under a running Spotify can be overwritten
                    # when it exits, so refuse rather than produce a change that
                    # may silently revert.
                    result.operations_failed += 1
                    result.add(
                        f"ERROR: Could not close Spotify ({message}). "
                        "No changes were made."
                    )
                    return result
                stopped_by_us = True
                spotify_was_running = True
                result.add("Spotify closed for the change.")
            env.spotify_running = False

        # --- 5. Execute ------------------------------------------------
        step += 1
        self._progress("Applying changes…", step / total_steps)
        optimizer = Optimizer(env, registry=self.registry_mgr)
        report = optimizer.apply(plan, allow_registry=allow_registry_changes)

        for outcome in report.outcomes:
            label = f"{outcome.change.operation_id}: {outcome.change.description}"
            if outcome.status == "applied":
                result.operations_completed += 1
                detail = f" — {outcome.detail}" if outcome.detail else ""
                verified = " (verified)" if outcome.verified else ""
                result.add(f"Done: {label}{detail}{verified}")
            elif outcome.status == "failed":
                result.operations_failed += 1
                result.add(f"ERROR: {label} — {outcome.detail or 'failed'}")
            else:
                result.operations_skipped += 1
                result.add(f"Skipped: {label} — {outcome.detail}")

        if report.rolled_back:
            result.rolled_back = True
            result.add("A critical change failed; applied settings were rolled back.")
            for detail in report.rollback_details:
                result.add(f"Rollback: {detail}")

        # --- 6. Restart (only when requested) --------------------------
        step += 1
        if restart_spotify and stopped_by_us and install.exe_path:
            self._progress("Restarting Spotify…", step / total_steps)
            ok, message = launch_spotify(Path(install.exe_path))
            result.add(f"Spotify restart: {'OK' if ok else 'failed'} — {message}")

        # --- 7. Verify / measure after --------------------------------
        step += 1
        self._progress("Verifying results…", step / total_steps)
        cache_after = _cache_size(env.cache_root)
        result.cache_freed_mb = round(max(0.0, cache_before - cache_after) / (1024 * 1024), 2)

        after = benchmark.measure(
            label="After",
            duration=measurement_seconds,
            interval=0.5,
            cache_root=env.cache_root,
            spotify_version=install.version,
        )
        if install.prefs_path:
            digest = PrefsManager(Path(install.prefs_path)).sha256()
            if digest:
                self.backup_mgr.update_post_write_hash(session, "prefs", digest)

        comparison_data = benchmark.compare(before, after)
        result.comparison = PerformanceComparison(
            before=PerformanceSnapshot.from_benchmark(before, "Before"),
            after=PerformanceSnapshot.from_benchmark(after, "After"),
            operations_completed=result.operations_completed,
            operations_skipped=result.operations_skipped,
            comparable=bool(comparison_data["comparable"]),
            notes=list(comparison_data["notes"]),
            cache_freed_mb=result.cache_freed_mb,
        )
        if not comparison_data["comparable"]:
            result.add(
                "Memory comparison not available: Spotify was not running for both "
                "measurements, so no RAM figure is claimed."
            )

        # --- 8. Record + retain ---------------------------------------
        step += 1
        self._progress("Recording results…", step / total_steps)
        result.success = result.operations_failed == 0

        if self.history is not None:
            self.history.record_session(
                started_at=before.started_at or datetime.now().isoformat(timespec="seconds"),
                finished_at=datetime.now().isoformat(timespec="seconds"),
                profile=profile,
                operations_completed=result.operations_completed,
                operations_skipped=result.operations_skipped,
                operations_failed=result.operations_failed,
                cache_freed_mb=result.cache_freed_mb,
                before_mb=result.comparison.before.total_memory_mb if result.comparison else None,
                after_mb=result.comparison.after.total_memory_mb if result.comparison else None,
                comparable=int(bool(result.comparison and result.comparison.comparable)),
                spotify_version=install.version,
                notes="; ".join(result.comparison.notes) if result.comparison else "",
            )
            self.history.prune(history_retention_days)

        if backup_retention > 0:
            self.backup_mgr.cleanup_old_sessions(keep=backup_retention)

        result.add(
            f"Optimization complete: {result.operations_completed} done, "
            f"{result.operations_skipped} skipped, "
            f"{result.operations_failed} failed"
            + (", settings rolled back." if result.rolled_back else ".")
        )
        return result

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_latest(
        self,
        *,
        allow_conflict: bool = False,
        allow_system_changes: bool = False,
    ) -> OptimizationResult:
        """Restore the most recent backup (all components)."""
        session = self.backup_mgr.get_latest_session()
        if session is None:
            result = OptimizationResult()
            result.add("No backups found. Nothing to restore.")
            return result
        return self.restore_session(
            session,
            allow_conflict=allow_conflict,
            allow_system_changes=allow_system_changes,
        )

    def restore_session(
        self,
        session: Path,
        *,
        components: Optional[Iterable[str]] = None,
        allow_conflict: bool = False,
        allow_system_changes: bool = False,
    ) -> OptimizationResult:
        """
        Restore selected artefacts from ``session``.

        ``components`` is a subset of ``("prefs", "registry", "shortcuts",
        "spicetify")``; ``None`` restores everything present.

        Registry and shortcut writes require ``allow_system_changes=True`` so a
        library or test caller cannot modify a machine's configuration by
        accident.
        """
        with self._lock:
            return self._do_restore(
                Path(session),
                set(components) if components else None,
                allow_conflict,
                allow_system_changes,
            )

    def _do_restore(
        self,
        session: Path,
        components: Optional[set[str]],
        allow_conflict: bool,
        allow_system_changes: bool,
    ) -> OptimizationResult:
        result = OptimizationResult()
        if self.installation is None:
            self.installation = detect_installation()
        if self.installation is None:
            result.add("No Spotify installation detected. Nothing to restore.")
            return result

        validation = self.backup_mgr.validate_session(session)
        wanted = components or {"prefs", "registry", "shortcuts", "spicetify"}
        result.add(f"Restoring backup from: {session.name}")

        integrity = self.backup_mgr.verify_integrity(session)
        if (session / "manifest.json").is_file() and not integrity.ok:
            result.add(f"WARNING: {integrity.summary()}")

        install = self.installation
        env = self.build_environment()

        needs_spotify_closed = (
            ("prefs" in wanted and validation["prefs"])
            or ("spicetify" in wanted and validation["spicetify"])
        )
        if needs_spotify_closed and is_spotify_running():
            ok, message = stop_spotify()
            if not ok:
                result.add(f"WARNING: Could not close Spotify — {message}")

        # Prefs (with conflict detection)
        if "prefs" in wanted and validation["prefs"] and install.prefs_path:
            prefs_path = Path(install.prefs_path)
            if self.backup_mgr.has_conflict(session, "prefs", prefs_path) and not allow_conflict:
                reason = "Spotify preferences changed after this backup was taken."
                result.conflicts.append(reason)
                result.conflicts_by_component["prefs"] = reason
                result.add(
                    "CONFLICT: Spotify's preferences changed since this snapshot. "
                    "Re-run the restore with 'overwrite' to replace them, or keep the "
                    "current values."
                )
            elif self.backup_mgr.restore_prefs(session, prefs_path, allow_conflict=allow_conflict):
                result.operations_completed += 1
                result.add("Preferences restored and verified.")
            else:
                result.operations_failed += 1
                result.add("ERROR: Could not restore preferences.")

        # Registry
        if "registry" in wanted and validation["registry"]:
            if not allow_system_changes:
                result.operations_skipped += 1
                result.add("Startup entries: restore disabled in this context.")
            else:
                reg_data = self.backup_mgr.restore_registry_data(session)
                if reg_data and self.registry_mgr.restore_from_backup(reg_data):
                    result.operations_completed += 1
                    result.add("Startup entries restored.")
                else:
                    result.operations_failed += 1
                    result.add("WARNING: Startup entry restore was incomplete.")

        # Shortcuts
        if "shortcuts" in wanted and validation["shortcuts"]:
            if not allow_system_changes:
                result.operations_skipped += 1
                result.add("Shortcuts: restore disabled in this context.")
            else:
                shortcut_data = self.backup_mgr.restore_shortcuts_data(session)
                if shortcut_data is not None:
                    if self.shortcut_mgr.restore_shortcuts(shortcut_data):
                        result.operations_completed += 1
                        result.add("Shortcuts restored.")
                    else:
                        result.operations_skipped += 1
                        result.add(
                            "Shortcuts: some could not be restored (they may no longer exist)."
                        )

        # Spicetify
        if "spicetify" in wanted and validation["spicetify"] and install.spicetify:
            config_path = install.spicetify.config_path
            if config_path:
                if self.backup_mgr.restore_spicetify(session, Path(config_path)):
                    result.operations_completed += 1
                    result.add("Spicetify config restored.")
                    SpicetifyManager(install.spicetify).run_apply()
                else:
                    result.operations_failed += 1
                    result.add("ERROR: Could not restore Spicetify config.")

        result.success = result.operations_failed == 0 and not result.conflicts
        result.add(
            f"Restore complete: {result.operations_completed} done, "
            f"{result.operations_failed} failed"
            + (f", {len(result.conflicts)} conflict(s)." if result.conflicts else ".")
        )
        if result.conflicts:
            result.add("Current Spotify settings were left untouched where conflicts were found.")
        return result

    # ------------------------------------------------------------------
    # Startup entries (read + transactional toggle)
    # ------------------------------------------------------------------

    def startup_entries(self) -> list:
        """Detailed, read-only startup entries for the Startup page."""
        return self.registry_mgr.get_startup_entry_details()

    def set_startup_entry(self, name: str, enabled: bool) -> OptimizationResult:
        """
        Enable or disable one Spotify startup entry, backup first.

        * Disabling removes the HKCU Run value (allow-listed names only).
        * Enabling re-writes the command recorded in the most recent backup,
          because the live value no longer exists once it was removed.

        Both paths create their own hash-verified snapshot so the change can be
        reversed from Backups & Restore, and both verify the registry state
        after writing.
        """
        with self._lock:
            result = OptimizationResult()
            entries = {entry.name: entry for entry in self.startup_entries()}
            entry = entries.get(name)

            command = ""
            if enabled:
                if entry is not None and entry.enabled and entry.command:
                    command = entry.command
                else:
                    command = self._recorded_startup_command(name)
                if not command:
                    result.add(
                        f"No recorded command for startup entry '{name}'. "
                        "Nothing was changed."
                    )
                    return result
            else:
                if entry is None:
                    result.add(f"Startup entry '{name}' is not present. Nothing was changed.")
                    return result
                if not entry.safe_to_modify:
                    result.add(
                        f"Startup entry '{name}' is outside the Spotify allow-list and "
                        "was left untouched."
                    )
                    return result

            session = self.backup_mgr.create_session()
            result.backup_session = session
            meta = BackupMetadata(
                created_at=datetime.now().isoformat(timespec="seconds"),
                app_version=APP_VERSION,
                profile="startup",
                operations=[f"startup.{'enable' if enabled else 'disable'}"],
            )
            meta.registry_backed_up = self.backup_mgr.backup_registry(
                session, self.registry_mgr.export_for_backup()
            )
            self.backup_mgr.write_metadata(session, meta)
            if not self.backup_mgr.write_manifest(session):
                result.operations_failed += 1
                result.add("ERROR: Could not create a verifiable backup — nothing was changed.")
                return result
            integrity = self.backup_mgr.verify_integrity(session)
            result.add(f"Backup {integrity.summary()}")
            if not integrity.ok:
                result.operations_failed += 1
                result.add("ERROR: Backup verification failed — nothing was changed.")
                return result

            if enabled:
                applied = self.registry_mgr.enable_startup_entry(name, command)
                present = name in self.registry_mgr.get_spotify_startup_entries()
                verified = applied and present
                detail = f"Enabled '{name}'."
            else:
                applied = self.registry_mgr.disable_startup_entry(
                    name, require_spotify_value=True
                )
                present = name in self.registry_mgr.get_spotify_startup_entries()
                verified = applied and not present
                detail = f"Disabled '{name}'."

            if verified:
                result.operations_completed += 1
                result.success = True
                result.add(detail + " Verified in the registry.")
            else:
                result.operations_failed += 1
                result.add(
                    f"ERROR: Could not {'enable' if enabled else 'disable'} '{name}'; "
                    "the registry value did not change as expected."
                )
            return result

    def _recorded_startup_command(self, name: str) -> str:
        """Most recent backed-up command for ``name``, newest backup first."""
        for session in self.backup_mgr.list_sessions():
            data = self.backup_mgr.restore_registry_data(session)
            if not data:
                continue
            value = (data.get("startup_entries") or {}).get(name)
            if value:
                return str(value)
        return ""

    # ------------------------------------------------------------------
    # Installation report
    # ------------------------------------------------------------------

    def installation_report(self) -> dict:
        """
        Everything the Installation page shows, in one read-only dictionary.

        Sizes come from the same containment-checked cache inventory the
        engine uses, so the page cannot report a total it would never touch.
        """
        install = self.installation or detect_installation()
        env = detect_environment(install, registry=self.registry_mgr)
        self.environment = env

        def path_text(value) -> str:
            return str(value) if value else ""

        prefs_path = Path(install.prefs_path) if install.prefs_path else None
        prefs_size = 0
        if prefs_path is not None and prefs_path.is_file():
            try:
                prefs_size = prefs_path.stat().st_size
            except OSError:
                prefs_size = 0

        cache_total = 0
        cache_disposable = 0
        cache_dirs = 0
        if env.cache_root is not None:
            manager = CacheManager(env.cache_root)
            if manager.exists():
                cache_total = manager.get_cache_size()
                inventory = manager.inventory()
                cache_dirs = len(inventory)
                cache_disposable = sum(
                    item.size_bytes for item in inventory if item.eligible
                )

        spicetify = install.spicetify
        spicetify_data = {
            "installed": bool(spicetify and spicetify.is_installed),
            "version": (spicetify.version if spicetify else None) or "",
            "config": path_text(spicetify.config_path) if spicetify else "",
            "extensions": list(spicetify.extensions) if spicetify else [],
            "custom_apps": list(spicetify.custom_apps) if spicetify else [],
        }

        return {
            "install_type": install.install_type.value,
            "version": install.version or "",
            "exe_path": path_text(install.exe_path),
            "data_path": path_text(install.data_path),
            "prefs_path": path_text(install.prefs_path),
            "cache_path": path_text(install.cache_path),
            "store_package": path_text(install.store_package_path),
            "prefs_bytes": prefs_size,
            "prefs_readable": env.prefs_readable,
            "prefs_writable": env.prefs_writable,
            "cache_bytes": cache_total,
            "cache_disposable_bytes": cache_disposable,
            "cache_dirs": cache_dirs,
            "spicetify": spicetify_data,
            "windows": env.windows.label,
            "windows_build": env.windows.build or 0,
            "windows_edition": env.windows.edition or "",
            "architecture": env.windows.architecture,
            "process_count": env.process_count,
            "startup_entries": len(env.startup_entries),
            "notes": list(env.notes),
        }

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def describe_conflicts(self, session: Path) -> dict[str, str]:
        """
        Per-component conflict reasons for ``session`` (empty when clean).

        Used by the restore interface so the user sees *which* component
        changed before choosing to overwrite anything.
        """
        install = self.installation or detect_installation()
        conflicts: dict[str, str] = {}
        if install.prefs_path and self.backup_mgr.has_conflict(
            Path(session), "prefs", Path(install.prefs_path)
        ):
            conflicts["prefs"] = (
                "Spotify's preferences changed after this snapshot was taken."
            )
        return conflicts

    def list_backups(self) -> list[dict]:
        """Rich summaries of available backups, newest first."""
        return [
            self.backup_mgr.session_summary(session)
            for session in self.backup_mgr.list_sessions()
        ]

    def delete_backup(self, name: str) -> bool:
        """Delete one backup session by folder name (containment-checked)."""
        session = self.backup_mgr.root / name
        return self.backup_mgr.delete_session(session)


def _cache_size(cache_root: Optional[Path]) -> int:
    if cache_root is None:
        return 0
    manager = CacheManager(cache_root)
    if not manager.exists():
        return 0
    return manager.get_cache_size()


__all__ = [
    "APP_VERSION", "OptimizationEngine", "OptimizationResult", "OptimizationSettings",
]
