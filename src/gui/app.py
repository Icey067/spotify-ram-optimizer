"""
Main application window for the Spotify RAM Optimizer workspace.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import messagebox

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.core.config_manager import AppConfig, load_config
from src.core.detector import SpotifyInstallation, detect_installation
from src.core.engine import OptimizationEngine, OptimizationResult, OptimizationSettings
from src.core.logger import register_gui_callback
from src.core.performance_monitor import PerformanceSnapshot

from .components import SidebarButton, StatusPill
from .dashboard_panel import DashboardPanel
from .navigation import NavigationController
from .settings_panel import SettingsPanel
from .theme import ACCENT, BG, ERROR, MUTED, SIDEBAR, SURFACE, SURFACE_RAISED, TEXT, WARNING
from .workspace_pages import AboutPanel, ActivityLogPanel, AppSettingsPanel, BackupsPanel, PerformancePanel


class App(ctk.CTk):
    """Authoritative responsive navigation shell for Spotify Optimizer."""
    VERSION = "1.0.0"

    def __init__(self) -> None:
        super().__init__()

        # Load persistent configuration
        self._config: AppConfig = load_config()
        ctk.set_appearance_mode(self._config.appearance_mode.lower())
        ctk.set_default_color_theme("blue")
        try:
            scale_val = float(self._config.ui_scale.rstrip("%")) / 100
            ctk.set_widget_scaling(scale_val)
        except Exception:
            pass

        self.title("Spotify RAM Optimizer")
        self.geometry("1180x780")
        self.minsize(980, 660)
        self.configure(fg_color=BG)

        self._installation: Optional[SpotifyInstallation] = None
        self._engine: Optional[OptimizationEngine] = None
        self._running = False
        self._closed = False
        self._history: list[float] = []
        self._latest_snapshot = PerformanceSnapshot.capture("Current")

        self._build_ui()
        register_gui_callback(self._on_log_entry)

        # Background auto-scan if enabled in config
        if self._config.auto_scan_on_startup:
            threading.Thread(target=self._auto_scan, daemon=True).start()

        # Start periodic memory sampling
        self._poll_memory()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ===================================================================
        # Sidebar (Col 0)
        # ===================================================================
        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=SIDEBAR)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(2, weight=1)

        # Brand header
        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=20, pady=(24, 18), sticky="ew")
        ctk.CTkLabel(brand, text="SPOTIFY", text_color=ACCENT,
                     font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(brand, text="Optimizer", text_color=TEXT,
                     font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold")).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(brand, text=f"Desktop workspace  •  v{self.VERSION}", text_color=MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=10)).pack(anchor="w")

        # Sidebar navigation items
        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, padx=10, sticky="ew")

        # Create sidebar buttons
        sidebar_buttons: dict[str, SidebarButton] = {}
        nav_items = (
            ("Dashboard", "Dashboard"),
            ("Optimizations", "Optimizations"),
            ("Performance", "Performance"),
            ("Backups", "Backups & Restore"),
            ("Activity", "Activity Logs"),
            ("Settings", "Settings"),
            ("About", "About"),
        )
        for key, label in nav_items:
            btn = SidebarButton(nav, label, lambda item=key: self.show_page(item))
            btn.pack(fill="x", pady=2)
            sidebar_buttons[key] = btn

        # Sidebar footer status
        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=3, column=0, padx=16, pady=16, sticky="ew")
        self._sidebar_status = StatusPill(footer, "Checking Spotify")
        self._sidebar_status.pack(anchor="w")
        ctk.CTkLabel(footer, text="Protected, reversible changes", text_color=MUTED,
                     font=ctk.CTkFont(size=10)).pack(anchor="w", pady=(7, 0))

        # ===================================================================
        # Main Content Area (Col 1)
        # ===================================================================
        content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        # Top bar
        topbar = ctk.CTkFrame(content, height=66, corner_radius=0, fg_color=SURFACE)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        topbar.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(topbar, fg_color="transparent")
        title_box.grid(row=0, column=0, padx=24, pady=12, sticky="w")
        self._page_title = ctk.CTkLabel(title_box, text="Dashboard", text_color=TEXT,
                                        font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"))
        self._page_title.pack(anchor="w")
        self._page_description = ctk.CTkLabel(title_box, text="Overview of your Spotify setup", text_color=MUTED,
                                              font=ctk.CTkFont(family="Segoe UI", size=10))
        self._page_description.pack(anchor="w")

        self._top_status = StatusPill(topbar, "Scanning")
        self._top_status.grid(row=0, column=1, padx=(0, 8), pady=14)

        ctk.CTkButton(topbar, text="Scan Spotify", command=self._on_scan_clicked, width=96, height=30,
                      fg_color=SURFACE_RAISED, hover_color="#29313B").grid(row=0, column=2, padx=(0, 24), pady=14)

        # Page Host (Container where pages live)
        self._page_host = ctk.CTkFrame(content, fg_color="transparent")
        self._page_host.grid(row=1, column=0, sticky="nsew")
        self._page_host.grid_columnconfigure(0, weight=1)
        self._page_host.grid_rowconfigure(0, weight=1)

        # Initialize Navigation Controller
        self.nav = NavigationController(self._page_host, self._page_title, self._page_description)

        # Progress / Status Footer
        progress = ctk.CTkFrame(content, height=38, fg_color=SURFACE, corner_radius=0)
        progress.grid(row=2, column=0, sticky="ew")
        progress.grid_columnconfigure(0, weight=1)
        self._progress_bar = ctk.CTkProgressBar(progress, height=6, progress_color=ACCENT, fg_color="#27303B")
        self._progress_bar.grid(row=0, column=0, padx=(20, 10), pady=14, sticky="ew")
        self._progress_bar.set(0)
        self._progress_label = ctk.CTkLabel(progress, text="Ready", text_color=MUTED, font=ctk.CTkFont(size=10))
        self._progress_label.grid(row=0, column=1, padx=(0, 20))

        # Instantiate all 7 pages and register them
        self._make_pages(sidebar_buttons)

        # Initial navigation to Dashboard
        self.show_page("Dashboard")

    def _make_pages(self, buttons: dict[str, SidebarButton]) -> None:
        """Create and register all 7 workspace pages with the navigation controller."""
        self.dashboard = DashboardPanel(
            self._page_host, self._on_scan_clicked, self._on_run_clicked, self._on_restore_clicked
        )
        self.settings_panel = SettingsPanel(
            self._page_host, on_run=self._on_run_clicked
        )
        self.results_panel = PerformancePanel(
            self._page_host, self._refresh_performance
        )
        self.backups_panel = BackupsPanel(
            self._page_host, self._get_backups, self._on_restore_clicked
        )
        self.log_panel = ActivityLogPanel(
            self._page_host
        )
        self.app_settings_panel = AppSettingsPanel(
            self._page_host, self._set_appearance, self._set_scaling
        )
        self.about_panel = AboutPanel(
            self._page_host
        )

        # Register with NavigationController
        self.nav.register_page("Dashboard", self.dashboard, buttons.get("Dashboard"))
        self.nav.register_page("Optimizations", self.settings_panel, buttons.get("Optimizations"))
        self.nav.register_page("Performance", self.results_panel, buttons.get("Performance"), on_show=self._refresh_performance)
        self.nav.register_page("Backups", self.backups_panel, buttons.get("Backups"), on_show=self.backups_panel.refresh)
        self.nav.register_page("Activity", self.log_panel, buttons.get("Activity"), on_show=self.log_panel.reload)
        self.nav.register_page("Settings", self.app_settings_panel, buttons.get("Settings"))
        self.nav.register_page("About", self.about_panel, buttons.get("About"))

    def show_page(self, name: str) -> bool:
        """Central navigation entry point. Fast, single-click, atomic."""
        return self.nav.show_page(name)

    @property
    def current_page(self) -> str:
        """Authoritative current page query."""
        return self.nav.current_page

    # ===================================================================
    # Optimization Engine Actions
    # ===================================================================

    def _on_scan_clicked(self) -> None:
        if self._running:
            return
        self._set_status("Scanning Spotify", WARNING)
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _on_run_clicked(self) -> None:
        if self._running:
            return
        if self._installation is None or self._installation.install_type.value == "Not Found":
            self.dashboard.show_message("Scan a valid Spotify installation before optimizing.", "error")
            return
        if not messagebox.askyesno(
            "Optimize Spotify",
            "A timestamped backup will be created before modifying preferences, startup entries, or temporary cache files.\n\nContinue?"
        ):
            return
        self._running = True
        self._set_controls_enabled(False)
        settings = self.settings_panel.get_settings()
        threading.Thread(target=self._do_run, args=(settings,), daemon=True).start()

    def _on_restore_clicked(self) -> None:
        if self._running:
            return
        if not messagebox.askyesno(
            "Restore Previous Settings",
            "Restore the latest protected Spotify configuration?\n\nCurrent Spotify settings will be reverted to the snapshot."
        ):
            return
        self._running = True
        self._set_controls_enabled(False)
        threading.Thread(target=self._do_restore, daemon=True).start()

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.dashboard.set_buttons_enabled(enabled)
        self.settings_panel.set_buttons_enabled(enabled)

    # ===================================================================
    # Worker Threads & Engine Operations
    # ===================================================================

    def _auto_scan(self) -> None:
        time.sleep(0.2)
        if not self._closed:
            self._do_scan()

    def _do_scan(self) -> None:
        self._set_progress("Scanning Spotify installation…", 0.2)
        install = detect_installation()
        self._installation = install
        self._engine = OptimizationEngine(installation=install)
        self._engine.set_progress_callback(self._on_engine_progress)
        self._safe_after(self._update_dashboard)
        self._set_progress("", 0)

    def _do_run(self, settings: OptimizationSettings) -> None:
        try:
            self._set_progress("Starting optimization…", 0.1)
            result = self._engine.run_optimization(settings) if self._engine else OptimizationResult()
            self._safe_after(lambda: self._on_run_complete(result))
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(f"Optimization error: {exc}", "error"))
        finally:
            self._running = False
            self._safe_after(lambda: self._set_controls_enabled(True))
            self._set_progress("", 0)

    def _do_restore(self) -> None:
        try:
            self._set_progress("Restoring protected backup…", 0.25)
            result = self._engine.restore_latest() if self._engine else OptimizationResult()
            self._safe_after(lambda: self._on_restore_complete(result))
        except Exception as exc:
            self._safe_after(lambda: self.dashboard.show_message(f"Restore error: {exc}", "error"))
        finally:
            self._running = False
            self._safe_after(lambda: self._set_controls_enabled(True))
            self._set_progress("", 0)

    # ===================================================================
    # UI Updates (Thread-safe on main thread)
    # ===================================================================

    def _update_dashboard(self) -> None:
        install = self._installation
        if install is None:
            return
        info = {
            "Install Type": install.install_type.value,
            "Spicetify": "Detected" if install.spicetify and install.spicetify.is_installed else "Not installed",
            "Version": install.version or "Unknown",
            "Prefs File": "Found" if install.prefs_path else "Missing",
            "Cache": "Found" if install.cache_path else "Missing",
            "Process": "Running" if self._latest_snapshot.process_count else "Stopped",
        }
        self.dashboard.update_info(info)
        if install.spicetify and install.spicetify.is_installed:
            self.settings_panel.update_spicetify(install.spicetify.extensions, install.spicetify.custom_apps)
        color = ACCENT if install.install_type.value != "Not Found" else ERROR
        label = "Spotify detected" if install.install_type.value != "Not Found" else "Spotify not found"
        self._set_status(label, color)

    def _on_run_complete(self, result: OptimizationResult) -> None:
        self.dashboard.show_message(
            "Optimization complete" if result.success else "Optimization completed with warnings",
            "success" if result.success else "error"
        )
        if result.comparison:
            self.results_panel.show_comparison(result.comparison)
        self.backups_panel.refresh()
        self.show_page("Performance")
        self._refresh_performance()

    def _on_restore_complete(self, result: OptimizationResult) -> None:
        self.dashboard.show_message(
            "Restore complete" if result.success else "Restore completed with warnings",
            "success" if result.success else "error"
        )
        self.backups_panel.refresh()
        self._refresh_performance()

    def _on_engine_progress(self, msg: str, pct: float) -> None:
        self._set_progress(msg, pct)

    def _on_log_entry(self, timestamp: str, level: str, message: str) -> None:
        self._safe_after(lambda: self.log_panel.append(timestamp, level, message))

    def _safe_after(self, callback) -> None:
        if self._closed:
            return
        try:
            self.after(0, callback)
        except RuntimeError:
            pass

    def _set_status(self, text: str, color: str = MUTED) -> None:
        self._safe_after(lambda: (self._top_status.set(text, color), self._sidebar_status.set(text, color)))

    def _set_progress(self, msg: str, pct: float) -> None:
        self._safe_after(lambda: (self._progress_bar.set(pct), self._progress_label.configure(text=msg or "Ready")))

    def _refresh_performance(self) -> None:
        self._latest_snapshot = PerformanceSnapshot.capture("Current")
        if self._latest_snapshot.process_count:
            self._history.append(self._latest_snapshot.total_memory_mb)
            self._history = self._history[-36:]
        self.dashboard.update_snapshot(self._latest_snapshot.total_memory_mb, self._latest_snapshot.process_count, self._history)
        self.results_panel.update_snapshot(self._latest_snapshot, self._history)
        if self._installation:
            self._update_dashboard()

    def _poll_memory(self) -> None:
        try:
            self._refresh_performance()
        finally:
            if not self._closed:
                self.after(5000, self._poll_memory)

    def _get_backups(self) -> list[dict]:
        return self._engine.list_backups() if self._engine else []

    @staticmethod
    def _set_appearance(choice: str) -> None:
        ctk.set_appearance_mode(choice.lower())

    @staticmethod
    def _set_scaling(choice: str) -> None:
        ctk.set_widget_scaling(float(choice.rstrip("%")) / 100)

    def destroy(self) -> None:
        self._closed = True
        super().destroy()
