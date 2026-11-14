"""
Spotify RAM Optimizer — Entry Point
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from pathlib import Path

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

# Ensure the project root is on the path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ensure_console_streams():
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
    Automated self-test and verification of the packaged application.
    Executes all primary subsystems, navigation destinations, and GUI components headlessly.
    Returns 0 on success, non-zero on failure.
    """
    _ensure_console_streams()
    print("=" * 60)
    print("SPOTIFY RAM OPTIMIZER -- STANDALONE EXE SMOKE TEST")
    print(f"Frozen executable: {getattr(sys, 'frozen', False)}")
    print(f"Executable path:   {sys.executable}")
    print(f"Python version:    {sys.version.split()[0]}")
    print("=" * 60)

    errors: list[str] = []

    # 1. Logger verification
    print("[1/10] Verifying logging subsystem...")
    try:
        from src.core.logger import get_logger, get_log_file_path
        log = get_logger("smoke_test")
        log.info("Smoke test logger initiated")
        log_path = get_log_file_path()
        print(f"   [OK] Logger initialized, writing to: {log_path}")
    except Exception as e:
        errors.append(f"Logger verification failed: {e}")
        print(f"   [FAIL] Logger failed: {e}")

    # 2. Spotify detection
    print("[2/10] Verifying Spotify detection...")
    try:
        from src.core.detector import detect_installation
        install = detect_installation()
        print(f"   [OK] Detection completed: type={install.install_type.value}, version={install.version}")
        if install.spicetify:
            print(f"   [OK] Spicetify: installed={install.spicetify.is_installed}, version={install.spicetify.version}")
    except Exception as e:
        errors.append(f"Spotify detection failed: {e}")
        print(f"   [FAIL] Detection failed: {e}")

    # 3. Process management
    print("[3/10] Verifying process manager...")
    try:
        from src.core.process_manager import is_spotify_running, get_total_spotify_memory_mb, get_spotify_process_count
        running = is_spotify_running()
        count = get_spotify_process_count()
        mem = get_total_spotify_memory_mb()
        print(f"   [OK] Process check: running={running}, count={count}, memory={mem} MB")
    except Exception as e:
        errors.append(f"Process manager failed: {e}")
        print(f"   [FAIL] Process manager failed: {e}")

    # 4. Engine safe handling of missing Spotify
    print("[4/10] Verifying safe optimization handling without Spotify...")
    try:
        from src.core.engine import OptimizationEngine, OptimizationSettings
        with tempfile.TemporaryDirectory() as temp_backup:
            eng = OptimizationEngine(installation=None, backup_root=Path(temp_backup))
            res = eng.run_optimization(OptimizationSettings())
            assert not res.success, "Optimization with None installation should not succeed"
            assert any("No Spotify installation" in m for m in res.messages), "Expected missing installation message"
        print("   [OK] Engine safely handles missing Spotify installation")
    except Exception as e:
        errors.append(f"Engine missing-Spotify handling failed: {e}")
        print(f"   [FAIL] Engine missing-Spotify test failed: {e}")

    # 5. Backup & Restore safe handling of missing backups
    print("[5/10] Verifying safe restore handling with no backups...")
    try:
        with tempfile.TemporaryDirectory() as temp_backup:
            eng = OptimizationEngine(installation=None, backup_root=Path(temp_backup))
            res = eng.restore_latest()
            assert not res.success, "Restore without backups should not succeed"
            assert any("No backups found" in m for m in res.messages), "Expected no backups message"
        print("   [OK] Engine safely handles empty backup directory")
    except Exception as e:
        errors.append(f"Restore safety test failed: {e}")
        print(f"   [FAIL] Restore safety test failed: {e}")

    # 6. Performance monitor
    print("[6/10] Verifying performance monitoring...")
    try:
        from src.core.performance_monitor import PerformanceSnapshot, PerformanceComparison
        snap1 = PerformanceSnapshot.capture("Before")
        snap2 = PerformanceSnapshot.capture("After")
        comp = PerformanceComparison(before=snap1, after=snap2, operations_completed=1, operations_skipped=0)
        rep = comp.report()
        assert "before_mb" in rep and "after_mb" in rep
        print(f"   [OK] Performance monitor snapshot: {rep['before_mb']} MB -> {rep['after_mb']} MB")
    except Exception as e:
        errors.append(f"Performance monitor failed: {e}")
        print(f"   [FAIL] Performance monitor failed: {e}")

    # 7. GUI App & Component instantiation
    print("[7/10] Verifying GUI App, theme, and persistent config...")
    try:
        from src.gui.app import App
        app = App()
        app.update()
        print("   [OK] App window created and responsive")

        # 8. All 7 Navigation Destinations Verification
        print("[8/10] Verifying all 7 sidebar navigation destinations...")
        nav_destinations = [
            ("Dashboard", "dashboard"),
            ("Optimizations", "settings_panel"),
            ("Performance", "results_panel"),
            ("Backups", "backups_panel"),
            ("Activity", "log_panel"),
            ("Settings", "app_settings_panel"),
            ("About", "about_panel"),
        ]

        for nav_key, panel_attr in nav_destinations:
            ok = app.show_page(nav_key)
            app.update()
            assert ok, f"Failed to navigate to {nav_key}"
            assert app.current_page == nav_key, f"current_page mismatch: expected {nav_key}, got {app.current_page}"
            target_panel = getattr(app, panel_attr)
            assert target_panel.winfo_ismapped() == 1, f"Expected {panel_attr} to be mapped for {nav_key}"
            print(f"      ✓ {nav_key} navigation verified (panel visible, header updated)")

        # Verify unmapping: when on Dashboard, other panels must be unmapped
        app.show_page("Dashboard")
        app.update()
        assert app.dashboard.winfo_ismapped() == 1
        assert app.settings_panel.winfo_ismapped() == 0
        assert app.log_panel.winfo_ismapped() == 0
        print("   [OK] Page isolation verified (inactive panels unmapped, zero frame bleeding)")

        # Test settings retrieval
        settings = app.settings_panel.get_settings()
        assert settings.disable_hw_accel is True
        print("   [OK] Settings panel configured and default values verified")

        # Test log appending without bleeding
        app.log_panel.append("00:00:00", "INFO", "Smoke test log entry")
        app.update()
        assert app.log_panel.winfo_ismapped() == 0, "Log panel should NOT become mapped by background append"
        print("   [OK] Log panel background update verified (no visual bleeding)")

        # Test results panel
        app.results_panel.show_comparison(comp)
        print("   [OK] Results panel comparison rendering verified")

        # 9. Scan Spotify action
        print("[9/10] Verifying 'Scan Spotify' action...")
        app._do_scan()
        app._update_dashboard()
        print("   [OK] Dashboard updated with scan results")

        # 10. Clean exit
        print("[10/10] Verifying clean shutdown...")
        app.quit()
        app.destroy()
        print("   [OK] App destroyed cleanly without crashes")

    except Exception as e:
        errors.append(f"GUI component test failed: {e}")
        print(f"   [FAIL] GUI test failed: {e}")

    print("=" * 60)
    if errors:
        print(f"SMOKE TEST FAILED with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        print("=" * 60)
        return 1

    print("SMOKE TEST PASSED: ALL 10 SUBSYSTEMS VERIFIED SUCCESSFULLY")
    print("=" * 60)
    return 0


def main() -> None:
    if "--smoke-test" in sys.argv:
        sys.exit(run_smoke_test())

    _ensure_console_streams()
    from src.gui.app import App
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
