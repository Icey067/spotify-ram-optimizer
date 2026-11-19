"""
Automated version consistency test across all application surfaces.

Verifies that the release candidate version 1.2.0 is uniformly defined across
the core engine, GUI app, Windows binary version metadata, documentation,
and command-line interface.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_VERSION = "1.2.0"
TARGET_VERSION_TUPLE = (1, 2, 0, 0)
TARGET_FILE_VERSION = "1.2.0.0"


def test_engine_app_version():
    from src.core.engine import APP_VERSION
    assert APP_VERSION == TARGET_VERSION, f"engine.APP_VERSION is {APP_VERSION}, expected {TARGET_VERSION}"


def test_gui_app_version():
    from src.gui.app import App
    assert App.VERSION == TARGET_VERSION, f"App.VERSION is {App.VERSION}, expected {TARGET_VERSION}"


def test_workspace_pages_about_default_version():
    import inspect
    from src.gui.workspace_pages import AboutPanel
    sig = inspect.signature(AboutPanel.__init__)
    param = sig.parameters.get("version")
    assert param is not None
    assert param.default == TARGET_VERSION


def test_version_info_file_metadata():
    version_file = ROOT / "version_info.txt"
    assert version_file.is_file(), "version_info.txt missing"
    content = version_file.read_text(encoding="utf-8")

    assert f"filevers={TARGET_VERSION_TUPLE}" in content
    assert f"prodvers={TARGET_VERSION_TUPLE}" in content
    assert f"StringStruct('FileVersion', '{TARGET_FILE_VERSION}')" in content
    assert f"StringStruct('ProductVersion', '{TARGET_VERSION}')" in content

    # Ensure no lingering 1.1.1 remains in version_info.txt
    assert "1.1.1" not in content


def test_main_cli_version_support():
    import subprocess
    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert f"v{TARGET_VERSION}" in result.stdout.strip()


def test_readme_version_reference():
    readme = ROOT / "README.md"
    assert readme.is_file()
    content = readme.read_text(encoding="utf-8")
    assert TARGET_VERSION in content


def test_changelog_version_reference():
    changelog = ROOT / "CHANGELOG.md"
    assert changelog.is_file()
    content = changelog.read_text(encoding="utf-8")
    assert f"[{TARGET_VERSION}]" in content


def test_release_notes_version_reference():
    notes = ROOT / "docs" / "RELEASE_NOTES.md"
    assert notes.is_file()
    content = notes.read_text(encoding="utf-8")
    assert f"v{TARGET_VERSION}" in content or f"{TARGET_VERSION}" in content
