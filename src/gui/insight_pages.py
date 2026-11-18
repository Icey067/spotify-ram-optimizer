"""
Diagnostics and Privacy Center pages.

Both panels are pure presentation: they never read a file, touch the registry
or apply a change.  The app hands them a report or a context dictionary built
from core services, which keeps the GUI/core separation intact and makes the
pages testable without a real Spotify installation.
"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from src.core.app_paths import redact_path

from .components import MetricCard, PageHeader, SectionCard
from .theme import (
    ACCENT, ACCENT_HOVER, BORDER, ERROR, MUTED, SUBTLE, SUCCESS,
    SURFACE_RAISED, TEXT, WARNING,
)

SEVERITY_COLORS = {
    "high": ERROR,
    "medium": WARNING,
    "low": MUTED,
    "info": SUBTLE,
}
SEVERITY_LABELS = {
    "high": "CRITICAL",
    "medium": "WARNING",
    "low": "OBSERVATION",
    "info": "INFO",
}


def _format_retention(days: int, unlimited_label: str = "Unlimited") -> str:
    return unlimited_label if not days or days <= 0 else f"{days} day(s)"


# ---------------------------------------------------------------------------
# 1. Diagnostics
# ---------------------------------------------------------------------------

class DiagnosticsPanel(ctk.CTkScrollableFrame):
    """The full health report, grouped by category and expandable per finding."""

    def __init__(
        self,
        master,
        get_report: Callable[[], tuple],
        on_run_health: Optional[Callable] = None,
        on_export: Optional[Callable] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._get_report = get_report
        self._on_run_health = on_run_health
        self._on_export = on_export
        self._report = None
        self._checks = 0
        self._finding_rows: list[dict] = []
        self.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="diagnostics")

        PageHeader(
            self, "Diagnostics",
            "Evidence-backed findings from the health-check engine. "
            "Nothing here changes Spotify.",
        ).grid(row=0, column=0, columnspan=5, padx=18, pady=(20, 10), sticky="ew")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, columnspan=5, padx=18, pady=(0, 10), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)

        self.status_note = ctk.CTkLabel(
            toolbar, text="No health check has run yet.",
            text_color=SUBTLE, font=ctk.CTkFont(size=11),
        )
        self.status_note.grid(row=0, column=0, sticky="w")

        self.run_button = ctk.CTkButton(
            toolbar, text="Run health check", width=140, height=32,
            command=self._run_health,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#08120C",
            font=ctk.CTkFont(size=12, weight="bold"),
            state="normal" if on_run_health else "disabled",
        )
        self.run_button.grid(row=0, column=1, padx=4)

        self.refresh_button = ctk.CTkButton(
            toolbar, text="Refresh", width=88, height=32, command=self.refresh,
            fg_color=SURFACE_RAISED, hover_color="#333E4C",
        )
        self.refresh_button.grid(row=0, column=2, padx=4)

        self.export_button = ctk.CTkButton(
            toolbar, text="Export report", width=120, height=32,
            command=self._export,
            fg_color=SURFACE_RAISED, hover_color="#333E4C",
            state="disabled",
        )
        self.export_button.grid(row=0, column=3, padx=(4, 0))

        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=2, column=0, columnspan=5, padx=18, pady=(0, 6), sticky="ew")
        cards.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="diagnostics")
        self.cards = {
            "checks": MetricCard(cards, "Health checks", "0", "This session"),
            "critical": MetricCard(cards, "Critical", "0", "High severity"),
            "warning": MetricCard(cards, "Warnings", "0", "Medium severity"),
            "low": MetricCard(cards, "Observations", "0", "Low severity"),
            "info": MetricCard(cards, "Informational", "0", "Context only"),
        }
        for column, card in enumerate(self.cards.values()):
            card.grid(row=0, column=column,
                      padx=(0 if column == 0 else 5, 0 if column == 4 else 5),
                      sticky="ew")

        self.last_check = ctk.CTkLabel(
            self, text="Last check: never", text_color=SUBTLE,
            font=ctk.CTkFont(size=11),
        )
        self.last_check.grid(row=3, column=0, columnspan=5, padx=20, pady=(2, 6),
                             sticky="w")

        self.findings_host = ctk.CTkFrame(self, fg_color="transparent")
        self.findings_host.grid(row=4, column=0, columnspan=5, padx=18,
                                pady=(0, 20), sticky="ew")
        self.findings_host.grid_columnconfigure(0, weight=1)
        self._render_empty()

    # -- public ---------------------------------------------------------

    def refresh(self) -> None:
        """Re-render from the app's current report (no new check is run)."""
        report, checks = (None, 0)
        if callable(self._get_report):
            try:
                report, checks = self._get_report()
            except Exception:
                report, checks = (None, 0)
        self.set_report(report, checks)

    def set_report(self, report, checks: int = 0) -> None:
        self._report = report
        self._checks = int(checks or 0)
        self.cards["checks"].set(str(self._checks), "This session")

        counts = report.counts if report is not None else {
            "high": 0, "medium": 0, "low": 0, "info": 0
        }
        self.cards["critical"].set(
            str(counts.get("high", 0)),
            "High severity" if counts.get("high") else "None found",
            ERROR if counts.get("high") else TEXT,
        )
        self.cards["warning"].set(
            str(counts.get("medium", 0)),
            "Medium severity" if counts.get("medium") else "None found",
            WARNING if counts.get("medium") else TEXT,
        )
        self.cards["low"].set(str(counts.get("low", 0)), "Low severity")
        self.cards["info"].set(str(counts.get("info", 0)), "Context only")

        if report is None:
            self.status_note.configure(text="No health check has run yet.")
            self.last_check.configure(text="Last check: never")
            self.export_button.configure(state="disabled")
            self._render_empty()
            return

        self.status_note.configure(
            text=f"{report.status} · {len(report.findings)} finding(s)",
            text_color=ERROR if counts.get("high") else
            WARNING if counts.get("medium") else SUCCESS,
        )
        self.last_check.configure(text=f"Last check: {report.generated_at}")
        self.export_button.configure(state="normal" if self._on_export else "disabled")
        self._render_findings(report)

    def set_running(self, running: bool) -> None:
        self.status_note.configure(
            text="Running health check…" if running else self.status_note.cget("text")
        )
        state = "disabled" if running else "normal"
        if self._on_run_health:
            self.run_button.configure(state=state)

    def toggle_finding(self, index: int) -> None:
        """Expand or collapse one finding's technical detail."""
        if not 0 <= index < len(self._finding_rows):
            return
        row = self._finding_rows[index]
        if row["expanded"]:
            row["details"].grid_remove()
            row["button"].configure(text="Details")
            row["expanded"] = False
        else:
            row["details"].grid()
            row["button"].configure(text="Hide details")
            row["expanded"] = True

    # -- internals ------------------------------------------------------

    def _run_health(self) -> None:
        if self._on_run_health:
            self._on_run_health()

    def export_report(self) -> None:
        """Ask the app to export the last report (redacted by the app)."""
        if self._on_export:
            self._on_export()

    def _export(self) -> None:
        self.export_report()

    def _clear_findings(self) -> None:
        for child in self.findings_host.winfo_children():
            child.destroy()
        self._finding_rows = []

    def _render_empty(self) -> None:
        self._clear_findings()
        empty = SectionCard(self.findings_host)
        empty.grid(row=0, column=0, sticky="ew")
        empty.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(empty, text="No diagnostic report yet", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(16, 2), sticky="w")
        ctk.CTkLabel(
            empty,
            text=("A health check inspects the installation, processes, preferences, "
                  "cache, startup configuration, Spicetify state and backup "
                  "protection. It never changes anything."),
            text_color=MUTED, justify="left", anchor="w", wraplength=640,
            font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, padx=16, pady=(0, 16), sticky="w")

    def _render_findings(self, report) -> None:
        self._clear_findings()
        if not report.findings:
            healthy = SectionCard(self.findings_host)
            healthy.grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(healthy, text="No findings",
                         text_color=SUCCESS,
                         font=ctk.CTkFont(size=15, weight="bold")).pack(
                             anchor="w", padx=16, pady=(14, 2))
            ctk.CTkLabel(healthy, text="Everything the health check inspects looks normal.",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).pack(
                             anchor="w", padx=16, pady=(0, 14))
            return

        grouped: dict[str, list] = {}
        for finding in report.findings:
            grouped.setdefault(finding.category, []).append(finding)

        row = 0
        for category, findings in grouped.items():
            section = SectionCard(self.findings_host)
            section.grid(row=row, column=0, pady=(0, 8), sticky="ew")
            section.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(section, text=category.upper(), text_color=ACCENT,
                         font=ctk.CTkFont(size=10, weight="bold")).grid(
                             row=0, column=0, padx=16, pady=(12, 4), sticky="w")

            for finding in findings:
                self._add_finding(section, finding)

            row += 1

    def _add_finding(self, section, finding) -> None:
        index = len(self._finding_rows)
        color = SEVERITY_COLORS.get(finding.severity.value, MUTED)
        card = ctk.CTkFrame(section, fg_color=SURFACE_RAISED, corner_radius=10)
        card.grid(row=index + 1, column=0, padx=12, pady=(0, 8), sticky="ew")
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text=SEVERITY_LABELS.get(finding.severity.value, "INFO"),
                     text_color=color, fg_color="#222A34", corner_radius=8,
                     padx=8, pady=2,
                     font=ctk.CTkFont(size=9, weight="bold")).grid(
                         row=0, column=0, padx=(12, 8), pady=(10, 0), sticky="w")
        ctk.CTkLabel(card, text=finding.observation, text_color=TEXT, justify="left",
                     anchor="w", wraplength=520,
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
                         row=0, column=1, padx=(0, 8), pady=(10, 0), sticky="w")

        button = ctk.CTkButton(card, text="Details", width=94, height=26,
                               fg_color="#27303B", hover_color="#333E4C",
                               command=lambda i=index: self.toggle_finding(i))
        button.grid(row=0, column=2, padx=10, pady=(8, 0), sticky="e")

        summary = ctk.CTkLabel(card, text=finding.recommendation, text_color=MUTED,
                               justify="left", anchor="w", wraplength=560,
                               font=ctk.CTkFont(size=11))
        summary.grid(row=1, column=0, columnspan=3, padx=12, pady=(4, 10), sticky="w")

        details = ctk.CTkFrame(card, fg_color="transparent")
        details.grid(row=2, column=0, columnspan=3, padx=12, pady=(0, 12), sticky="ew")
        details.grid_columnconfigure(1, weight=1)
        for row_index, (label, value) in enumerate((
            ("Evidence", finding.evidence),
            ("Impact", finding.impact),
            ("Recommendation", finding.recommendation),
        )):
            ctk.CTkLabel(details, text=label.upper(), text_color=SUBTLE,
                         font=ctk.CTkFont(size=9, weight="bold"), anchor="nw").grid(
                             row=row_index, column=0, padx=(0, 10), pady=3, sticky="nw")
            ctk.CTkLabel(details, text=value, text_color=MUTED, justify="left",
                         anchor="w", wraplength=520,
                         font=ctk.CTkFont(size=10)).grid(
                             row=row_index, column=1, pady=3, sticky="w")
        details.grid_remove()

        self._finding_rows.append(
            {"details": details, "button": button, "expanded": False}
        )


