"""
Tests for registry manager.

Mocks winreg entirely — never touches real registry.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


class TestRegistryManager:
    """
    All winreg operations are mocked.
    Tests verify correct calls are made — not real registry state.
    """

    @pytest.fixture
    def mgr(self):
        from src.core.registry_manager import RegistryManager
        return RegistryManager()

    def test_get_startup_entries_found(self, mgr):
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = lambda s: mock_key
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.QueryValueEx.side_effect = lambda k, name: (
            f"C:\\Spotify\\{name}.exe --minimized", 1
        )
        mock_winreg.HKEY_CURRENT_USER = 0x80000001

        with patch("src.core.registry_manager._open_winreg", return_value=mock_winreg):
            entries = mgr.get_startup_entries()

        assert isinstance(entries, dict)

    def test_get_startup_entries_no_winreg(self, mgr):
        with patch("src.core.registry_manager._open_winreg", return_value=None):
            entries = mgr.get_startup_entries()
        assert entries == {}

    def test_disable_startup_entry(self, mgr):
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = lambda s: mock_key
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.HKEY_CURRENT_USER = 0x80000001

        with patch("src.core.registry_manager._open_winreg", return_value=mock_winreg):
            result = mgr.disable_startup_entry("Spotify")

        assert result is True
        mock_winreg.DeleteValue.assert_called_once()

    def test_enable_startup_entry(self, mgr):
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = lambda s: mock_key
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.REG_SZ = 1
        mock_winreg.HKEY_CURRENT_USER = 0x80000001

        with patch("src.core.registry_manager._open_winreg", return_value=mock_winreg):
            result = mgr.enable_startup_entry("Spotify", "C:\\Spotify\\Spotify.exe")

        assert result is True
        mock_winreg.SetValueEx.assert_called_once()

    def test_export_for_backup(self, mgr):
        with patch.object(mgr, "get_startup_entries", return_value={"Spotify": "C:\\x.exe"}):
            data = mgr.export_for_backup()
        assert "startup_entries" in data
        assert data["startup_entries"]["Spotify"] == "C:\\x.exe"

    def test_restore_from_backup(self, mgr):
        backup_data = {"startup_entries": {"Spotify": "C:\\Spotify.exe --min"}}
        with patch.object(mgr, "get_startup_entries", return_value={}):
            with patch.object(mgr, "disable_startup_entry", return_value=True):
                with patch.object(mgr, "enable_startup_entry", return_value=True) as mock_enable:
                    result = mgr.restore_from_backup(backup_data)
        assert result is True
        mock_enable.assert_called_with("Spotify", "C:\\Spotify.exe --min")
