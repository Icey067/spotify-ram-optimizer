"""
Automated navigation test suite for the Spotify RAM Optimizer workspace.

Verifies:
  1. All sidebar navigation items switch to their respective pages.
  2. The displayed page is mapped (visible) and all other pages are unmapped.
  3. The active sidebar button highlight matches the displayed page.
  4. The top header title and description reflect the current page.
  5. Multi-step navigation sequences do not create duplicate widgets.
  6. Pages are built lazily: only the page being shown is constructed.
  7. Logging updates do not bleed over inactive pages.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.gui.app import App
from src.gui.navigation import PAGE_METADATA, is_page_mapped

PAGES = (
    ("Dashboard", "dashboard", "Dashboard"),
    ("Optimizations", "settings_panel", "Optimizations"),
    ("Diagnostics", "diagnostics_panel", "Diagnostics"),
    ("Performance", "results_panel", "Performance"),
    ("Processes", "processes_panel", "Processes"),
    ("Backups", "backups_panel", "Backups & Restore"),
    ("Startup", "startup_panel", "Startup"),
    ("Installation", "installation_panel", "Installation"),
    ("Activity", "log_panel", "Activity Logs"),
    ("Privacy", "privacy_panel", "Privacy Center"),
    ("Settings", "app_settings_panel", "Settings"),
    ("About", "about_panel", "About"),
)


@pytest.fixture
def app_instance():
    """Create an App instance for testing and destroy it safely on teardown."""
    app = App()
    app.update()
    yield app
    try:
        app.quit()
        app.destroy()
    except Exception:
        pass


def test_initial_page_is_dashboard(app_instance):
    """The window opens on Dashboard with no other page built yet."""
    app = app_instance
    assert app.current_page == "Dashboard"
    assert is_page_mapped(app.dashboard) is True
    assert app._page_title.cget("text") == PAGE_METADATA["Dashboard"][0]
    # Lazy construction: start-up builds the dashboard only.
    assert set(app._pages) == {"Dashboard"}
    dashboard = app.nav.pages["Dashboard"]
    expected = getattr(dashboard, "_parent_frame", dashboard)
    assert app._page_host.winfo_children() == [expected], (
        "only the dashboard frame should be created at start-up"
    )


@pytest.mark.parametrize("page_name, expected_panel_attr, expected_title", PAGES)
def test_navigate_to_every_page(app_instance, page_name, expected_panel_attr,
                                expected_title):
    """Clicking every sidebar item shows the correct page and hides all others."""
    app = app_instance
    for name, attr, _title in PAGES:
        app.show_page(name)
        app.update()

        assert app.current_page == name
        target_widget = getattr(app, attr)
        assert is_page_mapped(target_widget) is True, f"Expected {attr} to be mapped"

        for other_name, other_attr, _ in PAGES:
            if other_attr == attr:
                continue
            assert is_page_mapped(getattr(app, other_attr)) is False, (
                f"Expected {other_attr} to be unmapped while on {name}"
            )

        assert app._page_title.cget("text") == PAGE_METADATA[name][0]
        for key, button in app.nav.buttons.items():
            if key == name:
                assert button.cget("text_color") != "#9AA3B2"
            else:
                assert button.cget("fg_color") == "transparent"

    # Every declared page is reachable.
    assert set(app._pages) == {name for name, _, _ in PAGES}


def test_navigation_sequence_and_no_duplicates(app_instance):
    """Repeated cycles reuse the same frames; no duplicate widgets appear."""
    app = app_instance
    sequence = [name for name, _, _ in PAGES] + ["Dashboard"]

    # Warm every page once (lazy construction happens here), then count.
    app.show_page("Dashboard")
    app.update()
    for page in sequence:
        app.show_page(page)
        app.update()
    initial_children = len(app._page_host.winfo_children())

    for _ in range(3):
        for page in sequence:
            app.show_page(page)
            app.update()
            assert app.current_page == page
            assert app.nav.is_visible(page) is True

    assert len(app._page_host.winfo_children()) == initial_children
    assert len(app.nav.pages) == len(PAGES)


def test_log_entry_does_not_paint_over_optimizations(app_instance):
    """A log entry arriving on another page must not bleed into it."""
    app = app_instance

    app.show_page("Optimizations")
    app.update()
    assert app.current_page == "Optimizations"
    assert is_page_mapped(app.settings_panel) is True
    assert is_page_mapped(app.log_panel) is False

    app.log_panel.append("12:00:00", "INFO", "Background scan event")
    app.update()

    assert is_page_mapped(app.log_panel) is False
    assert is_page_mapped(app.settings_panel) is True
    assert app.current_page == "Optimizations"
    assert app._page_title.cget("text") == "Optimizations"


def test_invalid_navigation_fails_gracefully(app_instance):
    """Unknown page names return False and leave the current page untouched."""
    app = app_instance
    app.show_page("Dashboard")
    app.update()

    assert app.show_page("NonExistentPage") is False
    assert app.current_page == "Dashboard"
    assert is_page_mapped(app.dashboard) is True
