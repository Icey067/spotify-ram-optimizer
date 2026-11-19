"""
Secondary pages for the sidebar workspace:
  - PerformancePanel
  - BackupsPanel
  - ActivityLogPanel
  - AppSettingsPanel
  - AboutPanel
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.core.app_paths import backups_dir, history_db, logs_dir, redact_path
from src.core.config_manager import AppConfig, load_config, save_config
from src.core.logger import get_recent_entries
from src.core.performance_monitor import PerformanceComparison, PerformanceSnapshot

from .components import MemoryChart, MetricCard, PageHeader, SectionCard
from .theme import (
    ACCENT, ACCENT_HOVER, BORDER, ERROR, MUTED, SUBTLE, SUCCESS,
    SURFACE_RAISED, TEXT, WARNING,
)


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


# ---------------------------------------------------------------------------
# 1. Performance Panel
# ---------------------------------------------------------------------------

class PerformancePanel(ctk.CTkScrollableFrame):
    def __init__(
        self,
        master,
        on_refresh: Callable,
        on_benchmark: Optional[Callable] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_benchmark = on_benchmark
        self.grid_columnconfigure((0, 1, 2), weight=1, uniform="metric")
        PageHeader(self, "Performance",
                   "Sampled measurements from active Spotify processes.", on_refresh).grid(
                       row=0, column=0, columnspan=3, padx=18, pady=(20, 14), sticky="ew")

        self.memory = MetricCard(self, "Current RAM", "—",
                                 "Mean working set (last sample)")
        self.processes = MetricCard(self, "Processes", "—", "Detected Spotify processes")
        self.cpu = MetricCard(self, "CPU usage", "—", "Sampled across processes")
        for column, card in enumerate((self.memory, self.processes, self.cpu)):
            card.grid(row=1, column=column,
                      padx=(18 if column == 0 else 6, 18 if column == 2 else 6),
                      pady=4, sticky="ew")

        self.chart = MemoryChart(self)
        self.chart.grid(row=2, column=0, columnspan=3, padx=18, pady=(14, 6), sticky="ew")

        self.result = SectionCard(self)
        self.result.grid(row=3, column=0, columnspan=3, padx=18, pady=(8, 6), sticky="ew")
        self.result.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkLabel(self.result, text="LAST OPTIMIZATION RESULT", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=0, column=0, columnspan=3, padx=16, pady=(14, 8), sticky="w")

        self.result_labels: list[ctk.CTkLabel] = []
        for column, (label, value) in enumerate((
            ("Before", "No measured run yet"), ("After", "—"), ("Difference", "—"),
        )):
            ctk.CTkLabel(self.result, text=label.upper(), text_color=SUBTLE,
                         font=ctk.CTkFont(size=10, weight="bold")).grid(
                             row=1, column=column, padx=16, sticky="w")
            item = ctk.CTkLabel(self.result, text=value, text_color=TEXT,
                                font=ctk.CTkFont(size=14, weight="bold"))
            item.grid(row=2, column=column, padx=16, pady=(2, 6), sticky="w")
            self.result_labels.append(item)

        self._comparison_note = ctk.CTkLabel(
            self.result,
            text="Measurements are only compared when Spotify ran for both readings.",
            text_color=SUBTLE, justify="left", wraplength=760,
            font=ctk.CTkFont(size=10),
        )
        self._comparison_note.grid(row=3, column=0, columnspan=3, padx=16,
                                   pady=(0, 14), sticky="w")

        tools = SectionCard(self)
        tools.grid(row=4, column=0, columnspan=3, padx=18, pady=(6, 20), sticky="ew")
        tools.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(tools, text="BENCHMARK", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        self._benchmark_note = ctk.CTkLabel(
            tools, text="A benchmark samples for a few seconds and reports mean values.",
            text_color=SUBTLE, font=ctk.CTkFont(size=10))
        self._benchmark_note.grid(row=1, column=0, columnspan=2, padx=16,
                                  pady=(0, 12), sticky="w")
        self._benchmark_button = ctk.CTkButton(
            tools, text="Run benchmark", width=130, height=30,
            command=self.on_benchmark or (lambda: None),
            fg_color=SURFACE_RAISED, hover_color="#333E4C",
            state="normal" if self.on_benchmark else "disabled")
        self._benchmark_button.grid(row=0, column=1, rowspan=2, padx=16, sticky="e")

    def update_snapshot(self, snapshot: PerformanceSnapshot, history: list[float]) -> None:
        if snapshot.process_count > 0:
            self.memory.set(f"{snapshot.total_memory_mb:.1f} MB",
                            f"{snapshot.source} reading", ACCENT)
            self.processes.set(str(snapshot.process_count), "Active Spotify processes")
            self.cpu.set(f"{snapshot.cpu_percent:.1f}%", "Aggregated process CPU usage")
        else:
            self.memory.set("Not running", "Spotify is currently closed", MUTED)
            self.processes.set("0", "No Spotify processes detected")
            self.cpu.set("0.0%", "No active processes")
        self.chart.set_values(history)

    def show_comparison(self, comparison: PerformanceComparison) -> None:
        report = comparison.report()
        self.result_labels[0].configure(text=f"{report['before_mb']:.1f} MB")
        self.result_labels[1].configure(text=f"{report['after_mb']:.1f} MB")

        if not report["comparable"]:
            self.result_labels[2].configure(text="Not comparable", text_color=WARNING)
            note = ("No memory difference is shown: Spotify was not running for both "
                    "measurements, so a before/after RAM claim would be misleading.")
        else:
            freed = report["freed_mb"]
            if abs(freed) < 0.05:
                text, color = "No change", MUTED
            elif freed > 0:
                text, color = f"↓ {freed:.1f} MB", SUCCESS
            else:
                text, color = f"↑ {abs(freed):.1f} MB", WARNING
            self.result_labels[2].configure(text=text, text_color=color)
            note = " ".join(report.get("notes", [])) or report["note"]

        cache = report.get("cache_freed_mb") or 0.0
        if cache:
            note += f"  Cache cleanup reported {cache:.1f} MB of removed files."
        self._comparison_note.configure(text=note)

    def set_benchmark_text(self, text: str) -> None:
        self._benchmark_note.configure(text=text)


# ---------------------------------------------------------------------------
# 2. Backups & Restore Panel
# ---------------------------------------------------------------------------

class BackupsPanel(ctk.CTkScrollableFrame):
    def __init__(
        self,
        master,
        get_backups: Callable[[], list[dict]],
        on_restore: Callable,
        on_restore_session: Optional[Callable[[str], None]] = None,
        on_delete: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.get_backups = get_backups
        self.on_restore = on_restore
        self.on_restore_session = on_restore_session
        self.on_delete = on_delete
        self.grid_columnconfigure(0, weight=1)

        PageHeader(self, "Backups & Restore",
                   "Hash-verified snapshots. Restore one, or everything, at any time.",
                   self.refresh).grid(row=0, column=0, padx=18, pady=(20, 14), sticky="ew")

        self.summary = SectionCard(self)
        self.summary.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        self.summary.grid_columnconfigure(0, weight=1)
        self.summary_text = ctk.CTkLabel(self.summary,
                                        text="Loading backup snapshots…",
                                        text_color=MUTED, font=ctk.CTkFont(size=12))
        self.summary_text.grid(row=0, column=0, padx=16, pady=14, sticky="w")

        self.restore_button = ctk.CTkButton(
            self.summary, text="Restore Latest", command=self.on_restore, height=32,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#08120C",
            font=ctk.CTkFont(size=12, weight="bold"))
        self.restore_button.grid(row=0, column=1, padx=14, pady=10)

        self.listing = ctk.CTkFrame(self, fg_color="transparent")
        self.listing.grid(row=2, column=0, padx=18, pady=(0, 20), sticky="ew")
        self.listing.grid_columnconfigure(0, weight=1)

    def refresh(self) -> None:
        for child in self.listing.winfo_children():
            child.destroy()
        try:
            backups = self.get_backups()
        except Exception:
            backups = []

        count = len(backups)
        total_bytes = sum(b.get("size_bytes", 0) for b in backups)
        self.summary_text.configure(
            text=(f"{count} snapshot{'s' if count != 1 else ''} · "
                  f"{_format_bytes(total_bytes)} on disk · "
                  f"stored in {redact_path(backups_dir())}")
        )

        if not backups:
            empty = SectionCard(self.listing)
            empty.grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(empty, text="No Backups Recorded", text_color=TEXT,
                         font=ctk.CTkFont(size=16, weight="bold")).pack(
                             anchor="w", padx=16, pady=(16, 2))
            ctk.CTkLabel(
                empty,
                text="A timestamped, hash-verified backup is created before any change.",
                text_color=MUTED, font=ctk.CTkFont(size=11)).pack(
                    anchor="w", padx=16, pady=(0, 16))
            return

        for row, backup in enumerate(backups):
            card = SectionCard(self.listing)
            card.grid(row=row, column=0, pady=5, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            artefacts = backup.get("artefacts", {})
            parts = []
            if artefacts.get("prefs"):
                parts.append("Preferences")
            if artefacts.get("registry"):
                parts.append("Startup entries")
            if artefacts.get("shortcuts"):
                parts.append("Shortcuts")
            if artefacts.get("spicetify"):
                parts.append("Spicetify")
            components_text = " • ".join(parts) if parts else "Empty snapshot"
            created = backup.get("created_at") or backup.get("name", "Unknown")

            ctk.CTkLabel(card, text=f"Snapshot {backup.get('name', 'Session')}",
                         text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold")).grid(
                             row=0, column=0, padx=16, pady=(12, 0), sticky="w")
            ctk.CTkLabel(card, text=f"{created} · {components_text}",
                         text_color=SUBTLE, font=ctk.CTkFont(size=11)).grid(
                             row=1, column=0, padx=16, pady=(0, 4), sticky="w")

            integrity_ok = backup.get("integrity_ok")
            if backup.get("has_manifest"):
                status_text = "Integrity verified" if integrity_ok else "Integrity problem"
                status_color = SUCCESS if integrity_ok else ERROR
            else:
                status_text = "Legacy snapshot (no manifest)"
                status_color = WARNING
            ctk.CTkLabel(card, text=status_text, text_color=status_color,
                         font=ctk.CTkFont(size=10, weight="bold")).grid(
                             row=2, column=0, padx=16, pady=(0, 12), sticky="w")

            operations = backup.get("operations") or []
            if operations:
                ctk.CTkLabel(card, text="Operations: " + ", ".join(operations[:6]),
                             text_color=SUBTLE, font=ctk.CTkFont(size=10)).grid(
                                 row=3, column=0, padx=16, pady=(0, 12), sticky="w")

            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.grid(row=0, column=1, rowspan=4, padx=14, pady=10, sticky="e")
            if self.on_restore_session:
                ctk.CTkButton(
                    buttons, text="Restore this", width=104, height=28,
                    command=lambda name=backup.get("name"): self.on_restore_session(name),
                    fg_color="#27303B", hover_color="#333E4C").pack(side="left", padx=4)
            if self.on_delete:
                ctk.CTkButton(
                    buttons, text="Delete", width=70, height=28,
                    command=lambda name=backup.get("name"): self.on_delete(name),
                    fg_color="#3A2226", hover_color="#4A2A2F",
                    text_color="#F0B4B4").pack(side="left", padx=4)


# ---------------------------------------------------------------------------
# 3. Activity Logs Panel
# ---------------------------------------------------------------------------

class ActivityLogPanel(ctk.CTkFrame):
    LEVELS = ("All", "Information", "Success", "Warning", "Error")

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.entries: list[tuple[str, str, str]] = []

        PageHeader(self, "Activity Logs",
                   "A live, filterable record of scans, optimizations, and restores.",
                   self.reload).grid(row=0, column=0, padx=18, pady=(20, 12), sticky="ew")

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=1, column=0, padx=18, pady=(0, 8), sticky="ew")
        tools.grid_columnconfigure(1, weight=1)

        self.filter_var = ctk.StringVar(value="All")
        self.filter_var.trace_add("write", lambda *_: self.render())
        ctk.CTkOptionMenu(tools, values=list(self.LEVELS), variable=self.filter_var,
                          width=120, fg_color=SURFACE_RAISED,
                          button_color="#303A46").grid(row=0, column=0, padx=(0, 8))

        self.search = ctk.CTkEntry(tools, placeholder_text="Search logs (filter by text)",
                                  height=32, border_color=BORDER)
        self.search.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.search.bind("<KeyRelease>", lambda _e: self.render())

        ctk.CTkButton(tools, text="Export", width=72, height=32, command=self.export,
                      fg_color="#27303B", hover_color="#333E4C").grid(
                          row=0, column=2, padx=4)
        ctk.CTkButton(tools, text="Clear view", width=88, height=32,
                      command=self.clear_visible, fg_color="#27303B",
                      hover_color="#333E4C").grid(row=0, column=3)

        self.text = ctk.CTkTextbox(self, state="disabled", wrap="word",
                                   font=ctk.CTkFont(family="Consolas", size=11),
                                   border_width=1, border_color=BORDER)
        self.text.grid(row=2, column=0, padx=18, pady=(0, 18), sticky="nsew")

        inner = self.text._textbox
        for name, color in {"INFO": MUTED, "SUCCESS": SUCCESS, "WARNING": WARNING,
                            "ERROR": ERROR, "DEBUG": SUBTLE}.items():
            inner.tag_configure(name, foreground=color)

        self.reload()

    def append(self, timestamp: str, level: str, message: str) -> None:
        """Append a log entry; only paints when the page is visible."""
        self.entries.append((timestamp, level, message))
        if len(self.entries) > 2000:
            self.entries.pop(0)

        if self.winfo_ismapped():
            selected = self.filter_var.get()
            wanted = {"Information": "INFO", "Success": "SUCCESS",
                      "Warning": "WARNING", "Error": "ERROR"}.get(selected)
            if not wanted or level.upper() == wanted:
                query = self.search.get().lower() if hasattr(self, "search") else ""
                if not query or query in message.lower() or query in level.lower():
                    self.text.configure(state="normal")
                    inner = self.text._textbox
                    inner.insert("end", f"{timestamp}  ", ("INFO",))
                    inner.insert("end", f"{level:<7}  ", (level.upper(),))
                    inner.insert("end", message + "\n", ("INFO",))
                    inner.see("end")
                    self.text.configure(state="disabled")

    def reload(self) -> None:
        self.entries = get_recent_entries(1000)
        self.render()

    def render(self) -> None:
        """Full re-render with the active filters."""
        selected = self.filter_var.get()
        wanted = {"Information": "INFO", "Success": "SUCCESS",
                  "Warning": "WARNING", "Error": "ERROR"}.get(selected)
        query = self.search.get().lower() if hasattr(self, "search") else ""

        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        inner = self.text._textbox
        for timestamp, level, message in self.entries:
            if wanted and level.upper() != wanted:
                continue
            line = f"{timestamp}  {level:<7}  {message}"
            if query and query not in line.lower():
                continue
            inner.insert("end", f"{timestamp}  ", ("INFO",))
            inner.insert("end", f"{level:<7}  ", (level.upper(),))
            inner.insert("end", message + "\n", ("INFO",))
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear_visible(self) -> None:
        self.entries.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def export(self) -> None:
        target = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt")])
        if not target:
            return
        try:
            Path(target).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
            messagebox.showinfo("Export Successful", f"Logs exported to:\n{target}")
        except OSError as exc:
            messagebox.showerror("Export Failed", str(exc))


# ---------------------------------------------------------------------------
# 4. App Settings Panel
# ---------------------------------------------------------------------------

class AppSettingsPanel(ctk.CTkScrollableFrame):
    def __init__(
        self,
        master,
        on_appearance: Callable[[str], None],
        on_scaling: Callable[[str], None],
        on_clear_history: Optional[Callable[[], None]] = None,
        on_clear_logs: Optional[Callable[[], None]] = None,
        on_open_folder: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_appearance = on_appearance
        self.on_scaling = on_scaling
        self.on_clear_history = on_clear_history
        self.on_clear_logs = on_clear_logs
        self.on_open_folder = on_open_folder
        self.config: AppConfig = load_config()

        self.grid_columnconfigure(0, weight=1)
        PageHeader(self, "Settings",
                   "Workspace preferences, monitoring, retention and privacy.").grid(
                       row=0, column=0, padx=18, pady=(20, 12), sticky="ew")

        appearance = SectionCard(self)
        appearance.grid(row=1, column=0, padx=18, pady=5, sticky="ew")
        appearance.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(appearance, text="Appearance & Display", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).grid(
                         row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")

        ctk.CTkLabel(appearance, text="Theme mode", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=16,
                                                     pady=7, sticky="w")
        self.theme_menu = ctk.CTkOptionMenu(
            appearance, values=["Dark", "Light", "System"],
            command=self._handle_theme, width=130)
        self.theme_menu.set(self.config.appearance_mode)
        self.theme_menu.grid(row=1, column=1, padx=16, pady=7, sticky="e")

        ctk.CTkLabel(appearance, text="Interface scaling", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=2, column=0, padx=16,
                                                     pady=(7, 14), sticky="w")
        self.scale_menu = ctk.CTkOptionMenu(
            appearance, values=["90%", "100%", "110%", "125%"],
            command=self._handle_scaling, width=130)
        self.scale_menu.set(self.config.ui_scale)
        self.scale_menu.grid(row=2, column=1, padx=16, pady=(7, 14), sticky="e")

        monitoring = SectionCard(self)
        monitoring.grid(row=2, column=0, padx=18, pady=10, sticky="ew")
        monitoring.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(monitoring, text="Monitoring & History", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).grid(
                         row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")

        ctk.CTkLabel(monitoring, text="Sampling interval (seconds)", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=16,
                                                     pady=7, sticky="w")
        self.interval_menu = ctk.CTkOptionMenu(
            monitoring, values=["2", "5", "10", "30", "60"], width=130,
            command=self._handle_interval)
        self.interval_menu.set(str(self.config.monitoring_interval_seconds))
        self.interval_menu.grid(row=1, column=1, padx=16, pady=7, sticky="e")

        ctk.CTkLabel(monitoring, text="History retention (days, 0 = unlimited)",
                     text_color=MUTED, font=ctk.CTkFont(size=12)).grid(
                         row=2, column=0, padx=16, pady=7, sticky="w")
        self.retention_menu = ctk.CTkOptionMenu(
            monitoring, values=["0", "30", "90", "365"], width=130,
            command=self._handle_retention)
        self.retention_menu.set(str(self.config.history_retention_days))
        self.retention_menu.grid(row=2, column=1, padx=16, pady=7, sticky="e")

        self.history_var = ctk.BooleanVar(value=self.config.enable_performance_history)
        ctk.CTkCheckBox(monitoring, text="Record performance history locally",
                        variable=self.history_var,
                        command=self._handle_history_toggle).grid(
                            row=3, column=0, columnspan=2, padx=16, pady=(4, 2), sticky="w")
        ctk.CTkLabel(monitoring,
                     text="Stored in a local SQLite file. Nothing is sent anywhere.",
                     text_color=SUBTLE, font=ctk.CTkFont(size=10)).grid(
                         row=4, column=0, columnspan=2, padx=28, pady=(0, 8), sticky="w")

        self.restart_var = ctk.BooleanVar(
            value=self.config.restart_spotify_after_optimization)
        ctk.CTkCheckBox(monitoring, text="Restart Spotify after optimizations",
                        variable=self.restart_var,
                        command=self._handle_restart_toggle).grid(
                            row=5, column=0, columnspan=2, padx=16, pady=(2, 14), sticky="w")

        safety = SectionCard(self)
        safety.grid(row=3, column=0, padx=18, pady=5, sticky="ew")
        ctk.CTkLabel(safety, text="Safety & Reversibility", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         anchor="w", padx=16, pady=(14, 3))
        ctk.CTkLabel(
            safety,
            text="Every run creates a hash-verified backup before touching Spotify "
                 "preferences, startup entries, or temporary cache files. Nothing is "
                 "changed without a preview you can review, and every setting change can "
                 "be restored from Backups & Restore.",
            text_color=MUTED, justify="left", wraplength=680,
            font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=(0, 14))

        privacy = SectionCard(self)
        privacy.grid(row=4, column=0, padx=18, pady=10, sticky="ew")
        privacy.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(privacy, text="Privacy & Transparency", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).grid(
                         row=0, column=0, columnspan=2, padx=16, pady=(14, 4), sticky="w")
        ctk.CTkLabel(
            privacy,
            text=("This application is local-only: no telemetry, no analytics, no network "
                  "requests. It reads your Spotify installation, prefs file, cache sizes, "
                  "process list and HKCU startup entries. It writes only the settings you "
                  "explicitly apply, plus its own backups, logs and performance history.\n\n"
                  f"Backups: {redact_path(backups_dir())}\n"
                  f"Logs: {redact_path(logs_dir())}\n"
                  f"History: {redact_path(history_db())}"),
            text_color=MUTED, justify="left", wraplength=680,
            font=ctk.CTkFont(size=11)).grid(row=1, column=0, columnspan=2, padx=16,
                                            pady=(0, 10), sticky="w")

        buttons = ctk.CTkFrame(privacy, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="w")
        for text, command in (
            ("Open backups", lambda: self._open("backups")),
            ("Open logs", lambda: self._open("logs")),
            ("Clear history", self.on_clear_history),
            ("Clear logs", self.on_clear_logs),
        ):
            ctk.CTkButton(buttons, text=text, width=110, height=30,
                          command=command or (lambda: None),
                          fg_color=SURFACE_RAISED, hover_color="#333E4C",
                          state="normal" if command else "disabled").pack(
                              side="left", padx=(0, 8))

    # -- handlers -------------------------------------------------------

    def _handle_theme(self, choice: str) -> None:
        self.config.appearance_mode = choice
        save_config(self.config)
        self.on_appearance(choice)

    def _handle_scaling(self, choice: str) -> None:
        self.config.ui_scale = choice
        save_config(self.config)
        self.on_scaling(choice)

    def _handle_interval(self, choice: str) -> None:
        try:
            self.config.monitoring_interval_seconds = max(2, int(choice))
        except ValueError:
            return
        save_config(self.config)

    def _handle_retention(self, choice: str) -> None:
        try:
            self.config.history_retention_days = max(0, int(choice))
        except ValueError:
            return
        save_config(self.config)

    def _handle_history_toggle(self) -> None:
        self.config.enable_performance_history = bool(self.history_var.get())
        save_config(self.config)

    def _handle_restart_toggle(self) -> None:
        self.config.restart_spotify_after_optimization = bool(self.restart_var.get())
        save_config(self.config)

    def _open(self, which: str) -> None:
        if self.on_open_folder:
            self.on_open_folder(which)
            return
        target = backups_dir() if which == "backups" else logs_dir()
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target))


# ---------------------------------------------------------------------------
# 5. About Panel
# ---------------------------------------------------------------------------

class AboutPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, version: str = "1.2.0", **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.version = version
        self.grid_columnconfigure(0, weight=1)

        PageHeader(self, "About",
                   "Application information, version details, and safety principles.").grid(
                       row=0, column=0, padx=18, pady=(20, 12), sticky="ew")

        card = SectionCard(self)
        card.grid(row=1, column=0, padx=18, pady=5, sticky="ew")
        ctk.CTkLabel(card, text="Spotify RAM Optimizer", text_color=TEXT,
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(card, text=f"Version {self.version} · Windows Desktop Release",
                     text_color=ACCENT, font=ctk.CTkFont(size=13, weight="bold")).pack(
                         anchor="w", padx=20)
        ctk.CTkLabel(card, text="Designed and developed by Icey", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20, pady=(2, 0))
        ctk.CTkLabel(
            card,
            text=("A Windows utility for understanding and managing Spotify's resource "
                  "use. It measures before it changes anything, explains what each "
                  "operation does, backs up every change, and never claims a performance "
                  "result it cannot measure."),
            text_color=MUTED, justify="left", wraplength=680,
            font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20, pady=(10, 16))

        arch = SectionCard(self)
        arch.grid(row=2, column=0, padx=18, pady=10, sticky="ew")
        ctk.CTkLabel(arch, text="Safety Architecture", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         anchor="w", padx=20, pady=(14, 6))
        for point in (
            "Never modifies or patches Spotify installation binaries.",
            "Never deletes playlists, downloads, cookies, logins, local storage, "
            "IndexedDB or databases.",
            "Operates under standard Windows user permissions — no administrator access.",
            "Creates and hash-verifies a timestamped backup before any change.",
            "Every operation is listed with its risk level and compatibility verdict.",
            "Unverified settings are disabled by default and labelled.",
        ):
            ctk.CTkLabel(arch, text=f"✓  {point}", text_color=MUTED,
                         font=ctk.CTkFont(size=11)).pack(anchor="w", padx=24, pady=2)
        ctk.CTkLabel(arch, text="", height=8).pack()

        links = SectionCard(self)
        links.grid(row=3, column=0, padx=18, pady=5, sticky="ew")
        ctk.CTkLabel(links, text="Documentation & Folders", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         anchor="w", padx=20, pady=(14, 8))
        bar = ctk.CTkFrame(links, fg_color="transparent")
        bar.pack(anchor="w", padx=20, pady=(0, 16))
        for text, command in (
            ("Documentation", self._open_docs),
            ("Backups folder", lambda: self._open_folder(backups_dir())),
            ("Logs folder", lambda: self._open_folder(logs_dir())),
        ):
            ctk.CTkButton(bar, text=text, command=command, width=140, height=32,
                          fg_color=SURFACE_RAISED, hover_color="#27303B").pack(
                              side="left", padx=(0, 8))

    def _open_docs(self) -> None:
        readme = Path(__file__).resolve().parent.parent.parent / "README.md"
        if readme.exists():
            os.startfile(str(readme))
        else:
            messagebox.showinfo(
                "Documentation",
                "Documentation is available in the project README.md.")

    @staticmethod
    def _open_folder(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))
