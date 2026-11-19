"""
Isolated Windows integration validation (1.2.0).

Three clearly separated levels are exercised here, and none of them touches the
developer's real Spotify profile, registry or cache:

  ISOLATED  real core code against a temporary, complete Spotify tree
            (%APPDATA%\\Spotify, prefs, cache, Spicetify config) with
            APPDATA/LOCALAPPDATA/SPOTIFY_OPTIMIZER_HOME redirected.
  MOCKED    the HKCU registry surface, replaced by an in-memory implementation,
            because writing real startup values from a test is not acceptable.
  SIMULATED the "spicetify apply" call, which would otherwise launch a binary.

Everything else is the production code path: detection, planning, backup,
preference writes, verification, restore, conflict handling, Spicetify config
editing, cache cleanup and backup retention.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core import benchmark as benchmark_module
from src.core import compatibility, detector, engine as engine_module
from src.core import performance_monitor as performance_module
from src.core.detector import InstallType, SpicetifyInfo, detect_installation
from src.core.engine import OptimizationEngine, OptimizationSettings
from src.core.optimizations import OPERATIONS_BY_ID, SupportLevel
from src.core.registry_manager import StartupEntry
from src.core.spicetify_manager import SpicetifyManager

PREFS = (
    "# Spotify preferences file\r\n"
    "app.autostart-mode=\"0\"\r\n"
    "hardware_acceleration_mode_enabled=true\r\n"
    "storage.size=1024\r\n"
    "\r\n"
    "[Setting1]\r\n"
    "value=preserved\r\n"
)

FAST_SETTINGS = dict(
    set_cache_size=False,
    disable_autostart=False,
    clean_browser_cache=False,
    clean_code_cache=False,
    clean_gpu_cache=False,
    set_autostart_pref=False,
)


class MemoryRegistry:
    """MOCKED registry: same surface as RegistryManager, no HKCU access."""

    LOCATION = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get_spotify_startup_entries(self) -> dict[str, str]:
        return dict(self.values)

    def get_startup_entries(self) -> dict[str, str]:
        return dict(self.values)

    def get_startup_entry_details(self) -> list[StartupEntry]:
        return [
            StartupEntry(name, self.LOCATION, command, True, True, True)
            for name, command in self.values.items()
        ]

    def export_for_backup(self) -> dict:
        return {"startup_entries": dict(self.values)}

    def disable_startup_entry(self, name: str, *, require_spotify_value: bool = False) -> bool:
        if name not in self.values:
            return True
        if require_spotify_value and "spotify" not in self.values[name].lower():
            return False
        self.values.pop(name)
        return True

    def enable_startup_entry(self, name: str, value: str) -> bool:
        if name.lower() not in {"spotify", "spotifywebhelper"}:
            return False
        self.values[name] = value
        return True

    def restore_from_backup(self, data: dict) -> bool:
        self.values = dict(data.get("startup_entries", {}))
        return True


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A complete, disposable Spotify installation plus redirected app state."""
    appdata = tmp_path / "appdata"
    spotify = appdata / "Spotify"
    spotify.mkdir(parents=True)
    (spotify / "Spotify.exe").write_bytes(b"MZ-isolated-stub")
    prefs = spotify / "prefs"
    prefs.write_bytes(PREFS.encode("utf-8"))

    cache = spotify / "Data"
    personal = {
        "Cache/state.bin": b"http-cache",
        "Code Cache/js.bin": b"bytecode",
        "GPUCache/shader.bin": b"shader",
        "Local Storage/leveldb.ldb": b"personal-local-storage",
        "Databases/db.sqlite": b"personal-db",
        "Users/me/playlists.json": b"personal-playlists",
    }
    for relative, content in personal.items():
        target = cache / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("SPOTIFY_OPTIMIZER_HOME", str(tmp_path / "state"))
    # Detection must not launch the real spicetify binary.
    monkeypatch.setattr(detector, "_detect_spicetify", lambda: SpicetifyInfo())
    # MOCKED process table: no real process is enumerated, stopped or
    # relaunched, and measurements cannot pick up the developer's Spotify.
    monkeypatch.setattr(compatibility, "get_spotify_process_count", lambda: 0)
    monkeypatch.setattr(engine_module, "is_spotify_running", lambda: False)
    monkeypatch.setattr(
        engine_module, "stop_spotify", lambda *a, **k: (True, "isolated: not running")
    )
    monkeypatch.setattr(benchmark_module, "get_spotify_processes", lambda: [])
    monkeypatch.setattr(performance_module, "get_spotify_processes", lambda: [])
    return SimpleNamespace(appdata=appdata, spotify=spotify, prefs=prefs, cache=cache,
                           root=tmp_path)


