"""
Main application window for the Spotify Optimizer workspace.

Threading model
---------------
All file, process and registry work happens on worker threads.  Anything that
touches Tk runs through :meth:`App._safe_after`, so no widget is ever
reconfigured from a background thread.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.core import benchmark
from src.core.app_paths import (
    backups_dir, config_file, history_db, logs_dir, resource_path,
)
from src.core.config_manager import AppConfig, load_config, save_config
from src.core.detector import SpotifyInstallation, detect_installation
from src.core.diagnostics import HealthReport, run_health_check
from src.core.engine import (
    OptimizationEngine,
    OptimizationResult,
    OptimizationSettings,
)
from src.core.history import HistoryStore
from src.core.logger import delete_session_logs, register_gui_callback, unregister_gui_callback
from src.core.optimizations import Plan
from src.core.performance_monitor import PerformanceSnapshot
from src.core.process_manager import get_process_details
from src.core.registry_manager import STARTUP_APPROVED_KEY_PATH, STARTUP_KEY_PATH

from .components import PlanPreviewDialog, SidebarButton, StatusPill
from .dashboard_panel import DashboardPanel
from .insight_pages import DiagnosticsPanel, PrivacyCenterPanel
from .navigation import NavigationController
from .restore_dialog import RestoreDialog
from .settings_panel import SettingsPanel
from .system_pages import InstallationPanel, ProcessesPanel, StartupPanel
from .theme import ACCENT, BG, ERROR, MUTED, SIDEBAR, SURFACE, SURFACE_RAISED, TEXT, WARNING
from .workspace_pages import (
    AboutPanel,
    ActivityLogPanel,
    AppSettingsPanel,
    BackupsPanel,
    PerformancePanel,
)


class App(ctk.CTk):
    """Authoritative responsive navigation shell for the Spotify Optimizer."""
    VERSION = "1.1.1"

    def __init__(self) -> None:
        super().__init__()

        self._config: AppConfig = load_config()
        ctk.set_appearance_mode(self._config.appearance_mode.lower())
        ctk.set_default_color_theme("blue")
        try:
            ctk.set_widget_scaling(float(self._config.ui_scale.rstrip("%")) / 100)
        except (ValueError, AttributeError):
            pass

        self.title("Spotify RAM Optimizer")
        self.geometry("1180x780")
        self.minsize(980, 660)
        self.configure(fg_color=BG)

        self._installation: Optional[SpotifyInstallation] = None
        self._engine: Optional[OptimizationEngine] = None
        self._running = False
        self._closed = False
        self._history_values: list[float] = []
        # A placeholder until the first scheduled sample fills this in; capturing
        # a snapshot here would walk the process table before the window paints.
        self._latest_snapshot = PerformanceSnapshot("", 0, 0.0)
        self._health_report: Optional[HealthReport] = None
        self._health_runs = 0
        self._health_running = False
        self._spicetify_signature: Optional[tuple] = None
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._factories: dict = {}
        self._page_callbacks: dict = {}
        self._sidebar_buttons: dict = {}
        # Tk is not thread-safe: worker threads hand callbacks to this queue and
        # the Tk thread drains it on a timer.
        self._ui_queue: "queue.Queue" = queue.Queue()

        self.history: Optional[HistoryStore] = (
            HistoryStore() if self._config.enable_performance_history else None
        )

        self._build_ui()
        register_gui_callback(self._on_log_entry)

        if self._config.auto_scan_on_startup:
            threading.Thread(target=self._auto_scan, daemon=True).start()

        self._apply_window_icon()
        self.after(30, self._drain_ui_callbacks)
        self._load_history_from_store()
        # Scheduled rather than called inline: the window is painted first and
        # the first psutil sample lands a moment later.
        self.after(120, self._poll_memory)

    # ==================================================================
    # Layout
    # ==================================================================

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- Sidebar ----
        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=SIDEBAR)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=20, pady=(18, 12), sticky="ew")
        ctk.CTkLabel(brand, text="SPOTIFY", text_color=ACCENT,
                     font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(brand, text="Optimizer", text_color=TEXT,
                     font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold")).pack(
                         anchor="w", pady=(0, 2))
        ctk.CTkLabel(brand, text=f"Desktop workspace  •  v{self.VERSION}", text_color=MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=10)).pack(anchor="w")

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, padx=10, sticky="ew")

        sidebar_buttons: dict[str, SidebarButton] = {}
        nav_groups = (
            ("OVERVIEW", (("Dashboard", "Dashboard"),)),
            ("MANAGEMENT", (
                ("Optimizations", "Optimizations"),
                ("Diagnostics", "Diagnostics"),
                ("Performance", "Performance"),
                ("Processes", "Processes"),
                ("Startup", "Startup"),
                ("Installation", "Installation"),
                ("Backups", "Backups & Restore"),
            )),
            ("APPLICATION", (
                ("Activity", "Activity Logs"),
                ("Privacy", "Privacy Center"),
                ("Settings", "Settings"),
                ("About", "About"),
            )),
        )
        for title, items in nav_groups:
            ctk.CTkLabel(nav, text=title, text_color=MUTED,
                         font=ctk.CTkFont(family="Segoe UI", size=9,
                                          weight="bold")).pack(
                                              anchor="w", padx=8, pady=(4, 1))
            for key, label in items:
                button = SidebarButton(
                    nav, label, lambda item=key: self.show_page(item), height=30
                )
                button.pack(fill="x")
                sidebar_buttons[key] = button

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=3, column=0, padx=16, pady=10, sticky="ew")
        self._sidebar_status = StatusPill(footer, "Checking Spotify")
        self._sidebar_status.pack(anchor="w")
        ctk.CTkLabel(footer, text="Protected, reversible changes", text_color=MUTED,
                     font=ctk.CTkFont(size=10)).pack(anchor="w", pady=(7, 0))

        # ---- Main content ----
        content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        topbar = ctk.CTkFrame(content, height=66, corner_radius=0, fg_color=SURFACE)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        topbar.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(topbar, fg_color="transparent")
        title_box.grid(row=0, column=0, padx=24, pady=12, sticky="w")
        self._page_title = ctk.CTkLabel(title_box, text="Dashboard", text_color=TEXT,
                                        font=ctk.CTkFont(family="Segoe UI", size=16,
                                                         weight="bold"))
        self._page_title.pack(anchor="w")
        self._page_description = ctk.CTkLabel(
            title_box, text="Overview of your Spotify setup", text_color=MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=10))
        self._page_description.pack(anchor="w")

        self._top_status = StatusPill(topbar, "Scanning")
        self._top_status.grid(row=0, column=1, padx=(0, 8), pady=14)

        ctk.CTkButton(topbar, text="Scan Spotify", command=self._on_scan_clicked,
                      width=96, height=30, fg_color=SURFACE_RAISED,
                      hover_color="#29313B").grid(row=0, column=2, padx=(0, 24), pady=14)

        self._page_host = ctk.CTkFrame(content, fg_color="transparent")
        self._page_host.grid(row=1, column=0, sticky="nsew")
        self._page_host.grid_columnconfigure(0, weight=1)
        self._page_host.grid_rowconfigure(0, weight=1)

        self.nav = NavigationController(self._page_host, self._page_title,
                                        self._page_description)

        progress = ctk.CTkFrame(content, height=38, fg_color=SURFACE, corner_radius=0)
        progress.grid(row=2, column=0, sticky="ew")
        progress.grid_columnconfigure(0, weight=1)
        self._progress_bar = ctk.CTkProgressBar(progress, height=6, progress_color=ACCENT,
                                                fg_color="#27303B")
        self._progress_bar.grid(row=0, column=0, padx=(20, 10), pady=14, sticky="ew")
        self._progress_bar.set(0)
        self._progress_label = ctk.CTkLabel(progress, text="Ready", text_color=MUTED,
                                            font=ctk.CTkFont(size=10))
        self._progress_label.grid(row=0, column=1, padx=(0, 20))

        self._make_pages(sidebar_buttons)

    def _make_pages(self, buttons: dict[str, SidebarButton]) -> None:
        """
        Register page factories instead of constructing every page up front.

        Only the page the user opens is built, which removes the largest block
        of start-up work (ten CustomTkinter page trees, including nine operation
        cards and two canvases) without changing any behaviour.  ``show_page``
        and the ``*_panel`` properties build on first use.
        """
        self._sidebar_buttons = buttons
        self._factories = {
            "Dashboard": self._build_dashboard,
            "Optimizations": self._build_optimizations,
            "Diagnostics": self._build_diagnostics,
            "Performance": self._build_performance,
            "Processes": self._build_processes,
            "Backups": self._build_backups,
            "Startup": self._build_startup,
            "Installation": self._build_installation,
            "Activity": self._build_activity,
            "Privacy": self._build_privacy,
            "Settings": self._build_settings,
            "About": self._build_about,
        }
        self._page_callbacks = {
            "Optimizations": self._refresh_compatibility,
            "Diagnostics": self._on_diagnostics_shown,
            "Performance": self._refresh_performance,
            "Processes": self._refresh_processes,
            "Backups": self._on_backups_shown,
            "Startup": self._refresh_startup,
            "Installation": self._refresh_installation,
            "Activity": self._on_activity_shown,
            "Privacy": self._on_privacy_shown,
        }
        self.show_page("Dashboard")

    # ---- page factories -------------------------------------------------

    def _build_dashboard(self) -> DashboardPanel:
        return DashboardPanel(
            self._page_host,
            self._on_scan_clicked,
            self._on_run_clicked,
            self._on_restore_clicked,
            on_health=self._on_health_check,
            on_preview=self._on_preview_clicked,
            on_export_health=self._on_export_health,
        )

    def _build_optimizations(self) -> SettingsPanel:
        panel = SettingsPanel(
            self._page_host,
            on_run=self._on_run_clicked,
            on_preview=self._on_preview_clicked,
            on_profile_change=self._on_profile_changed,
            on_export_profile=self._on_export_profile,
            on_import_profile=self._on_import_profile,
        )
        try:
            if self._config.profile == "custom":
                panel.select_operations(self._config_operations())
            else:
                panel.apply_profile(self._config.profile, notify=False)
            panel.set_cache_size(self._config.cache_size_mb)
        except ValueError:
            pass
        install = self._installation
        if install is not None and install.spicetify and install.spicetify.is_installed:
            self._spicetify_signature = (
                tuple(install.spicetify.extensions),
                tuple(install.spicetify.custom_apps),
            )
            panel.update_spicetify(
                install.spicetify.extensions, install.spicetify.custom_apps
            )
        panel.update_compatibility(
            self._engine.environment if self._engine is not None else None
        )
        return panel

    def _build_diagnostics(self) -> DiagnosticsPanel:
        return DiagnosticsPanel(
            self._page_host,
            self._health_report_pair,
            on_run_health=self._on_health_check,
            on_export=self._on_export_health,
        )

    def _build_privacy(self) -> PrivacyCenterPanel:
        return PrivacyCenterPanel(
            self._page_host,
            self._privacy_context,
            on_clear_logs=self._on_clear_logs,
            on_clear_history=self._on_clear_history,
            on_manage_backups=self._on_manage_backups,
            on_export_report=self._on_export_health,
        )

    def _build_performance(self) -> PerformancePanel:
        return PerformancePanel(
            self._page_host, self._refresh_performance, on_benchmark=self._on_benchmark
        )

    def _build_processes(self) -> ProcessesPanel:
        return ProcessesPanel(self._page_host, self._refresh_processes)

    def _build_backups(self) -> BackupsPanel:
        return BackupsPanel(
            self._page_host,
            self._get_backups,
            self._on_restore_clicked,
            on_restore_session=self._on_restore_session,
            on_delete=self._on_delete_backup,
        )

    def _build_startup(self) -> StartupPanel:
        return StartupPanel(
            self._page_host, self._refresh_startup, on_toggle=self._on_startup_toggle
        )

    def _build_installation(self) -> InstallationPanel:
        return InstallationPanel(
            self._page_host, self._refresh_installation, on_scan=self._on_scan_clicked
        )

    def _build_activity(self) -> ActivityLogPanel:
        return ActivityLogPanel(self._page_host)

    def _build_settings(self) -> AppSettingsPanel:
        return AppSettingsPanel(
            self._page_host,
            self._change_theme,
            self._change_scale,
            on_clear_history=self._on_clear_history,
            on_clear_logs=self._on_clear_logs,
            on_open_folder=self._on_open_folder,
        )

    def _build_about(self) -> AboutPanel:
        return AboutPanel(self._page_host, version=self.VERSION)

    # ---- page access ----------------------------------------------------

    def _ensure_page(self, name: str):
        """Return the page, building and registering it on first use."""
        page = self._pages.get(name)
        if page is not None:
            return page
        factory = self._factories.get(name)
        if factory is None:
            return None
        page = factory()
        self._pages[name] = page
        self.nav.register_page(
            name,
            page,
            self._sidebar_buttons.get(name),
            on_show=self._page_callbacks.get(name),
        )
        if self.nav.current_page == name:
            self.nav.show_page(name)
        return page

    def show_page(self, name: str) -> bool:
        """Central navigation entry point. Builds a page the first time it is shown."""
        if name not in self._factories:
            return False
        if self._ensure_page(name) is None:
            return False
        return self.nav.show_page(name)

    @property
    def dashboard(self) -> DashboardPanel:
        return self._ensure_page("Dashboard")

    @property
    def settings_panel(self) -> SettingsPanel:
        return self._ensure_page("Optimizations")

    @property
    def results_panel(self) -> PerformancePanel:
        return self._ensure_page("Performance")

    @property
    def diagnostics_panel(self) -> DiagnosticsPanel:
        return self._ensure_page("Diagnostics")

    @property
    def privacy_panel(self) -> PrivacyCenterPanel:
        return self._ensure_page("Privacy")

    @property
    def processes_panel(self) -> ProcessesPanel:
        return self._ensure_page("Processes")

    @property
    def backups_panel(self) -> BackupsPanel:
        return self._ensure_page("Backups")

    @property
    def startup_panel(self) -> StartupPanel:
        return self._ensure_page("Startup")

    @property
    def installation_panel(self) -> InstallationPanel:
        return self._ensure_page("Installation")

    @property
    def log_panel(self) -> ActivityLogPanel:
        return self._ensure_page("Activity")

    @property
    def app_settings_panel(self) -> AppSettingsPanel:
        return self._ensure_page("Settings")

    @property
    def about_panel(self) -> AboutPanel:
        return self._ensure_page("About")

    @property
    def current_page(self) -> str:
        """Authoritative current page query."""
        return self.nav.current_page

    # ==================================================================
    # Engine
    # ==================================================================

    def _ensure_engine(self) -> OptimizationEngine:
        if self._engine is None:
            self._engine = OptimizationEngine(
                installation=self._installation, history=self.history
            )
            self._engine.set_progress_callback(self._on_engine_progress)
        return self._engine

    def _on_scan_clicked(self) -> None:
        if self._running:
            return
        self._set_status("Scanning Spotify", WARNING)
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _auto_scan(self) -> None:
        time.sleep(0.2)
        if not self._closed:
            self._do_scan()

    def _do_scan(self) -> None:
        try:
            self._set_progress("Scanning Spotify installation…", 0.2)
            install = detect_installation()
            self._installation = install
            self._engine = OptimizationEngine(installation=install, history=self.history)
            self._engine.set_progress_callback(self._on_engine_progress)
            try:
                self._engine.build_environment()
            except Exception:
                pass
            self._safe_after(self._update_dashboard)
            if self._pages.get("Startup") is not None:
                self._refresh_startup()
            if self._pages.get("Installation") is not None:
                self._refresh_installation()
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(
                f"Scan failed: {exc}", "error"))
        finally:
            self._set_progress("", 0)

    def _update_dashboard(self) -> None:
        install = self._installation
        if install is None:
            return
        startup = "None found"
        if self._engine is not None and self._engine.environment is not None:
            entries = self._engine.environment.startup_entries
            startup = ", ".join(sorted(entries)) if entries else "None found"
        info = {
            "Install Type": install.install_type.value,
            "Spicetify": "Detected" if install.spicetify and install.spicetify.is_installed
                         else "Not installed",
            "Version": install.version or "Unknown",
            "Prefs File": "Found" if install.prefs_path else "Missing",
            "Cache": "Found" if install.cache_path else "Missing",
            "Process": "Running" if self._latest_snapshot.process_count else "Stopped",
            "Startup": startup,
        }
        self.dashboard.update_info(info)
        panel = self._pages.get("Optimizations")
        if panel is not None and install.spicetify and install.spicetify.is_installed:
            signature = (tuple(install.spicetify.extensions),
                         tuple(install.spicetify.custom_apps))
            # Only rebuild the Spicetify checkboxes when the discovery changes;
            # rebuilding on every poll would discard the user's selection.
            if signature != self._spicetify_signature:
                self._spicetify_signature = signature
                panel.update_spicetify(
                    install.spicetify.extensions, install.spicetify.custom_apps
                )
        self._refresh_compatibility()

        color = ACCENT if install.install_type.value != "Not Found" else ERROR
        label = ("Spotify detected" if install.install_type.value != "Not Found"
                 else "Spotify not found")
        self._set_status(label, color)

    def _refresh_compatibility(self) -> None:
        panel = self._pages.get("Optimizations")
        if panel is None:
            return
        env = self._engine.environment if self._engine is not None else None
        panel.update_compatibility(env)

    # ==================================================================
    # Preview / run
    # ==================================================================

    def _on_preview_clicked(self) -> None:
        if self._running:
            return
        settings = self.settings_panel.get_settings()
        self._persist_optimization_choices(settings)
        self._set_progress("Preparing preview…", 0.2)
        threading.Thread(target=self._do_preview, args=(settings,), daemon=True).start()

    def _do_preview(self, settings: OptimizationSettings) -> None:
        try:
            plan = self._ensure_engine().preview(settings)
            self._safe_after(lambda: self._show_preview(plan))
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(
                f"Could not build a preview: {exc}", "error"))
        finally:
            self._set_progress("", 0)

    def _show_preview(self, plan: Plan) -> None:
        if self._closed:
            return
        PlanPreviewDialog(self, plan, on_apply=self._start_optimization)

    def _on_run_clicked(self) -> None:
        if self._running:
            return
        if self._installation is None or self._installation.install_type.value == "Not Found":
            self.dashboard.show_message(
                "Scan a valid Spotify installation before optimizing.", "error")
            return
        if self._config.confirm_before_apply and not messagebox.askyesno(
            "Optimize Spotify",
            "A timestamped, hash-verified backup is created before any change.\n\n"
            "You can restore it from Backups & Restore at any time.\n\nContinue?",
        ):
            return
        self._start_optimization()

    def _start_optimization(self) -> None:
        if self._running:
            return
        if self._installation is None or self._installation.install_type.value == "Not Found":
            self.dashboard.show_message(
                "Scan a valid Spotify installation before optimizing.", "error")
            return
        settings = self.settings_panel.get_settings()
        self._persist_optimization_choices(settings)
        self._running = True
        self._set_controls_enabled(False)
        threading.Thread(target=self._do_run, args=(settings,), daemon=True).start()

    def _do_run(self, settings: OptimizationSettings) -> None:
        try:
            self._set_progress("Starting optimization…", 0.05)
            engine = self._ensure_engine()
            result = engine.run_optimization(
                settings,
                restart_spotify=self._config.restart_spotify_after_optimization,
                profile=self.settings_panel.profile,
                allow_registry_changes=True,
                backup_retention=self._config.backup_retention,
                history_retention_days=self._config.history_retention_days,
            )
            self._safe_after(lambda: self._on_run_complete(result))
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(
                f"Optimization error: {exc}", "error"))
        finally:
            self._running = False
            self._safe_after(lambda: self._set_controls_enabled(True))
            self._set_progress("", 0)

    def _on_run_complete(self, result: OptimizationResult) -> None:
        self.dashboard.show_message(
            "Optimization complete" if result.success
            else "Optimization completed with warnings",
            "success" if result.success else "error",
        )
        if result.comparison:
            self.results_panel.show_comparison(result.comparison)
        self.backups_panel.refresh()
        self._load_history_from_store()
        self.show_page("Performance")
        self._refresh_performance()

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.dashboard.set_buttons_enabled(enabled)
        panel = self._pages.get("Optimizations")
        if panel is not None:
            panel.set_buttons_enabled(enabled)

    # ==================================================================
    # Restore
    # ==================================================================

    def _on_restore_clicked(self) -> None:
        """Open the restore interface for the most recent snapshot."""
        if self._running:
            return
        backups = self._get_backups()
        if not backups:
            messagebox.showinfo(
                "No snapshots yet",
                "There is nothing to restore: a hash-verified snapshot is written "
                "before any change is applied.",
            )
            return
        self._open_restore_dialog(backups[0])

    def _on_restore_session(self, name: str) -> None:
        if self._running or not name:
            return
        summary = next(
            (item for item in self._get_backups() if item.get("name") == name), None
        )
        if summary is None:
            messagebox.showerror(
                "Snapshot missing", f"Snapshot '{name}' is no longer on disk."
            )
            self.backups_panel.refresh()
            return
        self._open_restore_dialog(summary)

    def _open_restore_dialog(self, summary: dict) -> None:
        """Ask which components to restore and how to treat conflicts."""
        root = self._ensure_engine().backup_mgr.root
        session = Path(summary.get("path") or root / str(summary.get("name", "")))
        try:
            conflicts = self._ensure_engine().describe_conflicts(session)
        except Exception:
            conflicts = {}
        RestoreDialog(
            self,
            summary,
            on_restore=lambda components, overwrite: self._begin_restore(
                summary.get("name"), components, overwrite
            ),
            conflicts=conflicts,
        )

    def _begin_restore(self, name: Optional[str], components: list[str],
                       allow_conflict: bool) -> None:
        if self._running:
            return
        self._running = True
        self._set_controls_enabled(False)
        threading.Thread(
            target=self._do_restore,
            args=(name, tuple(components), allow_conflict),
            daemon=True,
        ).start()

    def _do_restore(self, name: Optional[str], components: tuple[str, ...],
                    allow_conflict: bool) -> None:
        try:
            self._set_progress("Restoring protected backup…", 0.25)
            engine = self._ensure_engine()
            if name:
                result = engine.restore_session(
                    engine.backup_mgr.root / name,
                    components=list(components) or None,
                    allow_conflict=allow_conflict,
                    allow_system_changes=True,
                )
            else:
                result = engine.restore_latest(
                    allow_conflict=allow_conflict, allow_system_changes=True
                )
            self._safe_after(lambda: self._on_restore_complete(result))
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(
                f"Restore error: {exc}", "error"))
        finally:
            self._running = False
            self._safe_after(lambda: self._set_controls_enabled(True))
            self._set_progress("", 0)

    def _on_restore_complete(self, result: OptimizationResult) -> None:
        if result.conflicts:
            self.dashboard.show_message("Restore paused on a conflict", "error")
            messagebox.showwarning(
                "Not everything was restored",
                "\n".join(result.conflicts)
                + "\n\nThose components were left at their current values. Run the "
                  "restore again and enable the overwrite option to replace them.",
            )
        else:
            self.dashboard.show_message(
                "Restore complete" if result.success
                else "Restore completed with warnings",
                "success" if result.success else "error",
            )
        self.backups_panel.refresh()
        self._refresh_performance()

    def _on_delete_backup(self, name: str) -> None:
        if not name:
            return
        if not messagebox.askyesno(
            "Delete snapshot",
            f"Permanently delete snapshot '{name}'?\n\nThis cannot be undone.",
        ):
            return
        engine = self._ensure_engine()
        if engine.delete_backup(name):
            self.backups_panel.refresh()
        else:
            messagebox.showerror("Delete failed", "The snapshot could not be deleted.")

    # ==================================================================
    # Health check / benchmark
    # ==================================================================

    def _on_health_check(self) -> None:
        if self._running or self._health_running:
            return
        self._health_running = True
        panel = self._pages.get("Diagnostics")
        if panel is not None:
            panel.set_running(True)
        self._set_progress("Running health check…", 0.2)
        threading.Thread(target=self._do_health, daemon=True).start()

    def _do_health(self) -> None:
        try:
            env = self._engine.environment if self._engine is not None else None
            report = run_health_check(
                installation=self._installation,
                env=env,
                backup_root=(self._engine.backup_mgr.root
                             if self._engine is not None else None),
                sample_seconds=1.5,
            )
            self._safe_after(lambda: self._apply_health(report))
        except Exception as exc:
            self._safe_after(lambda: self._on_health_failed(str(exc)))
        finally:
            self._set_progress("", 0)
            self._safe_after(self._finish_health)

    def _finish_health(self) -> None:
        self._health_running = False
        panel = self._pages.get("Diagnostics")
        if panel is not None:
            panel.set_running(False)

    def _apply_health(self, report: HealthReport) -> None:
        self._health_report = report
        self._health_runs += 1
        self.dashboard.set_health(report)
        panel = self._pages.get("Diagnostics")
        if panel is not None:
            panel.set_running(False)
            panel.set_report(report, self._health_runs)

    def _on_health_failed(self, message: str) -> None:
        self.dashboard.show_message(f"Health check failed: {message}", "error")
        panel = self._pages.get("Diagnostics")
        if panel is not None:
            panel.set_running(False)
            panel.set_report(self._health_report, self._health_runs)

    def _health_report_pair(self) -> tuple:
        """Current report plus how many checks have run in this session."""
        return self._health_report, self._health_runs

    def _on_diagnostics_shown(self) -> None:
        panel = self._pages.get("Diagnostics")
        if panel is not None:
            panel.refresh()

    def _on_privacy_shown(self) -> None:
        panel = self._pages.get("Privacy")
        if panel is not None:
            panel.refresh()

    def _on_manage_backups(self) -> None:
        self.show_page("Backups")

    def _privacy_context(self) -> dict:
        """Assemble the real paths and retention values the Privacy Center shows."""
        install = self._installation
        read_files = [str(config_file()), str(logs_dir())]
        write_files = [str(config_file()), str(backups_dir()), str(logs_dir())]
        if self.history is not None:
            read_files.append(str(history_db()))
            write_files.append(str(history_db()))
        if install is not None:
            if install.prefs_path:
                read_files.insert(0, str(install.prefs_path))
                write_files.insert(
                    0, f"{install.prefs_path} (only when you apply an operation)"
                )
            if install.cache_path:
                read_files.append(str(install.cache_path))
            if install.spicetify and install.spicetify.config_path:
                read_files.append(str(install.spicetify.config_path))
                write_files.append(str(install.spicetify.config_path))

        statistics = (
            dict(self.history.stats())
            if self.history is not None else {"samples": 0, "sessions": 0}
        )
        try:
            log_files = len(list(logs_dir().glob("optimizer_*.log")))
        except OSError:
            log_files = 0
        statistics["backups"] = len(self._get_backups())
        statistics["log_files"] = log_files

        return {
            "config": str(config_file()),
            "backups": str(backups_dir()),
            "logs": str(logs_dir()),
            "history": str(history_db()),
            "read_files": read_files,
            "write_files": write_files,
            "registry_locations": [
                f"HKCU\\{STARTUP_KEY_PATH} — read on every scan; written only when "
                "you enable or disable a startup entry",
                f"HKCU\\{STARTUP_APPROVED_KEY_PATH} — read only, never written",
            ],
            "retention": {
                "history_days": self._config.history_retention_days,
                "backup_keep": self._config.backup_retention,
                "log_days": self._config.log_retention_days,
            },
            "statistics": statistics,
        }

    def _on_export_health(self) -> None:
        if self._health_report is None:
            messagebox.showinfo(
                "No report yet",
                "Run a health check first — the report is generated from live data.",
            )
            return
        target = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt")],
            initialfile="spotify-health-report.md",
        )
        if not target:
            return
        try:
            Path(target).write_text(
                self._health_report.to_markdown(redact=True), encoding="utf-8"
            )
            messagebox.showinfo(
                "Report exported",
                f"Diagnostic report saved to:\n{target}\n\n"
                "Your user profile path has been redacted.",
            )
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def _on_benchmark(self) -> None:
        if self._running:
            return
        self.results_panel.set_benchmark_text("Sampling Spotify for 3 seconds…")
        threading.Thread(target=self._do_benchmark, daemon=True).start()

    def _do_benchmark(self) -> None:
        try:
            install = self._installation
            result = benchmark.measure(
                label="Benchmark",
                duration=3.0,
                interval=0.5,
                cache_root=install.cache_path if install else None,
                spotify_version=install.version if install else None,
            )
            self._safe_after(lambda: self._apply_benchmark(result))
        except Exception as exc:
            self._safe_after(lambda: self.results_panel.set_benchmark_text(
                f"Benchmark failed: {exc}"))
        finally:
            self._set_progress("", 0)

    def _apply_benchmark(self, result) -> None:
        self.results_panel.set_benchmark_text(result.summary())
        snapshot = PerformanceSnapshot.from_benchmark(result, "Benchmark")
        self.results_panel.update_snapshot(snapshot, self._history_values)
        if self.history is not None and result.spotify_running:
            self.history.record_sample(
                total_mb=result.working_set_mb or 0.0,
                private_mb=result.private_mb,
                cpu_percent=result.cpu_mean,
                process_count=result.process_count,
                spotify_running=True,
            )
            self._load_history_from_store()

    # ==================================================================
    # Settings actions
    # ==================================================================

    def _config_operations(self) -> list[str]:
        """Rebuild the saved custom selection from persisted flags."""
        config = self._config
        operations: list[str] = []
        if config.disable_hw_accel:
            operations.append("prefs.hardware_acceleration")
        if config.set_cache_size:
            operations.append("prefs.cache_size")
        if config.disable_autostart:
            operations.append("startup.run_entry")
        if config.clean_browser_cache:
            operations.append("cache.browser")
        if config.clean_code_cache:
            operations.append("cache.code")
        if config.clean_gpu_cache:
            operations.append("cache.gpu")
        return operations

    def _on_profile_changed(self, profile: str) -> None:
        self._config.profile = profile
        save_config(self._config)

    def _on_export_profile(self) -> None:
        from src.core.profiles import Profile, ProfileError, export_profile

        selected = self.settings_panel.selected_operations()
        default_name = f"spotify-{self.settings_panel.profile}.json"
        target = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Profile", "*.json")],
            initialfile=default_name,
        )
        if not target:
            return
        name = Path(target).stem.strip()[:64] or "profile"
        try:
            export_profile(
                Profile(
                    name=name,
                    operations=selected,
                    cache_size_mb=self.settings_panel.get_cache_size_mb(),
                ),
                Path(target),
            )
            messagebox.showinfo(
                "Profile exported",
                f"Saved {len(selected)} operation(s) to:\n{target}",
            )
        except ProfileError as exc:
            messagebox.showerror("Export failed", str(exc))

    def _on_import_profile(self) -> None:
        from src.core.profiles import ProfileError, import_profile

        source = filedialog.askopenfilename(
            filetypes=[("Profile", "*.json")],
        )
        if not source:
            return
        try:
            profile = import_profile(Path(source))
        except ProfileError as exc:
            messagebox.showerror(
                "Invalid profile",
                f"This file cannot be imported:\n\n{exc}",
            )
            return
        self.settings_panel.select_operations(profile.operations)
        self.settings_panel.set_cache_size(profile.cache_size_mb)
        self._config.profile = "custom"
        save_config(self._config)
        messagebox.showinfo(
            "Profile imported",
            f"'{profile.name}' selected {len(profile.operations)} operation(s).\n"
            "Review them, then use Preview before applying.",
        )

    def _persist_optimization_choices(self, settings: OptimizationSettings) -> None:
        self._config.disable_hw_accel = settings.disable_hw_accel
        self._config.set_cache_size = settings.set_cache_size
        self._config.cache_size_mb = settings.cache_size_mb
        self._config.disable_autostart = settings.disable_autostart
        self._config.clean_browser_cache = settings.clean_browser_cache
        self._config.clean_code_cache = settings.clean_code_cache
        self._config.clean_gpu_cache = settings.clean_gpu_cache
        self._config.profile = self.settings_panel.profile
        save_config(self._config)

    def _on_clear_history(self) -> None:
        if not messagebox.askyesno(
            "Clear performance history",
            "Delete all recorded performance samples and optimisation sessions?",
        ):
            return
        if self.history is not None:
            self.history.clear_all()
        self._history_values.clear()
        self._refresh_performance()
        self._on_privacy_shown()

    def _on_clear_logs(self) -> None:
        if not messagebox.askyesno(
            "Clear logs", "Delete all log files for this application?"
        ):
            return
        removed = delete_session_logs()
        self.log_panel.reload()
        self._on_privacy_shown()
        messagebox.showinfo("Logs cleared", f"{removed} log file(s) removed.")

    @staticmethod
    def _on_open_folder(which: str) -> None:
        target = backups_dir() if which == "backups" else logs_dir()
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target))

    # NOTE: these must not be named ``_set_scaling`` or ``_apply_appearance_mode``.
    # Both are CustomTkinter hooks that every window calls internally; overriding
    # them breaks window creation with a confusing TypeError/AttributeError.
    @staticmethod
    def _change_theme(choice: str) -> None:
        ctk.set_appearance_mode(choice.lower())

    @staticmethod
    def _change_scale(choice: str) -> None:
        try:
            ctk.set_widget_scaling(float(choice.rstrip("%")) / 100)
        except (ValueError, AttributeError):
            pass

    # ==================================================================
    # Live measurement
    # ==================================================================

    def _refresh_performance(self) -> None:
        if self._closed:
            return
        self._latest_snapshot = PerformanceSnapshot.capture("Current")
        if self._latest_snapshot.process_count:
            self._history_values.append(self._latest_snapshot.total_memory_mb)
            self._history_values = self._history_values[-60:]
        self.dashboard.update_snapshot(
            self._latest_snapshot.total_memory_mb,
            self._latest_snapshot.process_count,
            self._history_values,
            self._latest_snapshot.cpu_percent,
        )
        panel = self._pages.get("Performance")
        if panel is not None:
            panel.update_snapshot(self._latest_snapshot, self._history_values)

        if self.history is not None:
            self.history.record_sample(
                total_mb=self._latest_snapshot.total_memory_mb,
                cpu_percent=self._latest_snapshot.cpu_percent,
                process_count=self._latest_snapshot.process_count,
                spotify_running=bool(self._latest_snapshot.process_count),
                min_interval=30.0,
            )
        if self._installation:
            self._update_dashboard()

    def _load_history_from_store(self) -> None:
        if self.history is None:
            return
        samples = self.history.samples(hours=24, limit=200)
        values = [s["total_mb"] for s in samples if s.get("total_mb")]
        if values:
            self._history_values = values[-60:]

    def _poll_memory(self) -> None:
        try:
            self._refresh_performance()
        except Exception:
            pass
        finally:
            if not self._closed:
                interval_ms = max(2, self._config.monitoring_interval_seconds) * 1000
                self.after(interval_ms, self._poll_memory)

    # ==================================================================
    # System pages (processes, startup, installation)
    # ==================================================================

    def _refresh_processes(self) -> None:
        panel = self._pages.get("Processes")
        if panel is None or self._closed:
            return
        threading.Thread(target=self._do_process_refresh, daemon=True).start()

    def _do_process_refresh(self) -> None:
        start = time.perf_counter()
        try:
            details = get_process_details()
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(
                f"Could not read processes: {exc}", "error"))
            return
        elapsed = time.perf_counter() - start
        panel = self._pages.get("Processes")
        if panel is not None:
            self._safe_after(lambda: panel.set_rows(details, elapsed))

    def _refresh_startup(self) -> None:
        panel = self._pages.get("Startup")
        if panel is None or self._closed:
            return
        threading.Thread(target=self._do_startup_refresh, daemon=True).start()

    def _do_startup_refresh(self) -> None:
        try:
            entries = self._ensure_engine().startup_entries()
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(
                f"Could not read startup entries: {exc}", "error"))
            return
        panel = self._pages.get("Startup")
        if panel is not None:
            self._safe_after(lambda: panel.set_entries(entries))

    def _on_startup_toggle(self, name: str, enabled: bool) -> None:
        if self._running or not name:
            return
        action = "Enable" if enabled else "Disable"
        if not messagebox.askyesno(
            f"{action} startup entry",
            f"{action} the Spotify startup entry '{name}'?\n\n"
            "A hash-verified snapshot is written first and the registry state is "
            "verified afterwards. You can undo this from Backups & Restore.",
        ):
            return
        self._running = True
        self._set_controls_enabled(False)
        threading.Thread(
            target=self._do_startup_toggle, args=(name, enabled), daemon=True
        ).start()

    def _do_startup_toggle(self, name: str, enabled: bool) -> None:
        try:
            self._set_progress(
                f"{'Enabling' if enabled else 'Disabling'} startup entry…", 0.4
            )
            result = self._ensure_engine().set_startup_entry(name, enabled)
            self._safe_after(lambda: self._on_startup_toggled(result))
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(
                f"Startup change failed: {exc}", "error"))
        finally:
            self._running = False
            self._safe_after(lambda: self._set_controls_enabled(True))
            self._set_progress("", 0)

    def _on_startup_toggled(self, result: OptimizationResult) -> None:
        detail = result.messages[-1] if result.messages else ""
        self.dashboard.show_message(
            "Startup entry updated" if result.success else "Startup entry not changed",
            "success" if result.success else "error",
        )
        self._refresh_startup()
        panel = self._pages.get("Backups")
        if panel is not None:
            panel.refresh()
        if detail and not result.success:
            messagebox.showwarning("Startup entry", detail)

    def _refresh_installation(self) -> None:
        panel = self._pages.get("Installation")
        if panel is None or self._closed:
            return
        threading.Thread(target=self._do_installation_refresh, daemon=True).start()

    def _do_installation_refresh(self) -> None:
        try:
            report = self._ensure_engine().installation_report()
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(
                f"Installation scan failed: {exc}", "error"))
            return
        panel = self._pages.get("Installation")
        if panel is not None:
            self._safe_after(lambda: panel.set_report(report))

    def _on_backups_shown(self) -> None:
        panel = self._pages.get("Backups")
        if panel is not None:
            panel.refresh()

    def _on_activity_shown(self) -> None:
        panel = self._pages.get("Activity")
        if panel is not None:
            panel.reload()

    def _apply_window_icon(self) -> None:
        icon = resource_path("assets/icon.ico")
        if not icon.is_file() or sys.platform != "win32":
            return
        try:
            self.iconbitmap(str(icon))
        except Exception:
            pass

    # ==================================================================
    # Thread-safe UI helpers
    # ==================================================================

    def _get_backups(self) -> list[dict]:
        return self._engine.list_backups() if self._engine else []

    def _on_engine_progress(self, msg: str, pct: float) -> None:
        self._set_progress(msg, pct)

    def _on_log_entry(self, timestamp: str, level: str, message: str) -> None:
        panel = self._pages.get("Activity")
        if panel is None:
            # The Activity page reloads the bounded log buffer when first shown.
            return
        self._safe_after(lambda: panel.append(timestamp, level, message))

    def _safe_after(self, callback) -> None:
        """
        Run ``callback`` on the Tk thread, from any thread.

        ``after()`` cannot be relied on from a worker thread — the scheduled
        callback can silently never run, which previously dropped scan results,
        progress updates and benchmark output.  Worker threads therefore enqueue
        and the Tk thread drains; calls already on the Tk thread run immediately
        so ordinary UI updates stay synchronous.
        """
        if self._closed:
            return
        if threading.current_thread() is threading.main_thread():
            try:
                callback()
            except Exception:
                pass
            return
        self._ui_queue.put(callback)

    def _drain_ui_callbacks(self) -> None:
        """Apply queued worker-thread callbacks on the Tk thread."""
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                try:
                    callback()
                except Exception:
                    pass
        except queue.Empty:
            pass
        finally:
            if not self._closed:
                self.after(30, self._drain_ui_callbacks)

    def _set_status(self, text: str, color: str = MUTED) -> None:
        self._safe_after(lambda: (
            self._top_status.set(text, color),
            self._sidebar_status.set(text, color),
        ))

    def _set_progress(self, msg: str, pct: float) -> None:
        self._safe_after(lambda: (
            self._progress_bar.set(pct),
            self._progress_label.configure(text=msg or "Ready"),
        ))

    def destroy(self) -> None:
        self._closed = True
        try:
            unregister_gui_callback(self._on_log_entry)
        except Exception:
            pass
        super().destroy()
