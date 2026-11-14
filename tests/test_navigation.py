"""
Comprehensive automated navigation test suite for Spotify RAM Optimizer.

Verifies:
  1. All 7 sidebar navigation items switch to their respective pages.
  2. The displayed page is mapped (visible) and all previous/other pages are unmapped (hidden).
  3. The active sidebar button highlight matches the displayed page.
  4. The top header title and description reflect the current page.
  5. Multi-step navigation sequences (Dashboard -> Optimizations -> Activity -> Performance -> Settings -> Dashboard).
  6. Repeated cycles do not create duplicate widgets or leak state.
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
    """App should open with Dashboard as the authoritative active page."""
    app = app_instance
    assert app.current_page == "Dashboard"
    assert is_page_mapped(app.dashboard) is True
    assert is_page_mapped(app.settings_panel) is False
    assert is_page_mapped(app.results_panel) is False
    assert is_page_mapped(app.backups_panel) is False
    assert is_page_mapped(app.log_panel) is False
    assert is_page_mapped(app.app_settings_panel) is False
    assert is_page_mapped(app.about_panel) is False

    assert app._page_title.cget("text") == PAGE_METADATA["Dashboard"][0]


@pytest.mark.parametrize("page_name, expected_panel_attr, expected_title", [
    ("Dashboard", "dashboard", "Dashboard"),
    ("Optimizations", "settings_panel", "Optimizations"),
    ("Performance", "results_panel", "Performance"),
    ("Backups", "backups_panel", "Backups & Restore"),
    ("Activity", "log_panel", "Activity Logs"),
    ("Settings", "app_settings_panel", "Settings"),
    ("About", "about_panel", "About"),
])
def test_navigate_to_every_page(app_instance, page_name, expected_panel_attr, expected_title):
    """Clicking every sidebar item must show the correct page and hide all others."""
    app = app_instance
    success = app.show_page(page_name)
    app.update()

    assert success is True
    assert app.current_page == page_name

    # Target page must be visible
    target_widget = getattr(app, expected_panel_attr)
    assert is_page_mapped(target_widget) is True, f"Expected {expected_panel_attr} to be mapped"

    # All other pages must be unmapped (invisible)
    all_pages = [
        app.dashboard, app.settings_panel, app.results_panel,
        app.backups_panel, app.log_panel, app.app_settings_panel, app.about_panel
    ]
    for p in all_pages:
        if p is not target_widget:
            assert is_page_mapped(p) is False, f"Expected other page to be unmapped, but found mapped"

    # Header title must match
    assert app._page_title.cget("text") == expected_title

    # Sidebar button must be highlighted
    for key, btn in app.nav.buttons.items():
        if key == page_name:
            assert btn.cget("text_color") != "#9AA3B2", f"Button {key} should have active text color"
        else:
            assert btn.cget("fg_color") == "transparent", f"Inactive button {key} should have transparent bg"


def test_navigation_sequence_and_no_duplicates(app_instance):
    """Test switching across multiple pages repeatedly in complex sequence."""
    app = app_instance
    sequence = ["Dashboard", "Optimizations", "Activity", "Performance", "Settings", "Backups", "About", "Dashboard"]

    # Record initial widget counts in page host
    initial_children = len(app._page_host.winfo_children())

    # Run the sequence 3 times
    for _ in range(3):
        for page in sequence:
            app.show_page(page)
            app.update()
            assert app.current_page == page
            assert app.nav.is_visible(page) is True

    # No duplicate frames should be created
    assert len(app._page_host.winfo_children()) == initial_children


def test_log_entry_does_not_paint_over_optimizations(app_instance):
    """Simulate a log entry arriving while on Optimizations page to verify zero frame bleeding."""
    app = app_instance

    # Navigate to Optimizations
    app.show_page("Optimizations")
    app.update()
    assert app.current_page == "Optimizations"
    assert is_page_mapped(app.settings_panel) is True
    assert is_page_mapped(app.log_panel) is False

    # Emit a log entry
    app.log_panel.append("12:00:00", "INFO", "Background scan event")
    app.update()

    # Log panel must STILL be unmapped and Optimizations must remain visible
    assert is_page_mapped(app.log_panel) is False
    assert is_page_mapped(app.settings_panel) is True
    assert app.current_page == "Optimizations"
    assert app._page_title.cget("text") == "Optimizations"


def test_invalid_navigation_fails_gracefully(app_instance):
    """Attempting to navigate to an unknown page returns False and retains current page."""
    app = app_instance
    app.show_page("Dashboard")
    app.update()

    res = app.show_page("NonExistentPage")
    assert res is False
    assert app.current_page == "Dashboard"
    assert is_page_mapped(app.dashboard) is True