def _engine(isolated, registry=None) -> OptimizationEngine:
    install = detect_installation()
    assert install.install_type == InstallType.STANDARD
    engine = OptimizationEngine(
        installation=install, backup_root=isolated.root / "backups"
    )
    engine.registry_mgr = registry or MemoryRegistry()
    return engine


def _prefs_only(**overrides) -> OptimizationSettings:
    settings = OptimizationSettings(disable_hw_accel=True, **FAST_SETTINGS)
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _run(engine: OptimizationEngine, settings: OptimizationSettings, **overrides):
    """Run with a short sampling window so the suite stays fast."""
    kwargs = dict(measurement_seconds=0.05, allow_registry_changes=False)
    kwargs.update(overrides)
    return engine.run_optimization(settings, **kwargs)


# ---------------------------------------------------------------------------
# Detection (ISOLATED filesystem, real detector code)
# ---------------------------------------------------------------------------

class TestDetectionIsolated:
    def test_standard_installation_is_detected(self, isolated):
        install = detect_installation()
        assert install.install_type == InstallType.STANDARD
        assert Path(install.prefs_path) == isolated.prefs
        assert Path(install.cache_path) == isolated.cache
        assert install.data_path == isolated.spotify

    def test_microsoft_store_layout_is_detected(self, isolated, tmp_path):
        (isolated.spotify / "Spotify.exe").unlink()
        package = (tmp_path / "localappdata" / "Packages"
                   / "SpotifyAB.SpotifyMusic_zpdnekdrzrea0")
        store_exe = package / "LocalCache" / "Spotify" / "Spotify.exe"
        store_exe.parent.mkdir(parents=True)
        store_exe.write_bytes(b"MZ-store-stub")

        install = detect_installation()
        assert install.install_type == InstallType.STORE
        assert install.store_package_path is not None
        assert Path(install.exe_path) == store_exe

    def test_missing_installation_is_reported_not_guessed(self, isolated, monkeypatch,
                                                          tmp_path):
        (isolated.spotify / "Spotify.exe").unlink()
        empty = tmp_path / "empty-appdata"
        empty.mkdir()
        monkeypatch.setenv("APPDATA", str(empty))
        install = detect_installation()
        assert install.install_type == InstallType.NOT_FOUND
        assert install.prefs_path is None


# ---------------------------------------------------------------------------
# Compatibility reporting
# ---------------------------------------------------------------------------

class TestCompatibilityIsolated:
    def test_prefs_operations_are_supported_and_require_restart(self, isolated):
        env = compatibility.detect_environment(detect_installation())
        verdict = OPERATIONS_BY_ID["prefs.hardware_acceleration"].compatibility(env)
        assert verdict.usable
        assert verdict.level in (
            SupportLevel.REQUIRES_RESTART, SupportLevel.REQUIRES_CONFIRMATION
        )
        assert "next time spotify starts" in verdict.reason.lower()

    def test_cache_group_is_reported_available(self, isolated):
        env = compatibility.detect_environment(detect_installation())
        assert env.cache_readable
        assert OPERATIONS_BY_ID["cache.browser"].compatibility(env).usable

    def test_no_installation_makes_prefs_operations_unsupported(self):
        from src.core.detector import SpotifyInstallation
        env = compatibility.detect_environment(SpotifyInstallation())
        verdict = OPERATIONS_BY_ID["prefs.hardware_acceleration"].compatibility(env)
        assert not verdict.usable
        assert verdict.level == SupportLevel.UNSUPPORTED


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

class TestDryRunIsolated:
    def test_preview_changes_nothing_and_names_exact_values(self, isolated):
        engine = _engine(isolated)
        before = isolated.prefs.read_bytes()
        plan = engine.preview(_prefs_only())

        assert not plan.is_empty()
        change = next(c for c in plan.changes
                      if c.operation_id == "prefs.hardware_acceleration")
        assert change.before == "true"
        assert change.after == "false"
        assert "true -> false" in "\n".join(plan.describe())
        assert isolated.prefs.read_bytes() == before
        assert engine.backup_mgr.list_sessions() == [], "a preview must not back up"


# ---------------------------------------------------------------------------
# Backup, apply, verify, restore, conflicts
# ---------------------------------------------------------------------------

