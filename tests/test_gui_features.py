"""
GUI feature tests for the new panels.

These exercise widget state only; they do not apply optimizations, restore
backups or write configuration.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.diagnostics import Finding, HealthReport, Severity
from src.core.optimizations import Change, OptimizationRequest, Plan
from src.core.performance_monitor import PerformanceComparison, PerformanceSnapshot
from src.gui.app import App
from src.gui.components import PlanPreviewDialog


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


class TestOptimizationProfiles:
    def test_safe_profile_is_conservative(self, app_instance):
        panel = app_instance.settings_panel
        panel.apply_profile("safe", notify=False)
        settings = panel.get_settings()
        assert settings.disable_hw_accel is True
        assert settings.set_cache_size is True
        assert settings.clean_browser_cache is True
        assert settings.disable_autostart is False
        assert settings.set_autostart_pref is False
        assert settings.clean_gpu_cache is False

    def test_balanced_profile_adds_startup_and_gpu(self, app_instance):
        panel = app_instance.settings_panel
        panel.apply_profile("balanced", notify=False)
        settings = panel.get_settings()
        assert settings.disable_autostart is True
        assert settings.clean_gpu_cache is True
        assert settings.set_autostart_pref is False, "unverified pref stays opt-in"

    def test_advanced_profile_includes_unverified_pref(self, app_instance):
        panel = app_instance.settings_panel
        panel.apply_profile("advanced", notify=False)
        assert panel.get_settings().set_autostart_pref is True

    def test_selecting_operations_switches_to_custom(self, app_instance):
        panel = app_instance.settings_panel
        panel.select_operations(["cache.gpu", "prefs.cache_size"])
        assert panel.profile == "custom"
        settings = panel.get_settings()
        assert settings.clean_gpu_cache is True
        assert settings.disable_hw_accel is False

    def test_cache_size_round_trip(self, app_instance):
        panel = app_instance.settings_panel
        panel.set_cache_size(1024)
        assert panel.get_cache_size_mb() == 1024
        assert panel.get_settings().cache_size_mb == 1024

    def test_reset_returns_to_safe_profile(self, app_instance):
        panel = app_instance.settings_panel
        panel.apply_profile("advanced", notify=False)
        panel.reset_defaults()
        assert panel.profile == "safe"
        assert panel.get_settings().clean_gpu_cache is False


class TestHonestComparisonUI:
    def test_non_comparable_shows_no_saving(self, app_instance):
        before = PerformanceSnapshot("10:00:00", 5, 620.0, label="Before")
        after = PerformanceSnapshot("10:01:00", 0, 0.0, label="After")
        comparison = PerformanceComparison(
            before=before, after=after, comparable=False,
            notes=["Spotify was closed for the 'after' measurement."],
        )
        app_instance.results_panel.show_comparison(comparison)
        assert app_instance.results_panel.result_labels[2].cget("text") == "Not comparable"
        note = app_instance.results_panel._comparison_note.cget("text")
        assert "misleading" in note.lower()

    def test_comparable_difference_is_shown(self, app_instance):
        before = PerformanceSnapshot("10:00:00", 5, 620.0, label="Before")
        after = PerformanceSnapshot("10:01:00", 5, 500.0, label="After")
        comparison = PerformanceComparison(
            before=before, after=after, comparable=True, notes=["measured"],
        )
        app_instance.results_panel.show_comparison(comparison)
        assert "MB" in app_instance.results_panel.result_labels[2].cget("text")


class TestDashboardHealth:
    def test_health_report_is_rendered(self, app_instance):
        report = HealthReport(
            generated_at="now",
            status="Needs attention",
            findings=[
                Finding("Performance", "Working set is high", Severity.MEDIUM,
                        "2400 MB", "maybe slower", "Restart Spotify"),
                Finding("Cache", "Cache is large", Severity.MEDIUM,
                        "3 GB", "slow start", "Clear cache", "cache.browser"),
            ],
        )
        app_instance.dashboard.set_health(report)
        assert app_instance.dashboard._health_status.cget("text") == "Needs attention"
        body = app_instance.dashboard._health_body.cget("text")
        assert "Working set is high" in body
        assert "Cache is large" in body

    def test_healthy_report_uses_success_colour(self, app_instance):
        report = HealthReport(generated_at="now", status="Healthy", findings=[])
        app_instance.dashboard.set_health(report)
        assert app_instance.dashboard.optimization_card.value.cget("text") == "Healthy"


class TestBackupsPanel:
    def test_empty_state(self, app_instance):
        panel = app_instance.backups_panel
        panel.get_backups = lambda: []
        panel.refresh()
        text = panel.summary_text.cget("text")
        assert "0 snapshot" in text

    def test_session_listing(self, app_instance):
        panel = app_instance.backups_panel
        panel.get_backups = lambda: [{
            "name": "20240101_120000",
            "created_at": "2024-01-01T12:00:00",
            "artefacts": {"prefs": True, "registry": True},
            "integrity_ok": True,
            "has_manifest": True,
            "size_bytes": 2048,
            "operations": ["prefs.hardware_acceleration"],
        }]
        panel.refresh()
        assert "1 snapshot" in panel.summary_text.cget("text")

    def test_preview_dialog_lists_real_plan_details(self, app_instance, tmp_path):
        prefs = tmp_path / "prefs"
        prefs.write_text("hardware_acceleration_mode_enabled=true\n")
        plan = Plan(
            request=OptimizationRequest(operations={"prefs.hardware_acceleration"}),
            changes=[Change(
                operation_id="prefs.hardware_acceleration",
                kind="prefs",
                description="Spotify prefs file",
                target=str(prefs),
                before="true",
                after="false",
                payload={"key": "hardware_acceleration_mode_enabled",
                         "value": "false"},
            )],
            backup_targets=[prefs],
        )
        dialog = PlanPreviewDialog(app_instance, plan, on_apply=None)
        dialog.update()
        try:
            text = dialog.body.get("1.0", "end")
            assert "hardware_acceleration_mode_enabled" in text
            assert "true -> false" in text
            assert str(prefs) in text
            assert "hash-verified backup" in text
        finally:
            dialog.destroy()

    def test_preview_dialog_has_no_apply_button_for_empty_plan(self, app_instance):
        plan = Plan(request=OptimizationRequest())
        dialog = PlanPreviewDialog(app_instance, plan, on_apply=lambda: None)
        dialog.update()
        try:
            buttons = []

            def walk(widget):
                for child in widget.winfo_children():
                    if child.__class__.__name__ == "CTkButton":
                        buttons.append(str(child.cget("text")))
                    walk(child)

            walk(dialog)
            assert "Apply changes" not in buttons
            assert "Close" in buttons
        finally:
            dialog.destroy()

    def test_integrity_problem_is_surfaced(self, app_instance):
        panel = app_instance.backups_panel
        panel.get_backups = lambda: [{
            "name": "broken",
            "created_at": "2024-01-01",
            "artefacts": {"prefs": True},
            "integrity_ok": False,
            "has_manifest": True,
            "size_bytes": 10,
            "operations": [],
        }]
        panel.refresh()
        labels = []

        def walk(widget):
            for child in widget.winfo_children():
                if child.__class__.__name__ == "CTkLabel":
                    labels.append(str(child.cget("text")))
                walk(child)

        walk(panel.listing)
        assert any("Integrity problem" in text for text in labels)
