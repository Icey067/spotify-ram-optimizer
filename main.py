"""
Spotify RAM Optimizer — Entry Point

Run the GUI::

    python main.py

Verify a build (GUI and packaged executable)::

    python main.py --smoke-test
    SpotifyOptimizer.exe --smoke-test
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

# Ensure UTF-8 output encoding across all Windows console code pages
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ensure_console_streams() -> None:
    """Ensure standard output and error are available for console logging."""
    if sys.stdout is not None and sys.stderr is not None:
        return

    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            if kernel32.AttachConsole(0xFFFFFFFF):
                try:
                    if sys.stdout is None:
                        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                    if sys.stderr is None:
                        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                    return
                except Exception:
                    pass
        except Exception:
            pass

    import io
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


def run_smoke_test() -> int:
    """
    Automated self-test of the packaged application.

    Exercises every subsystem, a dry-run plan, the diagnostics engine, the
    history store and backup integrity — then verifies a clean shutdown.
    Returns 0 on success.
    """
    _ensure_console_streams()
    from src.core.engine import APP_VERSION
    print("=" * 62)
    print(f"SPOTIFY RAM OPTIMIZER v{APP_VERSION} -- STANDALONE SMOKE TEST")
    print(f"Application version: {APP_VERSION}")
    print(f"Frozen executable: {getattr(sys, 'frozen', False)}")
    print(f"Executable path:   {sys.executable}")
    print(f"Python version:    {sys.version.split()[0]}")
    print("=" * 62)

    errors: list[str] = []
    steps: list[tuple[str, Callable[[], None]]] = []

    def step(label: str):
        def decorator(function: Callable[[], None]) -> Callable[[], None]:
            steps.append((label, function))
            return function
        return decorator

    # ------------------------------------------------------------------
    # Core subsystems
    # ------------------------------------------------------------------

    @step("Verifying logging subsystem")
    def _logger() -> None:
        from src.core.logger import get_log_file_path, get_logger
        log = get_logger("smoke_test")
        log.info("Smoke test logger initiated")
        print(f"   [OK] Logger initialized, writing to: {get_log_file_path()}")

    @step("Verifying Spotify detection")
    def _detection() -> None:
        from src.core.detector import detect_installation
        install = detect_installation()
        print(f"   [OK] Detection completed: type={install.install_type.value}, "
              f"version={install.version}")
        if install.spicetify:
            print(f"   [OK] Spicetify: installed={install.spicetify.is_installed}, "
                  f"version={install.spicetify.version}")

    @step("Verifying process manager")
    def _processes() -> None:
        from src.core.process_manager import (
            get_spotify_process_count, get_total_spotify_memory_mb, is_spotify_running,
        )
        print(f"   [OK] Process check: running={is_spotify_running()}, "
              f"count={get_spotify_process_count()}, "
              f"memory={get_total_spotify_memory_mb()} MB")

    @step("Verifying safe handling without a Spotify installation")
    def _no_installation() -> None:
        from src.core.engine import OptimizationEngine, OptimizationSettings
        with tempfile.TemporaryDirectory() as temp_backup:
            engine = OptimizationEngine(installation=None, backup_root=Path(temp_backup))
            result = engine.run_optimization(OptimizationSettings())
            assert not result.success
            assert any("No Spotify installation" in m for m in result.messages)

    @step("Verifying safe restore handling with no backups")
    def _no_backups() -> None:
        from src.core.engine import OptimizationEngine
        with tempfile.TemporaryDirectory() as temp_backup:
            engine = OptimizationEngine(installation=None, backup_root=Path(temp_backup))
            result = engine.restore_latest()
            assert not result.success
            assert any("No backups found" in m for m in result.messages)

    @step("Verifying performance snapshots")
    def _performance() -> None:
        from src.core.performance_monitor import PerformanceComparison, PerformanceSnapshot
        before = PerformanceSnapshot.capture("Before")
        after = PerformanceSnapshot.capture("After")
        comparison = PerformanceComparison(before=before, after=after,
                                           operations_completed=1, operations_skipped=0)
        report = comparison.report()
        assert "before_mb" in report and "after_mb" in report
        assert "comparable" in report
        print(f"   [OK] Snapshot: {report['before_mb']} MB -> {report['after_mb']} MB "
              f"(comparable={report['comparable']})")

    @step("Verifying optimization registry and dry-run planning")
    def _planning() -> None:
        from src.core.compatibility import detect_environment
        from src.core.optimizations import OPERATIONS, build_plan, request_from_settings
        from src.core.engine import OptimizationSettings
        from src.core.profiles import validate_profile

        assert len(OPERATIONS) >= 8
        assert len({op.id for op in OPERATIONS}) == len(OPERATIONS)

        profile = validate_profile({
            "name": "Smoke profile",
            "operations": ["cache.browser", "prefs.hardware_acceleration"],
            "cache_size_mb": 256,
        })
        assert profile.operations == ["prefs.hardware_acceleration", "cache.browser"]

        from src.core.detector import detect_installation
        env = detect_environment(detect_installation())
        plan = build_plan(request_from_settings(OptimizationSettings()), env)
        lines = plan.describe()
        assert isinstance(lines, list) and lines
        print(f"   [OK] Plan built: {plan.summary()} ({len(lines)} preview line(s))")

    @step("Verifying health-check engine")
    def _health() -> None:
        from src.core.diagnostics import run_health_check
        report = run_health_check(sample_seconds=0.6, include_measurement=False)
        assert report.status
        assert isinstance(report.findings, list) and report.findings
        text = report.to_markdown()
        assert "Health Report" in text
        print(f"   [OK] Health check: {report.status} "
              f"({len(report.findings)} finding(s))")

    @step("Verifying performance history store")
    def _history() -> None:
        from src.core.history import HistoryStore
        with tempfile.TemporaryDirectory() as temp:
            store = HistoryStore(Path(temp) / "history.db")
            assert store.available
            assert store.record_sample(total_mb=123.4, process_count=3,
                                       spotify_running=True)
            assert len(store.samples(hours=1)) == 1
            assert store.record_session(started_at="now", profile="safe",
                                        operations_completed=1) is not None
            assert store.stats()["sessions"] == 1
            assert store.clear_all()
            assert store.stats() == {"samples": 0, "sessions": 0}
        print("   [OK] History store records, reads and clears")

    @step("Verifying backup manifest integrity")
    def _backup_integrity() -> None:
        from src.core.backup_manager import BackupManager, BackupMetadata
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefs = root / "prefs"
            prefs.write_text("hardware_acceleration_mode_enabled=true\n")
            manager = BackupManager(root / "backups")
            session = manager.create_session()
            assert manager.backup_prefs(session, prefs)
            manager.write_metadata(session, BackupMetadata(created_at="smoke"))
            assert manager.write_manifest(session)
            integrity = manager.verify_integrity(session)
            assert integrity.ok, integrity.summary()
            (session / "prefs").write_text("tampered=true\n")
            assert manager.verify_integrity(session).ok is False
        print("   [OK] Backup hashes verify, and tampering is detected")

    # ------------------------------------------------------------------
    # GUI
    # ------------------------------------------------------------------

    @step("Verifying GUI App, theme, and persistent config")
    def _gui() -> None:
        from src.gui.app import App
        app = App()
        app.update()
        print("   [OK] App window created and responsive")

        destinations = [
            ("Dashboard", "dashboard"),
            ("Optimizations", "settings_panel"),
            ("Diagnostics", "diagnostics_panel"),
            ("Performance", "results_panel"),
            ("Processes", "processes_panel"),
            ("Backups", "backups_panel"),
            ("Startup", "startup_panel"),
            ("Installation", "installation_panel"),
            ("Activity", "log_panel"),
            ("Privacy", "privacy_panel"),
            ("Settings", "app_settings_panel"),
            ("About", "about_panel"),
        ]
        for nav_key, panel_attr in destinations:
            assert app.show_page(nav_key), f"Failed to navigate to {nav_key}"
            app.update()
            assert app.current_page == nav_key
            assert getattr(app, panel_attr).winfo_ismapped() == 1
            print(f"      - {nav_key} verified (panel visible, header updated)")

        app.show_page("Dashboard")
        app.update()
        assert app.dashboard.winfo_ismapped() == 1
        from src.gui.navigation import is_page_mapped
        assert is_page_mapped(app.settings_panel) is False
        assert is_page_mapped(app.log_panel) is False
        print("   [OK] Page isolation verified")

        from src.core.process_manager import get_process_details
        details = get_process_details()
        app.processes_panel.set_rows(details, 0.0)
        app.update()
        print(f"   [OK] Process tree rendered ({len(details)} process(es))")

        entries = app._ensure_engine().startup_entries()
        assert isinstance(entries, list)
        app.startup_panel.set_entries(entries)
        app.update()
        print(f"   [OK] Startup page rendered ({len(entries)} entry(ies))")

        diagnostics = app.diagnostics_panel
        app.show_page("Diagnostics")
        app.update()
        assert diagnostics.cards["checks"].value.cget("text") == "0"
        print("   [OK] Diagnostics page renders its empty state")

        privacy = app.privacy_panel
        app.show_page("Privacy")
        app.update()
        context = app._privacy_context()
        assert context["config"] and context["history"]
        privacy.set_context(context)
        app.update()
        print("   [OK] Privacy Center renders real paths and retention")

        report = app._ensure_engine().installation_report()
        assert report["install_type"] and "prefs_path" in report
        app.installation_panel.set_report(report)
        app.update()
        print(f"   [OK] Installation report rendered ({report['install_type']})")

        from src.gui.restore_dialog import RestoreDialog
        dialog = RestoreDialog(
            app,
            {
                "name": "smoke-snapshot",
                "created_at": "smoke",
                "artefacts": {"prefs": True, "registry": False,
                              "shortcuts": False, "spicetify": False},
                "integrity_ok": True,
                "has_manifest": True,
                "integrity_detail": "Integrity verified (1 artefact(s)).",
            },
            conflicts={"prefs": "smoke conflict"},
        )
        dialog.update()
        assert dialog.selected_components() == ["prefs"]
        dialog.destroy()
        print("   [OK] Selective restore dialog renders components and conflicts")

        dispatched: list[bool] = []
        worker = threading.Thread(
            target=lambda: app._safe_after(lambda: dispatched.append(True))
        )
        worker.start()
        worker.join()
        for _ in range(100):
            app.update()
            time.sleep(0.01)
            if dispatched:
                break
        assert dispatched, "worker-thread UI update never reached the Tk thread"
        print("   [OK] Thread-safe UI dispatch verified")

        settings = app.settings_panel.get_settings()
        assert isinstance(settings.disable_hw_accel, bool)
        assert app.settings_panel.profile in ("safe", "balanced", "advanced", "custom")
        print(f"   [OK] Optimization settings: profile={app.settings_panel.profile}, "
              f"hw_accel={settings.disable_hw_accel}")

        app.log_panel.append("00:00:00", "INFO", "Smoke test log entry")
        app.update()
        assert app.log_panel.winfo_ismapped() == 0
        print("   [OK] Log panel background update verified (no visual bleeding)")

        from src.core.performance_monitor import PerformanceComparison, PerformanceSnapshot
        comparison = PerformanceComparison(
            before=PerformanceSnapshot("now", 2, 500.0, label="Before"),
            after=PerformanceSnapshot("now", 0, 0.0, label="After"),
            comparable=False,
        )
        app.results_panel.show_comparison(comparison)
        print("   [OK] Results panel renders a non-comparable measurement honestly")

        app._do_scan()
        app._update_dashboard()
        print("   [OK] Dashboard updated with scan results")

        app.quit()
        app.destroy()
        print("   [OK] App destroyed cleanly without crashes")

    total = len(steps)
    for index, (label, function) in enumerate(steps, start=1):
        print(f"[{index}/{total}] {label}...")
        try:
            function()
        except Exception as exc:  # noqa: BLE001 - smoke test reports everything
            errors.append(f"{label}: {exc}")
            detail = str(exc) or repr(exc)
            print(f"   [FAIL] {type(exc).__name__}: {detail}")
            import traceback
            traceback.print_exc()

    print("=" * 62)
    if errors:
        print(f"SMOKE TEST FAILED with {len(errors)} error(s):")
        for error in errors:
            print(f"  - {error}")
        print("=" * 62)
        return 1

    print(f"SMOKE TEST PASSED: ALL {total} CHECKS VERIFIED SUCCESSFULLY")
    print("=" * 62)
    return 0


def main() -> None:
    if "--version" in sys.argv or "-v" in sys.argv:
        from src.core.engine import APP_VERSION
        print(f"Spotify RAM Optimizer v{APP_VERSION}")
        sys.exit(0)

    if "--smoke-test" in sys.argv:
        sys.exit(run_smoke_test())

    _ensure_console_streams()
    from src.gui.app import App
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
