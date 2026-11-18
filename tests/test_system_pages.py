"""
GUI tests for the surfaces added in 1.1.1:

  - the Spotify process tree viewer,
  - the startup-entry management page,
  - the installation information page,
  - the selective restore dialog (components + conflict resolution).

These exercise widget state only. They never terminate a process, write a
registry value, restore a backup or change configuration.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.process_manager import ProcessDetails
from src.core.registry_manager import StartupEntry
from src.gui.app import App
from src.gui.restore_dialog import RestoreDialog


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


def _buttons(widget) -> list[str]:
    found: list[str] = []
    for child in widget.winfo_children():
        if child.__class__.__name__ == "CTkButton":
            found.append(str(child.cget("text")))
        found.extend(_buttons(child))
    return found


# ---------------------------------------------------------------------------
# Process tree
# ---------------------------------------------------------------------------

class TestProcessesPanel:
    def test_rows_render_memory_and_parent(self, app_instance):
        panel = app_instance.processes_panel
        panel.set_rows([
            ProcessDetails(100, "Spotify.exe", 500.0, 4.0, "running", 1.0, None,
                           "C:/x/Spotify.exe", True),
            ProcessDetails(200, "SpotifyWebHelper.exe", 50.0, 1.0, "running", 2.0, 100,
                           "C:/x/SpotifyWebHelper.exe", True),
        ])
        app_instance.update()
        assert panel.count_card.value.cget("text") == "2"
        assert panel.memory_card.value.cget("text") == "550.0 MB"
        texts = _labels(panel._rows)
        assert any("SpotifyWebHelper.exe" in text for text in texts)
        assert any("child of PID 100" in text for text in texts)
        assert any("Spotify.exe" in text for text in texts)

    def test_empty_state_does_not_claim_memory(self, app_instance):
        panel = app_instance.processes_panel
        panel.set_rows([])
        app_instance.update()
        assert panel.count_card.value.cget("text") == "0"
        assert panel.memory_card.value.cget("text") == "—"
        assert any("Spotify is not running" in text for text in _labels(panel._rows))

    def test_no_terminate_controls_exist(self, app_instance):
        panel = app_instance.processes_panel
        panel.set_rows([
            ProcessDetails(100, "Spotify.exe", 10.0, 0.0, "running", 1.0, None,
                           "C:/x/Spotify.exe", True),
        ])
        app_instance.update()
        buttons = [text.lower() for text in _buttons(panel)]
        assert not any("kill" in text or "end" in text for text in buttons)


# ---------------------------------------------------------------------------
# Startup entries
# ---------------------------------------------------------------------------

class TestStartupPanel:
    def test_entries_render_state_and_safety(self, app_instance):
        panel = app_instance.startup_panel
        panel.set_entries([
            StartupEntry("Spotify", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                         '"C:/x/Spotify.exe" --autostart', True, True, True),
            StartupEntry("SpotifyStartup.lnk", "Startup folder", "C:/link.lnk", True,
                         True, False, "Read-only startup folder shortcut."),
        ])
        app_instance.update()
        texts = _labels(panel.listing)
        assert any("ENABLED" == text for text in texts)
        assert any("READ-ONLY" == text for text in texts)
        assert "1 changeable here" in panel.summary_text.cget("text")
        buttons = _buttons(panel.listing)
        assert "Disable" in buttons
        assert buttons.count("Disable") == 1, "unsafe entries must not get a button"

    def test_empty_state_is_explicit(self, app_instance):
        panel = app_instance.startup_panel
        panel.set_entries([])
        app_instance.update()
        assert any("No Spotify startup entries" in text
                   for text in _labels(panel.listing))
        assert "0 entries" in panel.summary_text.cget("text")

    def test_disabled_entry_offers_enable(self, app_instance):
        panel = app_instance.startup_panel
        panel.set_entries([
            StartupEntry("Spotify", r"HKCU\...\Run", '"C:/x/Spotify.exe"', False,
                         True, True, "Already disabled by Windows."),
        ])
        app_instance.update()
        assert "Enable" in _buttons(panel.listing)
        assert any("DISABLED" == text for text in _labels(panel.listing))


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

class TestInstallationPanel:
    REPORT = {
        "install_type": "Standard",
        "version": "1.2.3.4",
        "exe_path": r"C:\Users\someone\AppData\Roaming\Spotify\Spotify.exe",
        "data_path": r"C:\Users\someone\AppData\Roaming\Spotify",
        "prefs_path": r"C:\Users\someone\AppData\Roaming\Spotify\prefs",
        "cache_path": r"C:\Users\someone\AppData\Roaming\Spotify\Data",
        "store_package": "",
        "prefs_bytes": 2048,
        "prefs_readable": True,
        "prefs_writable": True,
        "cache_bytes": 5 * 1024 * 1024,
        "cache_disposable_bytes": 3 * 1024 * 1024,
        "cache_dirs": 3,
        "spicetify": {
            "installed": True, "version": "2.46.7",
            "config": r"C:\Users\someone\AppData\Roaming\spicetify\config-xpui.ini",
            "extensions": ["a", "b"], "custom_apps": [],
        },
        "windows": "Windows 11",
        "windows_build": 22631,
        "windows_edition": "Professional",
        "architecture": "AMD64",
        "process_count": 3,
        "startup_entries": 1,
        "notes": ["Spotify version could not be read from the executable metadata."],
    }

    def test_report_is_rendered(self, app_instance):
        panel = app_instance.installation_panel
        panel.set_report(dict(self.REPORT))
        app_instance.update()
        assert panel.values["type"].cget("text") == "Standard"
        assert panel.values["version"].cget("text") == "1.2.3.4"
        assert panel.values["prefs_size"].cget("text") == "2.0 KB"
        assert panel.values["cache_disposable"].cget("text") == "3.0 MB"
        assert panel.values["sp_status"].cget("text") == "Installed"
        assert "build 22631" in panel.values["windows"].cget("text")
        assert "executable metadata" in panel.notes.cget("text")

    def test_paths_are_redacted(self, app_instance, monkeypatch):
        monkeypatch.setenv("USERPROFILE", r"C:\Users\someone")
        panel = app_instance.installation_panel
        panel.set_report(dict(self.REPORT))
        app_instance.update()
        assert panel.values["exe"].cget("text").startswith("%USERPROFILE%")

    def test_not_found_state_is_explicit(self, app_instance):
        panel = app_instance.installation_panel
        report = dict(self.REPORT)
        report.update({"install_type": "Not Found", "prefs_path": "", "cache_path": "",
                       "spicetify": {}, "notes": []})
        panel.set_report(report)
        app_instance.update()
        assert panel.values["prefs"].cget("text") == "Not detected"
        assert "not detected" in panel.notes.cget("text").lower()


# ---------------------------------------------------------------------------
# Selective restore
# ---------------------------------------------------------------------------

SUMMARY = {
    "name": "20260101_120000",
    "created_at": "2026-01-01T12:00:00",
    "artefacts": {"prefs": True, "registry": True, "shortcuts": False,
                  "spicetify": True},
    "integrity_ok": True,
    "has_manifest": True,
    "integrity_detail": "Integrity verified (3 artefact(s)).",
}


class TestRestoreDialog:
    def test_present_components_are_selected_by_default(self, app_instance):
        dialog = RestoreDialog(app_instance, dict(SUMMARY))
        dialog.update()
        try:
            assert dialog.selected_components() == ["prefs", "registry", "spicetify"]
            assert dialog._restore_button.cget("state") == "normal"
        finally:
            dialog.destroy()

    def test_deselecting_everything_disables_restore(self, app_instance):
        dialog = RestoreDialog(app_instance, dict(SUMMARY))
        dialog.update()
        try:
            for var in dialog._vars.values():
                var.set(False)
            dialog._update_state()
            assert dialog._restore_button.cget("state") == "disabled"
            assert "at least one" in dialog._status.cget("text")
        finally:
            dialog.destroy()

    def test_selected_components_are_handed_to_the_app(self, app_instance):
        calls: list[tuple] = []
        dialog = RestoreDialog(app_instance, dict(SUMMARY),
                               on_restore=lambda components, overwrite:
                               calls.append((components, overwrite)))
        dialog.update()
        dialog._vars["registry"].set(False)
        dialog._restore()
        app_instance.update()
        assert calls == [(["prefs", "spicetify"], False)]

    def test_conflict_is_named_and_requires_explicit_overwrite(self, app_instance):
        conflicts = {"prefs": "Spotify preferences changed after this backup was taken."}
        calls: list[tuple] = []
        dialog = RestoreDialog(app_instance, dict(SUMMARY),
                               on_restore=lambda components, overwrite:
                               calls.append((components, overwrite)),
                               conflicts=conflicts)
        dialog.update()
        try:
            assert any("changed after this backup" in text
                       for text in _labels(dialog))
            assert dialog._overwrite_box.cget("state") == "normal"
            assert dialog.overwrite_var.get() is False
        finally:
            dialog.destroy()

        dialog = RestoreDialog(app_instance, dict(SUMMARY),
                               on_restore=lambda components, overwrite:
                               calls.append((components, overwrite)),
                               conflicts=conflicts)
        dialog.update()
        dialog.overwrite_var.set(True)
        dialog._restore()
        app_instance.update()
        assert calls[-1] == (["prefs", "registry", "spicetify"], True)

    def test_no_conflicts_disables_overwrite_box(self, app_instance):
        dialog = RestoreDialog(app_instance, dict(SUMMARY))
        dialog.update()
        try:
            assert dialog._overwrite_box.cget("state") == "disabled"
        finally:
            dialog.destroy()

    def test_legacy_snapshot_is_labelled(self, app_instance):
        summary = dict(SUMMARY)
        summary.update({"has_manifest": False, "integrity_ok": False})
        dialog = RestoreDialog(app_instance, summary)
        dialog.update()
        try:
            assert any("Legacy snapshot" in text for text in _labels(dialog))
        finally:
            dialog.destroy()

    def test_integrity_problem_is_reported(self, app_instance):
        summary = dict(SUMMARY)
        summary.update({"integrity_ok": False, "integrity_detail": "hash mismatch: prefs"})
        dialog = RestoreDialog(app_instance, summary)
        dialog.update()
        try:
            assert any("hash mismatch" in text for text in _labels(dialog))
        finally:
            dialog.destroy()