class TestApplyAndRestoreIsolated:
    def test_backup_is_created_and_verified_before_changes(self, isolated):
        engine = _engine(isolated)
        result = _run(engine, _prefs_only())

        assert result.success, result.messages
        session = result.backup_session
        assert session is not None and session.is_dir()
        assert (session / "manifest.json").is_file()
        assert engine.backup_mgr.verify_integrity(session).ok
        assert (session / "prefs").read_bytes() == PREFS.encode("utf-8")
        assert any("Integrity verified" in message for message in result.messages)

    def test_preference_is_written_verified_and_format_preserved(self, isolated):
        engine = _engine(isolated)
        result = _run(engine, _prefs_only())

        raw = isolated.prefs.read_bytes()
        assert result.operations_completed >= 1
        assert any("(verified)" in message for message in result.messages)
        assert b"hardware_acceleration_mode_enabled=false" in raw
        assert b"[Setting1]\r\nvalue=preserved" in raw, "sections must survive"
        assert b"# Spotify preferences file\r\n" in raw, "comments must survive"
        assert raw.count(b"\r\n") >= 5, "CRLF line endings must survive"

    def test_no_memory_claim_when_spotify_was_not_running(self, isolated):
        engine = _engine(isolated)
        result = _run(engine, _prefs_only())
        assert result.comparison is not None
        assert result.comparison.comparable is False
        assert result.comparison.notes

    def test_restore_returns_the_exact_original_bytes(self, isolated):
        engine = _engine(isolated)
        result = _run(engine, _prefs_only())
        assert b"false" in isolated.prefs.read_bytes()

        restored = engine.restore_session(
            result.backup_session, components=["prefs"], allow_system_changes=True
        )
        assert restored.success, restored.messages
        assert isolated.prefs.read_bytes() == PREFS.encode("utf-8")

    def test_conflict_blocks_overwrite_until_explicitly_allowed(self, isolated):
        engine = _engine(isolated)
        result = _run(engine, _prefs_only())
        session = result.backup_session

        # Emulate Spotify itself rewriting prefs after the optimization.
        isolated.prefs.write_bytes(
            isolated.prefs.read_bytes().replace(b"false", b"true")
        )
        live = isolated.prefs.read_bytes()

        blocked = engine.restore_session(
            session, components=["prefs"], allow_system_changes=True
        )
        assert blocked.conflicts
        assert "prefs" in blocked.conflicts_by_component
        assert not blocked.success
        assert isolated.prefs.read_bytes() == live, "conflict must not overwrite"

        forced = engine.restore_session(
            session, components=["prefs"], allow_conflict=True,
            allow_system_changes=True,
        )
        assert forced.success, forced.messages
        assert isolated.prefs.read_bytes() == PREFS.encode("utf-8")

    def test_selective_restore_skips_unselected_components(self, isolated):
        engine = _engine(isolated)
        result = _run(engine, _prefs_only())
        restored = engine.restore_session(
            result.backup_session, components=["spicetify"],
            allow_system_changes=True,
        )
        # Nothing to restore in that component, and prefs stay optimized.
        assert not restored.conflicts
        assert b"false" in isolated.prefs.read_bytes()


# ---------------------------------------------------------------------------
# Startup entries (MOCKED registry)
# ---------------------------------------------------------------------------

class TestStartupIsolated:
    def test_disable_is_backed_up_and_verified(self, isolated):
        command = r'"C:\Users\me\AppData\Roaming\Spotify\Spotify.exe" --autostart'
        registry = MemoryRegistry({"Spotify": command})
        engine = _engine(isolated, registry)

        result = engine.set_startup_entry("Spotify", False)
        assert result.success, result.messages
        assert registry.values == {}
        assert result.backup_session is not None
        data = engine.backup_mgr.restore_registry_data(result.backup_session)
        assert data["startup_entries"]["Spotify"] == command
        assert engine.backup_mgr.verify_integrity(result.backup_session).ok

    def test_enable_uses_the_recorded_command(self, isolated):
        command = r'"C:\Users\me\AppData\Roaming\Spotify\Spotify.exe" --autostart'
        registry = MemoryRegistry({"Spotify": command})
        engine = _engine(isolated, registry)
        assert engine.set_startup_entry("Spotify", False).success

        result = engine.set_startup_entry("Spotify", True)
        assert result.success, result.messages
        assert registry.values["Spotify"] == command

    def test_registry_restore_guard_is_portable(self, isolated):
        """PORTABLE (MOCKED registry): restore writes only with explicit opt-in."""
        command = '"C:/x/Spotify.exe"'
        registry = MemoryRegistry({"Spotify": command})
        engine = _engine(isolated, registry)

        disabled = engine.set_startup_entry("Spotify", False)
        assert disabled.success, disabled.messages
        assert registry.values == {}

        guarded = engine.restore_session(disabled.backup_session,
                                         allow_system_changes=False)
        assert any("disabled in this context" in message for message in guarded.messages)
        assert registry.values == {}, "guarded restore must not write"

        allowed = engine.restore_session(disabled.backup_session,
                                         allow_conflict=True,
                                         allow_system_changes=True)
        assert allowed.success, allowed.messages
        assert registry.values.get("Spotify") == command

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason=(
            "A full run only plans the registry operation on Windows; the mocked "
            "restore-guard test above covers the opt-in logic on every platform."
        ),
    )
    def test_registry_restore_requires_opt_in(self, isolated):
        """WINDOWS-ONLY: full run plans and applies the startup operation."""
        registry = MemoryRegistry({"Spotify": '"C:/x/Spotify.exe"'})
        engine = _engine(isolated, registry)
        result = _run(engine, _prefs_only(disable_autostart=True),
                      allow_registry_changes=True)
        assert result.success, result.messages
        assert registry.values == {}

        guarded = engine.restore_session(result.backup_session,
                                         allow_system_changes=False)
        assert any("disabled in this context" in message for message in guarded.messages)
        assert registry.values == {}

        allowed = engine.restore_session(result.backup_session,
                                         allow_conflict=True,
                                         allow_system_changes=True)
        assert allowed.success, allowed.messages
        assert "Spotify" in registry.values


