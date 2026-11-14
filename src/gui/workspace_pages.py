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
from typing import Callable

import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.core.config_manager import AppConfig, load_config, save_config
from src.core.logger import get_recent_entries
from src.core.performance_monitor import PerformanceComparison, PerformanceSnapshot

from .components import MemoryChart, MetricCard, PageHeader, SectionCard
from .theme import ACCENT, ACCENT_HOVER, BORDER, ERROR, MUTED, SUBTLE, SUCCESS, SURFACE, SURFACE_RAISED, TEXT, WARNING


# ---------------------------------------------------------------------------
# 1. Performance Panel
# ---------------------------------------------------------------------------

class PerformancePanel(ctk.CTkScrollableFrame):
    def __init__(self, master, on_refresh: Callable, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure((0, 1, 2), weight=1, uniform="metric")
        PageHeader(self, "Performance", "Live measurements from active Spotify processes.", on_refresh).grid(
            row=0, column=0, columnspan=3, padx=18, pady=(20, 14), sticky="ew")

        self.memory = MetricCard(self, "Current RAM", "—", "Combined resident memory")
        self.processes = MetricCard(self, "Processes", "—", "Detected Spotify processes")
        self.cpu = MetricCard(self, "CPU usage", "—", "Latest sampled process usage")
        for col, card in enumerate((self.memory, self.processes, self.cpu)):
            card.grid(row=1, column=col, padx=(18 if col == 0 else 6, 18 if col == 2 else 6), pady=4, sticky="ew")

        self.chart = MemoryChart(self)
        self.chart.grid(row=2, column=0, columnspan=3, padx=18, pady=(14, 6), sticky="ew")

        self.result = SectionCard(self)
        self.result.grid(row=3, column=0, columnspan=3, padx=18, pady=(8, 20), sticky="ew")
        self.result.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkLabel(self.result, text="LAST OPTIMIZATION RESULT", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
            row=0, column=0, columnspan=3, padx=16, pady=(14, 8), sticky="w")

        self.result_labels: list[ctk.CTkLabel] = []
        for col, (label, value) in enumerate((("Before", "No measured run yet"), ("After", "—"), ("Difference", "—"))):
            ctk.CTkLabel(self.result, text=label.upper(), text_color=SUBTLE,
                         font=ctk.CTkFont(size=10, weight="bold")).grid(row=1, column=col, padx=16, sticky="w")
            item = ctk.CTkLabel(self.result, text=value, text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold"))
            item.grid(row=2, column=col, padx=16, pady=(2, 14), sticky="w")
            self.result_labels.append(item)

    def update_snapshot(self, snapshot: PerformanceSnapshot, history: list[float]) -> None:
        if snapshot.process_count > 0:
            self.memory.set(f"{snapshot.total_memory_mb:.1f} MB", "Combined resident memory", ACCENT)
            self.processes.set(str(snapshot.process_count), "Active Spotify processes")
            cpu = sum(item.get("cpu_percent", 0) for item in snapshot.per_process)
            self.cpu.set(f"{cpu:.1f}%", "Aggregated process CPU usage")
        else:
            self.memory.set("Not running", "Spotify is currently closed", MUTED)
            self.processes.set("0", "No Spotify processes detected")
            self.cpu.set("0.0%", "Process idle")
        self.chart.set_values(history)

    def show_comparison(self, comparison: PerformanceComparison) -> None:
        report = comparison.report()
        self.result_labels[0].configure(text=f"{report['before_mb']:.1f} MB")
        self.result_labels[1].configure(text=f"{report['after_mb']:.1f} MB")
        freed = report["freed_mb"]
        self.result_labels[2].configure(
            text=f"↓ {freed:.1f} MB" if freed > 0 else f"↑ {abs(freed):.1f} MB" if freed < 0 else "No change",
            text_color=SUCCESS if freed > 0 else WARNING if freed < 0 else MUTED,
        )


# ---------------------------------------------------------------------------
# 2. Backups & Restore Panel
# ---------------------------------------------------------------------------

class BackupsPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, get_backups: Callable[[], list[dict]], on_restore: Callable, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.get_backups = get_backups
        self.on_restore = on_restore
        self.grid_columnconfigure(0, weight=1)

        PageHeader(self, "Backups & Restore",
                   "Protected configuration snapshots. Restore any previous configuration safely.",
                   self.refresh).grid(row=0, column=0, padx=18, pady=(20, 14), sticky="ew")

        self.summary = SectionCard(self)
        self.summary.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        self.summary.grid_columnconfigure(0, weight=1)
        self.summary_text = ctk.CTkLabel(self.summary, text="Loading backup snapshots…",
                                        text_color=MUTED, font=ctk.CTkFont(size=12))
        self.summary_text.grid(row=0, column=0, padx=16, pady=14, sticky="w")

        self.restore_button = ctk.CTkButton(
            self.summary, text="Restore Latest Backup",
            command=self.on_restore, height=32,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#08120C",
            font=ctk.CTkFont(size=12, weight="bold")
        )
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
        self.summary_text.configure(
            text=f"{count} protected backup session{'s' if count != 1 else ''} available on disk"
        )

        if not backups:
            empty = SectionCard(self.listing)
            empty.grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(empty, text="No Backups Recorded", text_color=TEXT,
                         font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=16, pady=(16, 2))
            ctk.CTkLabel(empty, text="A timestamped backup is automatically created every time you run an optimization.",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=(0, 16))
            return

        for row, backup in enumerate(backups):
            card = SectionCard(self.listing)
            card.grid(row=row, column=0, pady=5, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            valid = backup.get("artefacts", {})
            parts = []
            if valid.get("prefs"):
                parts.append("Preferences")
            if valid.get("registry"):
                parts.append("Startup Entry")
            if valid.get("shortcuts"):
                parts.append("Shortcuts")
            if valid.get("spicetify"):
                parts.append("Spicetify")

            components_str = " • ".join(parts) if parts else "Empty snapshot"
            created = backup.get("created_at") or backup.get("name", "Unknown")

            header_frame = ctk.CTkFrame(card, fg_color="transparent")
            header_frame.grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
            ctk.CTkLabel(header_frame, text=f"Snapshot: {backup.get('name', 'Session')}",
                         text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            ctk.CTkLabel(header_frame, text=f"  ({created})",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).pack(side="left")

            ctk.CTkLabel(card, text=f"Protected: {components_str}",
                         text_color=SUBTLE, font=ctk.CTkFont(size=11)).grid(
                             row=1, column=0, padx=16, pady=(0, 12), sticky="w")

            status_text = "Verified" if valid.get("metadata") else "Partial"
            status_color = SUCCESS if valid.get("metadata") else WARNING
            ctk.CTkLabel(card, text=status_text, text_color=status_color,
                         font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=1, rowspan=2, padx=16)


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
                   "A live, filterable record of scans, optimizations, and restore actions.",
                   self.reload).grid(row=0, column=0, padx=18, pady=(20, 12), sticky="ew")

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=1, column=0, padx=18, pady=(0, 8), sticky="ew")
        tools.grid_columnconfigure(1, weight=1)

        self.filter_var = ctk.StringVar(value="All")
        self.filter_var.trace_add("write", lambda *_: self.render())
        ctk.CTkOptionMenu(tools, values=list(self.LEVELS), variable=self.filter_var,
                          width=120, fg_color=SURFACE_RAISED, button_color="#303A46").grid(row=0, column=0, padx=(0, 8))

        self.search = ctk.CTkEntry(tools, placeholder_text="Search logs (filter by text)",
                                  height=32, border_color=BORDER)
        self.search.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.search.bind("<KeyRelease>", lambda _e: self.render())

        ctk.CTkButton(tools, text="Export", width=72, height=32, command=self.export,
                      fg_color="#27303B", hover_color="#333E4C").grid(row=0, column=2, padx=4)
        ctk.CTkButton(tools, text="Clear view", width=88, height=32, command=self.clear_visible,
                      fg_color="#27303B", hover_color="#333E4C").grid(row=0, column=3)

        self.text = ctk.CTkTextbox(self, state="disabled", wrap="word",
                                   font=ctk.CTkFont(family="Consolas", size=11),
                                   border_width=1, border_color=BORDER)
        self.text.grid(row=2, column=0, padx=18, pady=(0, 18), sticky="nsew")

        inner = self.text._textbox
        for name, color in {"INFO": MUTED, "SUCCESS": SUCCESS, "WARNING": WARNING, "ERROR": ERROR, "DEBUG": SUBTLE}.items():
            inner.tag_configure(name, foreground=color)

        self.reload()

    def append(self, timestamp: str, level: str, message: str) -> None:
        """Append log entry efficiently. Does not rebuild entire textbox if active."""
        self.entries.append((timestamp, level, message))
        if len(self.entries) > 2000:
            self.entries.pop(0)

        # Only update GUI widget if mapped to prevent background paint bleed
        if self.winfo_ismapped():
            selected = self.filter_var.get()
            wanted = {"Information": "INFO", "Success": "SUCCESS", "Warning": "WARNING", "Error": "ERROR"}.get(selected)
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
        """Full re-render with active filters."""
        selected = self.filter_var.get()
        wanted = {"Information": "INFO", "Success": "SUCCESS", "Warning": "WARNING", "Error": "ERROR"}.get(selected)
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
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt")]
        )
        if target:
            Path(target).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
            messagebox.showinfo("Export Successful", f"Logs exported to:\n{target}")


# ---------------------------------------------------------------------------
# 4. App Settings Panel
# ---------------------------------------------------------------------------

class AppSettingsPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, on_appearance: Callable[[str], None], on_scaling: Callable[[str], None], **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_appearance = on_appearance
        self.on_scaling = on_scaling
        self.config: AppConfig = load_config()

        self.grid_columnconfigure(0, weight=1)
        PageHeader(self, "Settings",
                   "Customize desktop workspace preferences and persistent behaviors.").grid(
                       row=0, column=0, padx=18, pady=(20, 12), sticky="ew")

        # Appearance Card
        appearance = SectionCard(self)
        appearance.grid(row=1, column=0, padx=18, pady=5, sticky="ew")
        appearance.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(appearance, text="Appearance & Display", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).grid(
                         row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")

        ctk.CTkLabel(appearance, text="Theme Mode", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=16, pady=7, sticky="w")
        self.theme_menu = ctk.CTkOptionMenu(
            appearance, values=["Dark", "Light", "System"],
            command=self._handle_theme, width=130
        )
        self.theme_menu.set(self.config.appearance_mode)
        self.theme_menu.grid(row=1, column=1, padx=16, pady=7, sticky="e")

        ctk.CTkLabel(appearance, text="Interface Scaling", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=2, column=0, padx=16, pady=(7, 14), sticky="w")
        self.scale_menu = ctk.CTkOptionMenu(
            appearance, values=["90%", "100%", "110%", "125%"],
            command=self._handle_scaling, width=130
        )
        self.scale_menu.set(self.config.ui_scale)
        self.scale_menu.grid(row=2, column=1, padx=16, pady=(7, 14), sticky="e")

        # Automation & Startup Card
        automation = SectionCard(self)
        automation.grid(row=2, column=0, padx=18, pady=10, sticky="ew")
        automation.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(automation, text="Startup & Diagnostics", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).grid(
                         row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")

        self.auto_scan_var = ctk.BooleanVar(value=self.config.auto_scan_on_startup)
        ctk.CTkCheckBox(
            automation, text="Automatically scan Spotify installation on startup",
            variable=self.auto_scan_var, command=self._handle_autoscan
        ).grid(row=1, column=0, columnspan=2, padx=16, pady=8, sticky="w")

        # Safety & Storage Info
        safety = SectionCard(self)
        safety.grid(row=3, column=0, padx=18, pady=5, sticky="ew")
        ctk.CTkLabel(safety, text="Safety & Reversibility Architecture", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=16, pady=(14, 3))
        ctk.CTkLabel(
            safety,
            text="Optimization parameters are selected on the Optimizations page. Every run automatically "
                 "creates a timestamped backup before touching Spotify preferences, startup entries, or temporary "
                 "cache files. All modifications can be reverted from the Backups & Restore tab.",
            text_color=MUTED, justify="left", wraplength=650, font=ctk.CTkFont(size=11)
        ).pack(anchor="w", padx=16, pady=(0, 14))

    def _handle_theme(self, choice: str) -> None:
        self.config.appearance_mode = choice
        save_config(self.config)
        self.on_appearance(choice)

    def _handle_scaling(self, choice: str) -> None:
        self.config.ui_scale = choice
        save_config(self.config)
        self.on_scaling(choice)

    def _handle_autoscan(self) -> None:
        self.config.auto_scan_on_startup = self.auto_scan_var.get()
        save_config(self.config)


# ---------------------------------------------------------------------------
# 5. About Panel
# ---------------------------------------------------------------------------

class AboutPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)

        PageHeader(self, "About", "Application information, version details, and safety principles.").grid(
            row=0, column=0, padx=18, pady=(20, 12), sticky="ew")

        # Identity Card
        card = SectionCard(self)
        card.grid(row=1, column=0, padx=18, pady=5, sticky="ew")
        ctk.CTkLabel(card, text="Spotify RAM Optimizer", text_color=TEXT,
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(card, text="Version 1.0.0 (Windows Desktop Release)", text_color=ACCENT,
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=20)
        ctk.CTkLabel(card, text="Designed and developed by Icey", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20, pady=(2, 0))
        ctk.CTkLabel(
            card,
            text="A clean, non-invasive Windows desktop utility designed to reduce Spotify's background memory "
                 "footprint safely. Every optimization is idempotent, verified, and completely reversible.",
            text_color=MUTED, justify="left", wraplength=680, font=ctk.CTkFont(size=12)
        ).pack(anchor="w", padx=20, pady=(10, 16))

        # Architecture & Safety Card
        arch = SectionCard(self)
        arch.grid(row=2, column=0, padx=18, pady=10, sticky="ew")
        ctk.CTkLabel(arch, text="Safety Architecture", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=20, pady=(14, 6))

        points = [
            "Never modifies or patches Spotify installation binaries.",
            "Never deletes user playlists, downloads, cookies, or account logins.",
            "Operates entirely under standard Windows user permissions (no Administrator access required).",
            "Creates an atomic timestamped backup prior to any preference or registry change.",
            "Targeted cache cleanup selectively frees temporary HTTP and compiled JS caches."
        ]
        for pt in points:
            ctk.CTkLabel(arch, text=f"✓  {pt}", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=24, pady=2)
        ctk.CTkLabel(arch, text="", height=8).pack()

        # Folders & Docs Card
        links = SectionCard(self)
        links.grid(row=3, column=0, padx=18, pady=5, sticky="ew")
        ctk.CTkLabel(links, text="Quick Access & Documentation", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=20, pady=(14, 8))

        btn_bar = ctk.CTkFrame(links, fg_color="transparent")
        btn_bar.pack(anchor="w", padx=20, pady=(0, 16))

        ctk.CTkButton(
            btn_bar, text="Open Documentation", command=self._open_docs,
            width=150, height=32, fg_color=SURFACE_RAISED, hover_color="#27303B"
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_bar, text="Open Backups Folder", command=self._open_backups,
            width=150, height=32, fg_color=SURFACE_RAISED, hover_color="#27303B"
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_bar, text="Open Logs Folder", command=self._open_logs,
            width=150, height=32, fg_color=SURFACE_RAISED, hover_color="#27303B"
        ).pack(side="left", padx=8)

    def _open_docs(self) -> None:
        readme = Path(__file__).resolve().parent.parent.parent / "README.md"
        if readme.exists():
            os.startfile(str(readme))
        else:
            messagebox.showinfo("Documentation", "Documentation is located in the application README.md")

    def _open_backups(self) -> None:
        p = Path(os.environ.get("APPDATA", ".")) / "SpotifyOptimizer" / "backups"
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))

    def _open_logs(self) -> None:
        p = Path(os.environ.get("APPDATA", ".")) / "SpotifyOptimizer" / "logs"
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))