# ---------------------------------------------------------------------------
# 2. Privacy Center
# ---------------------------------------------------------------------------

class PrivacyCenterPanel(ctk.CTkScrollableFrame):
    """Where the application stores data, what it reads and how to clear it."""

    def __init__(
        self,
        master,
        get_context: Callable[[], dict],
        on_clear_logs: Optional[Callable] = None,
        on_clear_history: Optional[Callable] = None,
        on_manage_backups: Optional[Callable] = None,
        on_export_report: Optional[Callable] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._get_context = get_context
        self._on_clear_logs = on_clear_logs
        self._on_clear_history = on_clear_history
        self._on_manage_backups = on_manage_backups
        self._on_export_report = on_export_report
        self.grid_columnconfigure(0, weight=1)

        PageHeader(
            self, "Privacy Center",
            "Everything this application reads, changes and stores. All of it "
            "stays on this machine.",
            self.refresh,
        ).grid(row=0, column=0, padx=18, pady=(20, 12), sticky="ew")

        statement = SectionCard(self)
        statement.grid(row=1, column=0, padx=18, pady=(0, 8), sticky="ew")
        statement.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(statement, text="Local by design", text_color=TEXT,
                     font=ctk.CTkFont(size=16, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        ctk.CTkLabel(
            statement,
            text=("This application makes no network requests: no telemetry, no "
                  "analytics, no update checks and no crash reporting. Measurements, "
                  "logs and backups are written to your own user profile and are only "
                  "read again when you open the relevant page."),
            text_color=MUTED, justify="left", anchor="w", wraplength=640,
            font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")

        locations = self._card(2, "Storage locations")
        self.location_labels: dict[str, ctk.CTkLabel] = {}
        for key, label in (
            ("config", "Application configuration"),
            ("backups", "Backup directory"),
            ("logs", "Log directory"),
            ("history", "Performance database"),
        ):
            self.location_labels[key] = self._row(locations, label)

        reads = self._card(3, "Files read")
        self.read_text = self._body(reads)
        writes = self._card(4, "Files modified")
        self.write_text = self._body(writes)
        registry = self._card(5, "Registry locations accessed")
        self.registry_text = self._body(registry)

        retention = self._card(6, "Local data retention")
        self.retention_text = self._body(retention)
        self.local_data_text = ctk.CTkLabel(
            retention, text="", text_color=SUBTLE, justify="left", anchor="w",
            wraplength=640, font=ctk.CTkFont(size=10),
        )
        self.local_data_text.pack(anchor="w", padx=16, pady=(0, 14))

        controls = self._card(7, "Data controls")
        bar = ctk.CTkFrame(controls, fg_color="transparent")
        bar.pack(anchor="w", padx=16, pady=(0, 14))
        self.buttons: dict[str, ctk.CTkButton] = {}
        for key, text, command in (
            ("logs", "Clear logs", on_clear_logs),
            ("history", "Clear performance history", on_clear_history),
            ("backups", "Manage backups", on_manage_backups),
            ("report", "Export redacted report", on_export_report),
        ):
            handler = {
                "logs": self.clear_logs,
                "history": self.clear_history,
                "backups": self.manage_backups,
                "report": self.export_report,
            }[key]
            button = ctk.CTkButton(
                bar, text=text, width=150, height=30,
                command=handler,
                fg_color=SURFACE_RAISED, hover_color="#333E4C",
                state="normal" if command else "disabled",
            )
            button.pack(side="left", padx=(0, 8))
            self.buttons[key] = button

        self.refresh()

    # -- layout helpers -------------------------------------------------

    def _card(self, row: int, title: str) -> SectionCard:
        card = SectionCard(self)
        card.grid(row=row, column=0, padx=18, pady=(0, 8), sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title.upper(), text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).pack(
                         anchor="w", padx=16, pady=(12, 4))
        return card

    def _row(self, card: SectionCard, label: str) -> ctk.CTkLabel:
        frame = ctk.CTkFrame(card, fg_color="transparent")
        frame.pack(fill="x", padx=16, pady=3)
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text=label, text_color=SUBTLE, width=190, anchor="w",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        value = ctk.CTkLabel(frame, text="—", text_color=TEXT, anchor="e",
                             justify="right", wraplength=430,
                             font=ctk.CTkFont(family="Consolas", size=10))
        value.grid(row=0, column=1, padx=(10, 0), sticky="e")
        return value

    def _body(self, card: SectionCard) -> ctk.CTkLabel:
        body = ctk.CTkLabel(card, text="", text_color=MUTED, justify="left",
                            anchor="w", wraplength=640,
                            font=ctk.CTkFont(size=10))
        body.pack(anchor="w", fill="x", padx=16, pady=(0, 14))
        return body

    # -- public ---------------------------------------------------------

    def refresh(self) -> None:
        context: dict = {}
        if callable(self._get_context):
            try:
                context = self._get_context() or {}
            except Exception:
                context = {}
        self.set_context(context)

    # -- actions (the app owns the confirmation dialogs) -----------------

    def clear_logs(self) -> None:
        if self._on_clear_logs:
            self._on_clear_logs()

    def clear_history(self) -> None:
        if self._on_clear_history:
            self._on_clear_history()

    def manage_backups(self) -> None:
        if self._on_manage_backups:
            self._on_manage_backups()

    def export_report(self) -> None:
        if self._on_export_report:
            self._on_export_report()

    def set_context(self, context: dict) -> None:
        for key, label in self.location_labels.items():
            value = context.get(key)
            label.configure(text=redact_path(value) if value else "Not configured")

        self.read_text.configure(
            text=self._listing(context.get("read_files"), "No Spotify files are read.")
        )
        self.write_text.configure(
            text=self._listing(context.get("write_files"), "No files are written.")
        )
        self.registry_text.configure(
            text=self._listing(context.get("registry_locations"),
                               "No registry locations are accessed.")
        )

        retention = context.get("retention") or {}
        self.retention_text.configure(text="\n".join((
            f"Performance samples: {_format_retention(retention.get('history_days', 0))}",
            f"Backup snapshots: {_format_retention(retention.get('backup_keep', 0), 'All kept')}",
            f"Session logs: {_format_retention(retention.get('log_days', 0))}",
        )))

        statistics = context.get("statistics") or {}
        self.local_data_text.configure(text=(
            f"Current local state: {statistics.get('samples', 0)} performance sample(s), "
            f"{statistics.get('sessions', 0)} recorded session(s), "
            f"{statistics.get('backups', 0)} backup snapshot(s), "
            f"{statistics.get('log_files', 0)} log file(s)."
        ))

    @staticmethod
    def _listing(items, empty_text: str) -> str:
        values = [str(item) for item in (items or []) if item]
        if not values:
            return empty_text
        return "\n".join(f"• {redact_path(value)}" for value in values)