# ---------------------------------------------------------------------------
# Cache cleanup with personal-data protection
# ---------------------------------------------------------------------------

class TestCacheIsolated:
    def test_only_disposable_caches_are_removed(self, isolated):
        engine = _engine(isolated)
        result = _run(
            engine,
            _prefs_only(disable_hw_accel=False, clean_browser_cache=True,
                        clean_code_cache=True),
        )
        assert result.success, result.messages
        assert list((isolated.cache / "Cache").iterdir()) == []
        assert list((isolated.cache / "Code Cache").iterdir()) == []
        for protected in ("Local Storage/leveldb.ldb", "Databases/db.sqlite",
                          "Users/me/playlists.json"):
            assert (isolated.cache / protected).is_file(), f"{protected} must survive"
        assert isolated.prefs.is_file()
        assert (isolated.cache / "GPUCache" / "shader.bin").is_file()

    def test_cache_report_marks_disposable_bytes(self, isolated):
        engine = _engine(isolated)
        report = engine.installation_report()
        assert report["cache_dirs"] >= 3
        assert report["cache_disposable_bytes"] > 0
        assert report["cache_bytes"] >= report["cache_disposable_bytes"]


# ---------------------------------------------------------------------------
# Spicetify (ISOLATED config, SIMULATED apply)
# ---------------------------------------------------------------------------

class TestSpicetifyIsolated:
    @pytest.fixture
    def spicetify_setup(self, isolated, monkeypatch, tmp_path):
        config_dir = tmp_path / "spicetify"
        config_dir.mkdir()
        config = config_dir / "config-xpui.ini"
        original = (
            "[AdditionalOptions]\r\n"
            "extensions=extA|extB\r\n"
            "custom_apps=appA\r\n"
        )
        config.write_bytes(original.encode("utf-8"))

        install = detect_installation()
        install.spicetify = SpicetifyInfo(
            is_installed=True,
            exe_path=tmp_path / "spicetify-stub.exe",
            version="2.46.7",
            config_path=config,
            config_dir=config_dir,
            extensions=["extA", "extB"],
            custom_apps=["appA"],
        )
        monkeypatch.setattr(
            SpicetifyManager, "run_apply", lambda self: (True, "simulated: not executed")
        )
        engine = OptimizationEngine(
            installation=install, backup_root=isolated.root / "backups"
        )
        engine.registry_mgr = MemoryRegistry()
        return SimpleNamespace(engine=engine, config=config, original=original,
                               install=install)

    def test_extension_is_disabled_and_can_be_restored(self, spicetify_setup):
        setup = spicetify_setup
        result = _run(
            setup.engine,
            _prefs_only(disable_hw_accel=False, disable_spicetify_extensions=["extA"]),
        )
        assert result.success, result.messages
        text = setup.config.read_text(encoding="utf-8")
        assert "extA" not in text
        assert "extB" in text
        assert (result.backup_session / "spicetify_config.ini").is_file()

        restored = setup.engine.restore_session(
            result.backup_session, components=["spicetify"], allow_system_changes=True
        )
        assert restored.success, restored.messages
        # Byte comparison: read_text() would normalise CRLF away.
        assert setup.config.read_bytes() == setup.original.encode("utf-8")

    def test_missing_spicetify_is_reported_as_unsupported(self, isolated):
        env = compatibility.detect_environment(detect_installation())
        verdict = OPERATIONS_BY_ID["spicetify.extensions"].compatibility(env)
        assert not verdict.usable
        assert verdict.level == SupportLevel.UNSUPPORTED


# ---------------------------------------------------------------------------
# Installation report (ISOLATED)
# ---------------------------------------------------------------------------

class TestInstallationReportIsolated:
    def test_report_reflects_the_isolated_tree(self, isolated):
        engine = _engine(isolated)
        report = engine.installation_report()
        assert report["install_type"] == "Standard"
        assert report["prefs_path"] == str(isolated.prefs)
        assert report["prefs_readable"] is True
        assert report["prefs_bytes"] == len(PREFS.encode("utf-8"))
        assert report["spicetify"]["installed"] is False
        assert isinstance(report["notes"], list)
