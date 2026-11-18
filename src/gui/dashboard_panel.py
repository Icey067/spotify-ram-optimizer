"""Dashboard: a truthful overview of the Spotify environment and resources."""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from .components import MemoryChart, MetricCard, SectionCard, StatusPill
from .theme import (
    ACCENT, ACCENT_HOVER, ERROR, MUTED, SUBTLE, SUCCESS, SURFACE_RAISED,
    TEXT, WARNING,
)

SEVERITY_COLORS = {
    "high": ERROR,
    "medium": WARNING,
    "low": MUTED,
    "info": SUBTLE,
}


class DashboardPanel(ctk.CTkScrollableFrame):
    def __init__(
        self,
        master,
        on_scan: Callable,
        on_run: Callable,
        on_restore: Callable,
        on_health: Optional[Callable] = None,
        on_preview: Optional[Callable] = None,
        on_export_health: Optional[Callable] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_scan = on_scan
        self._on_run = on_run
        self._on_restore = on_restore
        self._on_health = on_health
        self._on_preview = on_preview
        self._on_export_health = on_export_health
        self._info: dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="metrics")
        hero = ctk.CTkFrame(self, fg_color="transparent")
        hero.grid(row=0, column=0, columnspan=4, sticky="ew", padx=18, pady=(20, 14))
        hero.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hero, text="Your Spotify, Optimized.", text_color=TEXT,
                     font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold")).grid(
                         row=0, column=0, sticky="w")
        ctk.CTkLabel(hero,
                     text="Measure first, understand second, optimize third — and restore any time.",
                     text_color=MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=13)).grid(
                         row=1, column=0, sticky="w", pady=(3, 0))
        self.status = StatusPill(hero, "Scanning Spotify")
        self.status.grid(row=0, column=1, rowspan=2, sticky="e")

        self.memory_card = MetricCard(self, "Spotify memory usage", "—",
                                      "Mean working set across Spotify processes", "◌")
        self.process_card = MetricCard(self, "Active processes", "—",
                                       "Spotify and helper processes", "□")
        self.install_card = MetricCard(self, "Installation", "Scanning",
                                       "Checking available Spotify installations", "◇")
        self.optimization_card = MetricCard(self, "Health status", "Not checked",
                                            "Run a health check for findings", "✓")
        for column, card in enumerate((self.memory_card, self.process_card,
                                       self.install_card, self.optimization_card)):
            card.grid(row=1, column=column,
                      padx=(18 if column == 0 else 6, 18 if column == 3 else 6),
                      pady=4, sticky="ew")

        self.chart = MemoryChart(self)
        self.chart.grid(row=2, column=0, columnspan=2, padx=(18, 6), pady=(14, 6),
                        sticky="nsew")

        actions = SectionCard(self)
        actions.grid(row=2, column=2, columnspan=2, padx=(6, 18), pady=(14, 6), sticky="nsew")
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(actions, text="QUICK ACTIONS", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        ctk.CTkLabel(actions, text="Review, then apply", text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight="bold")).grid(
                         row=1, column=0, padx=16, sticky="w")
        ctk.CTkLabel(actions,
                     text="Preview shows exactly which files, registry values and cache "
                          "folders will change before anything is touched.",
                     text_color=MUTED, justify="left", wraplength=340,
                     font=ctk.CTkFont(size=11)).grid(
                         row=2, column=0, padx=16, pady=(3, 12), sticky="w")

        self._btn_run = ctk.CTkButton(actions, text="Optimize Spotify", command=self._on_run,
                                      height=40, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                      text_color="#08120C",
                                      font=ctk.CTkFont(size=13, weight="bold"))
        self._btn_run.grid(row=3, column=0, padx=16, pady=4, sticky="ew")
        self._btn_preview = ctk.CTkButton(actions, text="Preview changes",
                                          command=self._on_preview or self._on_run,
                                          height=33, fg_color=SURFACE_RAISED,
                                          hover_color="#333E4C", text_color=TEXT)
        self._btn_preview.grid(row=4, column=0, padx=16, pady=(5, 4), sticky="ew")
        self._btn_health = ctk.CTkButton(actions, text="Run health check",
                                         command=self._on_health or self._on_scan,
                                         height=33, fg_color=SURFACE_RAISED,
                                         hover_color="#333E4C", text_color=TEXT)
        self._btn_health.grid(row=5, column=0, padx=16, pady=4, sticky="ew")
        self._btn_restore = ctk.CTkButton(actions, text="Restore previous settings",
                                          command=self._on_restore, height=33,
                                          fg_color="#27303B", hover_color="#333E4C",
                                          text_color=TEXT)
        self._btn_restore.grid(row=6, column=0, padx=16, pady=(5, 14), sticky="ew")

        install = SectionCard(self)
        install.grid(row=3, column=0, columnspan=2, padx=(18, 6), pady=(8, 20), sticky="ew")
        install.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(install, text="SPOTIFY INSTALLATION", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")
        self._details: dict[str, ctk.CTkLabel] = {}
        for row, key in enumerate(("Install Type", "Version", "Spicetify", "Process",
                                   "Startup"), start=1):
            ctk.CTkLabel(install, text=key, text_color=SUBTLE,
                         font=ctk.CTkFont(size=11)).grid(
                             row=row, column=0, padx=16, pady=3, sticky="w")
            value = ctk.CTkLabel(install, text="—", text_color=TEXT,
                                 font=ctk.CTkFont(size=11, weight="bold"))
            value.grid(row=row, column=1, padx=16, pady=3, sticky="e")
            self._details[key] = value
        ctk.CTkButton(install, text="Scan Spotify", command=self._on_scan, width=110,
                      height=30, fg_color="#27303B", hover_color="#333E4C").grid(
                          row=6, column=0, columnspan=2, padx=16, pady=(10, 14), sticky="ew")

        self._health_card = SectionCard(self)
        self._health_card.grid(row=3, column=2, columnspan=2, padx=(6, 18),
                               pady=(8, 20), sticky="nsew")
        self._health_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self._health_card, text="LATEST HEALTH CHECK", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(14, 4), sticky="w")
        self._health_status = ctk.CTkLabel(self._health_card, text="Not run yet",
                                           text_color=TEXT,
                                           font=ctk.CTkFont(size=16, weight="bold"))
        self._health_status.grid(row=1, column=0, padx=16, sticky="w")
        self._health_body = ctk.CTkLabel(
            self._health_card,
            text="A health check inspects installation, processes, preferences, cache, "
                 "startup entries and backup protection. It never changes anything.",
            text_color=MUTED, justify="left", wraplength=360,
            font=ctk.CTkFont(size=11))
        self._health_body.grid(row=2, column=0, padx=16, pady=(3, 8), sticky="w")
        ctk.CTkButton(
            self._health_card, text="Export redacted report", width=170, height=28,
            command=self._on_export_health or (lambda: None),
            fg_color=SURFACE_RAISED, hover_color="#333E4C",
            state="normal" if self._on_export_health else "disabled",
        ).grid(row=3, column=0, padx=16, pady=(0, 14), sticky="w")

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def update_info(self, info: dict[str, str]) -> None:
        self._info.update(info)
        for key, label in self._details.items():
            label.configure(text=info.get(key, self._info.get(key, "—")))
        install_type = info.get("Install Type", "")
        if install_type == "Not Found":
            self.install_card.set("Not found", "Run Scan after installing Spotify", ERROR)
            self.status.set("Spotify not found", ERROR)
        elif install_type:
            self.install_card.set("Detected", f"{install_type} installation", ACCENT)
            self.status.set("Spotify detected", ACCENT)
        if "Process" in info:
            self._details["Process"].configure(text=info["Process"])

    def update_snapshot(self, memory_mb: float, process_count: int,
                        history: list[float], cpu_percent: float = 0.0) -> None:
        self.memory_card.set(
            f"{memory_mb:.1f} MB" if process_count else "Not running",
            "Mean working set" if process_count else "Spotify is closed",
        )
        self.process_card.set(
            str(process_count),
            "Spotify and helper processes" if process_count
            else "No Spotify processes detected",
        )
        self.chart.set_values(history)

    def update_memory(self, mb: float) -> None:
        self.memory_card.set(f"{mb:.1f} MB" if mb else "Not running")

    def set_health(self, report) -> None:
        """Render a :class:`HealthReport` without applying anything."""
        if report is None:
            return
        counts = report.counts
        if counts["high"]:
            color = ERROR
        elif counts["medium"]:
            color = WARNING
        elif counts["low"]:
            color = MUTED
        else:
            color = SUCCESS
        self._health_status.configure(text=report.status, text_color=color)
        self.optimization_card.set(report.status, report.summary_text(), color)

        lines: list[str] = []
        for finding in report.findings[:4]:
            lines.append(f"• [{finding.severity.value}] {finding.observation}")
        if not lines:
            lines.append("No findings. Everything checked looks normal.")
        elif len(report.findings) > 4:
            lines.append(f"… and {len(report.findings) - 4} more finding(s).")
        self._health_body.configure(text="\n".join(lines))

    def show_message(self, text: str, kind: str = "info") -> None:
        color = ACCENT if kind == "success" else ERROR if kind == "error" else MUTED
        self.optimization_card.set(
            "Complete" if kind == "success" else "Attention", text, color
        )

    def set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self._btn_run, self._btn_restore, self._btn_preview,
                       self._btn_health):
            try:
                button.configure(state=state)
            except Exception:
                pass
