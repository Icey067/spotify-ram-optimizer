"""
System pages that surface the evidence the core already collects:

  - ProcessesPanel      Spotify process tree (live, read-only)
  - StartupPanel        Windows startup entries (backup-first toggles)
  - InstallationPanel   Detection, paths, sizes and compatibility notes

Every panel renders data handed to it by :class:`src.gui.app.App`; none of them
performs file, registry or process work on the Tk thread, and none of them
duplicates core logic.
"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from src.core.app_paths import redact_path

from .components import MetricCard, PageHeader, SectionCard
from .theme import (
    ACCENT, BORDER, ERROR, MUTED, SUBTLE, SUCCESS, SURFACE, SURFACE_RAISED,
    TEXT, WARNING,
)


def format_bytes(value: int) -> str:
    """Human-readable size for byte counts coming from the core."""
    size = float(max(0, int(value)))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


# ---------------------------------------------------------------------------
# 1. Processes
# ---------------------------------------------------------------------------

class ProcessesPanel(ctk.CTkScrollableFrame):
    """Read-only table of the Spotify process tree."""

    COLUMNS = ("PID", "PROCESS", "MEMORY", "CPU", "STATUS", "STARTED")

    def __init__(self, master, on_refresh: Callable, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_refresh = on_refresh
        self.grid_columnconfigure(0, weight=1)

        PageHeader(
            self, "Processes",
            "Every Spotify process on this machine, read from the OS on demand. "
            "Nothing here is ever terminated.",
            on_refresh,
        ).grid(row=0, column=0, padx=18, pady=(20, 14), sticky="ew")

        metrics = ctk.CTkFrame(self, fg_color="transparent")
        metrics.grid(row=1, column=0, padx=18, pady=(0, 6), sticky="ew")
        metrics.grid_columnconfigure((0, 1, 2), weight=1, uniform="proc")
        self.count_card = MetricCard(metrics, "Processes", "—", "Spotify executables running")
        self.memory_card = MetricCard(metrics, "Total RAM", "—", "Sum of working sets")
        self.cpu_card = MetricCard(metrics, "CPU", "—", "Sampled per process")
        for column, card in enumerate((self.count_card, self.memory_card, self.cpu_card)):
            card.grid(row=0, column=column,
                      padx=(0 if column == 0 else 6, 0 if column == 2 else 6),
                      sticky="ew")

        self.table = SectionCard(self)
        self.table.grid(row=2, column=0, padx=18, pady=(8, 20), sticky="ew")
        self.table.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.table, text="SPOTIFY PROCESS TREE", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(14, 6), sticky="w")

        # Header cells and data cells share one grid, so the columns cannot
        # drift away from their headings.
        self._rows = ctk.CTkFrame(self.table, fg_color="transparent")
        self._rows.grid(row=1, column=0, padx=8, pady=(0, 12), sticky="ew")
        self._rows.grid_columnconfigure(1, weight=1)

        self._header_widgets: list = []
        widths = (70, 320, 110, 80, 110, 170)
        for column, (title, width) in enumerate(zip(self.COLUMNS, widths)):
            label = ctk.CTkLabel(self._rows, text=title, text_color=SUBTLE, width=width,
                                 anchor="w", font=ctk.CTkFont(size=9, weight="bold"))
            label.grid(row=0, column=column,
                       padx=(8 if column == 0 else 6, 6), pady=(0, 6), sticky="w")
            self._header_widgets.append(label)

        self._empty = ctk.CTkLabel(
            self._rows,
            text="Spotify is not running. Start it and refresh to see its processes.",
            text_color=SUBTLE, font=ctk.CTkFont(size=11),
        )
        self._empty.grid(row=1, column=0, columnspan=6, padx=8, pady=10, sticky="w")

        self._note = ctk.CTkLabel(
            self.table,
            text="Parent/child links are shown only when the parent is itself a "
                 "Spotify process. Memory figures are the current working set.",
            text_color=SUBTLE, justify="left", wraplength=900,
            font=ctk.CTkFont(size=10),
        )
        self._note.grid(row=2, column=0, padx=16, pady=(0, 14), sticky="w")

    def set_rows(self, details: list, elapsed: float = 0.0) -> None:
        """Render a list of ``ProcessDetails`` supplied by the app."""
        for child in self._rows.winfo_children():
            if child is not self._empty and child not in self._header_widgets:
                child.destroy()

        rows = sorted(details, key=lambda item: item.memory_mb, reverse=True)
        if not rows:
            self.count_card.set("0", "Spotify is closed", MUTED)
            self.memory_card.set("—", "No working set to measure")
            self.cpu_card.set("—", "No processes to sample")
            self._empty.grid(row=1, column=0, columnspan=6, padx=8, pady=10, sticky="w")
            return

        self._empty.grid_remove()
        total_memory = sum(item.memory_mb for item in rows)
        total_cpu = sum(item.cpu_percent for item in rows)
        self.count_card.set(str(len(rows)), "Spotify executables running", ACCENT)
        self.memory_card.set(f"{total_memory:.1f} MB",
                             f"Across {len(rows)} process(es)")
        self.cpu_card.set(f"{total_cpu:.1f}%",
                          f"Sampled in {elapsed * 1000:.0f} ms" if elapsed else
                          "Sampled per process")

        for index, item in enumerate(rows, start=1):
            parent = getattr(item, "parent_pid", None)
            name_text = f"└  {item.name}" if parent else item.name
            ctk.CTkLabel(self._rows, text=str(item.pid), text_color=MUTED,
                         anchor="w", font=ctk.CTkFont(family="Consolas", size=11)).grid(
                             row=index, column=0, padx=(8, 6), pady=5, sticky="w")

            name_box = ctk.CTkFrame(self._rows, fg_color="transparent")
            name_box.grid(row=index, column=1, padx=6, pady=4, sticky="w")
            ctk.CTkLabel(name_box, text=name_text, text_color=TEXT, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
            if parent:
                ctk.CTkLabel(name_box, text=f"child of PID {parent}", text_color=SUBTLE,
                             anchor="w", font=ctk.CTkFont(size=9)).pack(anchor="w")

            ctk.CTkLabel(self._rows, text=f"{item.memory_mb:.1f} MB", text_color=TEXT,
                         anchor="w",
                         font=ctk.CTkFont(size=11)).grid(row=index, column=2, padx=6,
                                                         pady=5, sticky="w")
            ctk.CTkLabel(self._rows, text=f"{item.cpu_percent:.1f}%", text_color=MUTED,
                         anchor="w",
                         font=ctk.CTkFont(size=11)).grid(row=index, column=3, padx=6,
                                                         pady=5, sticky="w")
            status = str(getattr(item, "status", "") or "unknown")
            ctk.CTkLabel(self._rows, text=status, text_color=SUBTLE, anchor="w",
                         font=ctk.CTkFont(size=10)).grid(row=index, column=4, padx=6,
                                                         pady=5, sticky="w")
            started = (item.start_time_text()
                       if hasattr(item, "start_time_text") else "unknown")
            ctk.CTkLabel(self._rows, text=started, text_color=SUBTLE, anchor="w",
                         font=ctk.CTkFont(size=10)).grid(row=index, column=5, padx=6,
                                                         pady=5, sticky="w")

        if elapsed:
            self._note.configure(
                text=f"Snapshot taken in {elapsed * 1000:.0f} ms. Parent/child links are "
                     "shown only when the parent is itself a Spotify process."
            )


# ---------------------------------------------------------------------------
# 2. Startup entries
# ---------------------------------------------------------------------------

class StartupPanel(ctk.CTkScrollableFrame):
    """Windows startup entries with backup-first enable/disable controls."""

    def __init__(
        self,
        master,
        on_refresh: Callable,
        on_toggle: Optional[Callable[[str, bool], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_refresh = on_refresh
        self.on_toggle = on_toggle
        self.grid_columnconfigure(0, weight=1)

        PageHeader(
            self, "Startup",
            "What launches Spotify when you sign in. Changes are limited to HKCU "
            "and are backed up first.",
            on_refresh,
        ).grid(row=0, column=0, padx=18, pady=(20, 14), sticky="ew")

        self.summary = SectionCard(self)
        self.summary.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        self.summary.grid_columnconfigure(0, weight=1)
        self.summary_text = ctk.CTkLabel(
            self.summary, text="Reading startup entries…", text_color=MUTED,
            justify="left", wraplength=820, font=ctk.CTkFont(size=11),
        )
        self.summary_text.grid(row=0, column=0, padx=16, pady=14, sticky="w")

        self.listing = ctk.CTkFrame(self, fg_color="transparent")
        self.listing.grid(row=2, column=0, padx=18, pady=(0, 20), sticky="ew")
        self.listing.grid_columnconfigure(0, weight=1)

        self._entries: list = []
        self._render()

    # ------------------------------------------------------------------

    def set_entries(self, entries: list) -> None:
        self._entries = list(entries)
        self._render()

    def _render(self) -> None:
        for child in self.listing.winfo_children():
            child.destroy()

        entries = self._entries
        if not entries:
            empty = SectionCard(self.listing)
            empty.grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(empty, text="No Spotify startup entries found", text_color=TEXT,
                         font=ctk.CTkFont(size=15, weight="bold")).pack(
                             anchor="w", padx=16, pady=(14, 2))
            ctk.CTkLabel(
                empty,
                text="Spotify is not registered to start with Windows, which is the "
                     "default after a clean install. This page only lists entries it "
                     "can prove belong to Spotify.",
                text_color=MUTED, justify="left", wraplength=820,
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=16, pady=(0, 14))
            self.summary_text.configure(
                text="0 entries · HKCU\\...\\Run and the per-user Startup folder were read"
            )
            return

        managed = sum(1 for entry in entries if entry.safe_to_modify)
        active = sum(1 for entry in entries if entry.enabled)
        self.summary_text.configure(
            text=(f"{len(entries)} Spotify entr{'y' if len(entries) == 1 else 'ies'} · "
                  f"{active} enabled · {managed} changeable here · "
                  "Windows' own StartupApproved state is read-only")
        )

        for row, entry in enumerate(entries):
            card = SectionCard(self.listing)
            card.grid(row=row, column=0, pady=5, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            header = ctk.CTkFrame(card, fg_color="transparent")
            header.grid(row=0, column=0, padx=16, pady=(12, 0), sticky="w")
            ctk.CTkLabel(header, text=entry.name, text_color=TEXT,
                         font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")

            if not entry.safe_to_modify:
                badge_text, badge_color = "READ-ONLY", MUTED
            elif entry.enabled:
                badge_text, badge_color = "ENABLED", SUCCESS
            else:
                badge_text, badge_color = "DISABLED", WARNING
            ctk.CTkLabel(header, text=badge_text, text_color=badge_color,
                         fg_color=SURFACE_RAISED, corner_radius=8, padx=8, pady=2,
                         font=ctk.CTkFont(size=9, weight="bold")).pack(side="left", padx=8)

            ctk.CTkLabel(card, text=entry.location, text_color=SUBTLE,
                         font=ctk.CTkFont(size=10)).grid(
                             row=1, column=0, padx=16, pady=(2, 0), sticky="w")
            ctk.CTkLabel(card, text=entry.command, text_color=MUTED, justify="left",
                         wraplength=700,
                         font=ctk.CTkFont(family="Consolas", size=10)).grid(
                             row=2, column=0, padx=16, pady=(2, 0), sticky="w")
            if entry.note:
                ctk.CTkLabel(card, text=entry.note, text_color=WARNING, justify="left",
                             wraplength=700, font=ctk.CTkFont(size=10)).grid(
                                 row=3, column=0, padx=16, pady=(2, 0), sticky="w")

            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.grid(row=0, column=1, rowspan=4, padx=14, pady=10, sticky="e")
            if self.on_toggle and entry.safe_to_modify:
                if entry.enabled:
                    ctk.CTkButton(
                        buttons, text="Disable", width=88, height=28,
                        command=lambda name=entry.name: self.on_toggle(name, False),
                        fg_color="#3A2226", hover_color="#4A2A2F",
                        text_color="#F0B4B4",
                    ).pack()
                else:
                    ctk.CTkButton(
                        buttons, text="Enable", width=88, height=28,
                        command=lambda name=entry.name: self.on_toggle(name, True),
                        fg_color=SURFACE_RAISED, hover_color="#333E4C",
                    ).pack()

            footer = ctk.CTkLabel(card, text="", text_color=SUBTLE,
                                  font=ctk.CTkFont(size=10))
            footer.grid(row=4, column=0, padx=16, pady=(2, 12), sticky="w")
            footer.configure(
                text=("A hash-verified snapshot is written before this entry changes."
                      if entry.safe_to_modify else
                      "Not on the allow-list: listed for transparency, never modified.")
            )


# ---------------------------------------------------------------------------
# 3. Installation
# ---------------------------------------------------------------------------

class InstallationPanel(ctk.CTkScrollableFrame):
    """Detection results, real paths, sizes and compatibility notes."""

    INSTALL_ROWS = (
        ("type", "Installation type"),
        ("version", "Spotify version"),
        ("exe", "Executable"),
        ("data", "Data folder"),
        ("prefs", "Preferences file"),
        ("cache", "Cache folder"),
        ("store", "Store package"),
        ("windows", "Windows"),
        ("architecture", "Architecture"),
    )
    STATE_ROWS = (
        ("prefs_size", "Preferences size"),
        ("prefs_state", "Preferences access"),
        ("cache_size", "Cache total"),
        ("cache_disposable", "Disposable cache"),
        ("cache_dirs", "Allow-listed cache folders"),
    )
    SPICETIFY_ROWS = (
        ("sp_status", "Status"),
        ("sp_version", "Version"),
        ("sp_config", "Config file"),
        ("sp_extensions", "Extensions"),
        ("sp_apps", "Custom apps"),
    )

    def __init__(
        self,
        master,
        on_refresh: Callable,
        on_scan: Optional[Callable] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_refresh = on_refresh
        self.grid_columnconfigure(0, weight=1)

        PageHeader(
            self, "Installation",
            "What was detected, where it lives, and what this build can and cannot "
            "change.",
            on_refresh,
        ).grid(row=0, column=0, padx=18, pady=(20, 14), sticky="ew")

        self.values: dict[str, ctk.CTkLabel] = {}
        row = 1
        row = self._section(row, "Spotify", self.INSTALL_ROWS)
        row = self._section(row, "Files and cache", self.STATE_ROWS)
        row = self._section(row, "Spicetify", self.SPICETIFY_ROWS)

        self.notes_card = SectionCard(self)
        self.notes_card.grid(row=row, column=0, padx=18, pady=(6, 20), sticky="ew")
        self.notes_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.notes_card, text="COMPATIBILITY NOTES", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(14, 4), sticky="w")
        self.notes = ctk.CTkLabel(
            self.notes_card,
            text="Scan Spotify to read the environment.",
            text_color=MUTED, justify="left", wraplength=880,
            font=ctk.CTkFont(size=11),
        )
        self.notes.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="w")
        if on_scan:
            ctk.CTkButton(
                self.notes_card, text="Rescan installation", width=150, height=30,
                command=on_scan, fg_color=SURFACE_RAISED, hover_color="#333E4C",
            ).grid(row=2, column=0, padx=16, pady=(0, 14), sticky="w")

    def _section(self, row: int, title: str, rows: tuple) -> int:
        card = SectionCard(self)
        card.grid(row=row, column=0, padx=18, pady=(0, 10), sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=title.upper(), text_color=ACCENT,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(
                         row=0, column=0, columnspan=2, padx=16, pady=(14, 6), sticky="w")
        for index, (key, label) in enumerate(rows, start=1):
            ctk.CTkLabel(card, text=label, text_color=MUTED,
                         font=ctk.CTkFont(size=11)).grid(
                             row=index, column=0, padx=16, pady=3, sticky="w")
            value = ctk.CTkLabel(card, text="—", text_color=TEXT, justify="left",
                                 anchor="e", wraplength=560,
                                 font=ctk.CTkFont(size=11))
            value.grid(row=index, column=1, padx=16, pady=3, sticky="e")
            self.values[key] = value
        return row + 1

    # ------------------------------------------------------------------

    def set_report(self, report: dict) -> None:
        if not report:
            return

        def path(key: str) -> str:
            raw = report.get(key) or ""
            return redact_path(raw) if raw else "Not detected"

        found = report.get("install_type") not in (None, "", "Not Found")
        self.values["type"].configure(
            text=report.get("install_type") or "Unknown",
            text_color=ACCENT if found else ERROR,
        )
        self.values["version"].configure(text=report.get("version") or "Unknown")
        self.values["exe"].configure(text=path("exe_path"))
        self.values["data"].configure(text=path("data_path"))
        self.values["prefs"].configure(text=path("prefs_path"))
        self.values["cache"].configure(text=path("cache_path"))
        self.values["store"].configure(
            text=path("store_package") if report.get("store_package")
            else "Not a Store installation"
        )

        windows = report.get("windows") or "Unknown"
        build = report.get("windows_build") or 0
        edition = report.get("windows_edition") or ""
        self.values["windows"].configure(
            text=" ".join(part for part in (windows, edition, f"build {build}" if build else "")
                          if part)
        )
        self.values["architecture"].configure(text=report.get("architecture") or "Unknown")

        self.values["prefs_size"].configure(
            text=format_bytes(report.get("prefs_bytes") or 0)
            if report.get("prefs_path") else "No preferences file"
        )
        readable = report.get("prefs_readable")
        writable = report.get("prefs_writable")
        if readable and writable:
            access, color = "Readable and writable", SUCCESS
        elif readable:
            access, color = "Readable, not writable", WARNING
        else:
            access, color = "Not readable", ERROR
        self.values["prefs_state"].configure(text=access, text_color=color)

        self.values["cache_size"].configure(
            text=format_bytes(report.get("cache_bytes") or 0)
            if report.get("cache_path") else "No cache folder"
        )
        self.values["cache_disposable"].configure(
            text=format_bytes(report.get("cache_disposable_bytes") or 0)
        )
        self.values["cache_dirs"].configure(text=str(report.get("cache_dirs") or 0))

        spicetify = report.get("spicetify") or {}
        installed = bool(spicetify.get("installed"))
        self.values["sp_status"].configure(
            text="Installed" if installed else "Not installed",
            text_color=SUCCESS if installed else MUTED,
        )
        self.values["sp_version"].configure(text=spicetify.get("version") or "—")
        config = spicetify.get("config") or ""
        self.values["sp_config"].configure(
            text=redact_path(config) if config else "—"
        )
        extensions = spicetify.get("extensions") or []
        apps = spicetify.get("custom_apps") or []
        self.values["sp_extensions"].configure(
            text=f"{len(extensions)} detected" if extensions else "None"
        )
        self.values["sp_apps"].configure(
            text=f"{len(apps)} detected" if apps else "None"
        )

        notes = list(report.get("notes") or [])
        if not found:
            notes.insert(0, "Spotify was not detected on this machine.")
        if not notes:
            notes.append("No compatibility limitations were detected.")
        self.notes.configure(text="\n".join(f"• {note}" for note in notes))
