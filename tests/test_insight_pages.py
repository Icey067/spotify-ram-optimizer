"""
GUI tests for the Diagnostics and Privacy Center pages.

The panels are pure presentation: these tests hand them a report or a context
dictionary and assert what is displayed.  No health check is executed, no file
is cleared and no backup is restored.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.diagnostics import Finding, HealthReport, Severity
from src.gui.app import App


@pytest.fixture
def app_instance():
    app = App()
    app.update()
    yield app
    try:
        app.quit()
        app.destroy()
    except Exception:
        pass


def _labels(widget) -> list[str]:
    found: list[str] = []

    def walk(node):
        for child in node.winfo_children():
            if child.__class__.__name__ == "CTkLabel":
                try:
                    found.append(str(child.cget("text")))
                except Exception:
                    pass
            walk(child)

    walk(widget)
    return found


class TestDiagnosticsPage:
    def test_page_is_a_navigation_destination(self, app_instance):
        assert app_instance.show_page("Diagnostics") is True
        app_instance.update()
        assert app_instance.current_page == "Diagnostics"
        assert app_instance._page_title.cget("text") == "Diagnostics"

    def test_empty_state_explains_the_engine(self, app_instance):
        panel = app_instance.diagnostics_panel
        app_instance.update()
        assert panel.cards["checks"].value.cget("text") == "0"
        texts = _labels(panel.findings_host)
        assert any("No diagnostic report yet" in text for text in texts)
        assert panel.export_button.cget("state") == "disabled"

    def test_report_renders_counts_groups_and_evidence(self, app_instance):
        panel = app_instance.diagnostics_panel
        report = HealthReport(
            generated_at="2026-01-02T09:30:00",
            status="Needs attention",
            findings=[
                Finding("Memory usage", "Working set is high", Severity.HIGH,
                        "2100 MB across 7 processes", "Possible slowdown",
                        "Restart Spotify"),
                Finding("Cache", "Cache is large", Severity.MEDIUM,
                        "3.1 GB", "Slower start", "Review the cache limit"),
                Finding("Preferences", "Hardware acceleration enabled",
                        Severity.INFO, "true", "Default behaviour",
                        "No action required"),
            ],
        )
        panel.set_report(report, checks=2)
        app_instance.update()

        assert panel.cards["checks"].value.cget("text") == "2"
        assert panel.cards["critical"].value.cget("text") == "1"
        assert panel.cards["warning"].value.cget("text") == "1"
        assert panel.cards["info"].value.cget("text") == "1"
        assert "2026-01-02T09:30:00" in panel.last_check.cget("text")
        assert panel.export_button.cget("state") == "normal"

        texts = _labels(panel.findings_host)
        assert any("MEMORY USAGE" in text for text in texts)
        assert any("CACHE" in text for text in texts)
        assert any("Working set is high" in text for text in texts)

    def test_findings_expand_and_collapse(self, app_instance):
        panel = app_instance.diagnostics_panel
        panel.set_report(HealthReport(
            generated_at="now", status="Needs attention",
            findings=[Finding("Cache", "Cache is large", Severity.MEDIUM,
                              "3.1 GB", "Slower start", "Review the cache limit")],
        ), checks=1)
        app_instance.update()

        row = panel._finding_rows[0]
        assert row["expanded"] is False
        panel.toggle_finding(0)
        app_instance.update()
        assert row["expanded"] is True
        assert row["button"].cget("text") == "Hide details"
        assert any("3.1 GB" in text for text in _labels(row["details"]))
        panel.toggle_finding(0)
        app_instance.update()
        assert row["expanded"] is False

    def test_no_findings_reports_healthy_without_alarm(self, app_instance):
        panel = app_instance.diagnostics_panel
        panel.set_report(HealthReport(generated_at="now", status="Healthy"), checks=1)
        app_instance.update()
        assert panel.cards["critical"].value.cget("text") == "0"
        texts = _labels(panel.findings_host)
        assert any("No findings" in text for text in texts)

    def test_export_callback_is_wired(self, app_instance):
        calls: list[bool] = []
        panel = app_instance.diagnostics_panel
        panel._on_export = lambda: calls.append(True)
        panel.set_report(HealthReport(generated_at="now", status="Healthy"), checks=1)
        panel.export_report()
        assert calls == [True]

    def test_report_does_not_apply_modifications(self, app_instance):
        """Rendering a finding with an automated_fix must never execute it."""
        panel = app_instance.diagnostics_panel
        panel.set_report(HealthReport(
            generated_at="now", status="Needs attention",
            findings=[Finding("Cache", "Cache is large", Severity.MEDIUM,
                              "3.1 GB", "Slower start", "Clear cache", "cache.browser")],
        ), checks=1)
        app_instance.update()
        buttons = []

        def walk(node):
            for child in node.winfo_children():
                if child.__class__.__name__ == "CTkButton":
                    buttons.append(str(child.cget("text")))
                walk(child)

        walk(panel.findings_host)
        assert not any("apply" in text.lower() or "fix" in text.lower()
                       for text in buttons)


class TestPrivacyCenterPage:
    CONTEXT = {
        "config": r"C:\Users\alice\AppData\Roaming\SpotifyOptimizer\config.json",
        "backups": r"C:\Users\alice\AppData\Roaming\SpotifyOptimizer\backups",
        "logs": r"C:\Users\alice\AppData\Roaming\SpotifyOptimizer\logs",
        "history": r"C:\Users\alice\AppData\Roaming\SpotifyOptimizer\history.db",
        "read_files": [
            r"C:\Users\alice\AppData\Roaming\Spotify\prefs",
            r"C:\Users\alice\AppData\Roaming\Spotify\Data",
        ],
        "write_files": [
            r"C:\Users\alice\AppData\Roaming\Spotify\prefs (only when you apply)",
        ],
        "registry_locations": [
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run — read on scan",
        ],
        "retention": {"history_days": 90, "backup_keep": 0, "log_days": 14},
        "statistics": {"samples": 12, "sessions": 2, "backups": 3, "log_files": 4},
    }

    def test_page_is_a_navigation_destination(self, app_instance):
        assert app_instance.show_page("Privacy") is True
        app_instance.update()
        assert app_instance.current_page == "Privacy"
        assert app_instance._page_title.cget("text") == "Privacy Center"

    def test_locations_are_rendered_and_redacted(self, app_instance):
        panel = app_instance.privacy_panel
        panel.set_context(self.CONTEXT)
        app_instance.update()

        for key in ("config", "backups", "logs", "history"):
            text = panel.location_labels[key].cget("text")
            assert text.startswith("%USERPROFILE%"), f"{key} was not redacted"
        assert "alice" not in " ".join(
            label.cget("text") for label in panel.location_labels.values()
        )

    def test_read_write_and_registry_lists(self, app_instance):
        panel = app_instance.privacy_panel
        panel.set_context(self.CONTEXT)
        app_instance.update()

        assert "%USERPROFILE%" in panel.read_text.cget("text")
        assert "only when you apply" in panel.write_text.cget("text")
        assert "CurrentVersion\\Run" in panel.registry_text.cget("text")

    def test_retention_and_statistics(self, app_instance):
        panel = app_instance.privacy_panel
        panel.set_context(self.CONTEXT)
        app_instance.update()

        retention = panel.retention_text.cget("text")
        assert "90 day(s)" in retention
        assert "All kept" in retention
        assert "14 day(s)" in retention
        stats = panel.local_data_text.cget("text")
        assert "12 performance sample(s)" in stats
        assert "3 backup snapshot(s)" in stats

    def test_controls_call_the_app_callbacks(self, app_instance):
        calls: list[str] = []
        panel = app_instance.privacy_panel
        panel._on_clear_logs = lambda: calls.append("logs")
        panel._on_clear_history = lambda: calls.append("history")
        panel._on_manage_backups = lambda: calls.append("backups")
        panel._on_export_report = lambda: calls.append("report")

        panel.clear_logs()
        panel.clear_history()
        panel.manage_backups()
        panel.export_report()
        assert calls == ["logs", "history", "backups", "report"]

    def test_context_refresh_updates_the_page(self, app_instance):
        panel = app_instance.privacy_panel
        panel.set_context(self.CONTEXT)
        updated = dict(self.CONTEXT)
        updated["statistics"] = {"samples": 0, "sessions": 0, "backups": 0,
                                 "log_files": 0}
        panel.set_context(updated)
        app_instance.update()
        assert "0 performance sample(s)" in panel.local_data_text.cget("text")
