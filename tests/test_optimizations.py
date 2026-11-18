"""
Optimization registry, dry-run planning and transactional execution tests.

Every test uses temporary directories and a fake registry; no real Spotify
prefs, registry values, shortcuts or cache files are touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.compatibility import Environment, WindowsInfo
from src.core.detector import InstallType, SpotifyInstallation
from src.core.engine import OptimizationSettings
from src.core.optimizations import (
    OPERATIONS,
    OPERATIONS_BY_ID,
    PROFILE_ADVANCED,
    PROFILE_BALANCED,
    PROFILE_SAFE,
    Optimizer,
    Plan,
    Risk,
    build_plan,
    operations_for_profile,
    request_from_settings,
)
from src.core.prefs_manager import PrefsManager


class FakeRegistry:
    """In-memory stand-in for RegistryManager."""

    def __init__(self, entries: dict[str, str] | None = None) -> None:
        self.entries = dict(entries or {})
        self.calls: list[tuple[str, str]] = []

    def get_startup_entries(self) -> dict[str, str]:
        return dict(self.entries)

    def get_spotify_startup_entries(self) -> dict[str, str]:
        return dict(self.entries)

    def disable_startup_entry(self, name: str, require_spotify_value: bool = False) -> bool:
        self.calls.append(("disable", name))
        self.entries.pop(name, None)
        return True

    def enable_startup_entry(self, name: str, value: str) -> bool:
        self.calls.append(("enable", name))
        self.entries[name] = value
        return True

    def export_for_backup(self) -> dict:
        return {"startup_entries": dict(self.entries)}

    def restore_from_backup(self, data: dict) -> bool:
        self.entries = dict(data.get("startup_entries", {}))
        return True


def make_env(tmp_path: Path, *, spotify_running: bool = False,
             with_cache_files: bool = True) -> Environment:
    spotify = tmp_path / "Spotify"
    spotify.mkdir(exist_ok=True)
    prefs = spotify / "prefs"
    prefs.write_text(
        "# Spotify preferences\n"
        "hardware_acceleration_mode_enabled=true\n"
        "storage.size=1024\n"
        "some.unknown.key=keep-me\n"
    )
    cache = spotify / "Data"
    (cache / "Cache").mkdir(parents=True, exist_ok=True)
    if with_cache_files:
        (cache / "Cache" / "tile").write_bytes(b"x" * 4096)
    (cache / "Code Cache").mkdir(exist_ok=True)
    if with_cache_files:
        (cache / "Code Cache" / "js").write_bytes(b"y" * 2048)

    install = SpotifyInstallation(
        install_type=InstallType.STANDARD,
        exe_path=spotify / "Spotify.exe",
        data_path=spotify,
        prefs_path=prefs,
        cache_path=cache,
        version="1.2.3.456",
    )
    return Environment(
        windows=WindowsInfo(True, "Windows 11", "11", 22631, "Professional", "AMD64"),
        installation=install,
        spotify_running=spotify_running,
        process_count=2 if spotify_running else 0,
        prefs_readable=True,
        prefs_writable=True,
        cache_readable=True,
        cache_root=cache,
        startup_entries={"Spotify": r"C:\Users\x\AppData\Roaming\Spotify\Spotify.exe --autostart"},
    )


def request(*operations: str, cache_size_mb: int = 256):
    from src.core.optimizations import OptimizationRequest
    return OptimizationRequest(operations=set(operations), cache_size_mb=cache_size_mb)


class TestRegistry:
    def test_operation_ids_are_unique(self):
        ids = [op.id for op in OPERATIONS]
        assert len(ids) == len(set(ids))

    def test_every_operation_has_metadata(self):
        for op in OPERATIONS:
            assert op.name and op.summary and op.detail and op.rationale
            assert isinstance(op.risk, Risk)
            assert op.profiles, f"{op.id} belongs to no profile"

    def test_safe_profile_is_conservative(self):
        safe = set(operations_for_profile(PROFILE_SAFE))
        assert "prefs.hardware_acceleration" in safe
        assert "cache.browser" in safe
        # Unverified and Spicetify operations must never be in the safe profile.
        assert "prefs.autostart" not in safe
        assert not any(op.startswith("spicetify") for op in safe)
        for operation_id in safe:
            assert not OPERATIONS_BY_ID[operation_id].unverified

    def test_advanced_profile_contains_unverified(self):
        assert "prefs.autostart" in operations_for_profile(PROFILE_ADVANCED)

    def test_request_from_settings_maps_checkboxes(self):
        settings = OptimizationSettings(
            disable_hw_accel=True,
            set_cache_size=False,
            disable_autostart=False,
            clean_browser_cache=True,
            clean_code_cache=False,
            clean_gpu_cache=False,
            set_autostart_pref=True,
        )
        req = request_from_settings(settings)
        assert "prefs.hardware_acceleration" in req.operations
        assert "cache.browser" in req.operations
        assert "prefs.cache_size" not in req.operations
        assert "prefs.autostart" in req.operations


class TestPlanning:
    def test_plan_is_read_only(self, tmp_path):
        env = make_env(tmp_path)
        prefs = Path(env.installation.prefs_path)
        before = prefs.read_bytes()
        plan = build_plan(
            request("prefs.hardware_acceleration", "prefs.cache_size", "cache.browser"),
            env,
            registry=FakeRegistry(),
        )
        assert plan.changes
        assert prefs.read_bytes() == before, "dry-run must not modify the prefs file"

    def test_plan_reports_real_before_and_after(self, tmp_path):
        env = make_env(tmp_path)
        plan = build_plan(request("prefs.hardware_acceleration"), env,
                          registry=FakeRegistry())
        change = plan.changes[0]
        assert change.before == "true"
        assert change.after == "false"
        assert change.target == str(env.installation.prefs_path)

    def test_plan_skips_already_applied_setting(self, tmp_path):
        env = make_env(tmp_path)
        prefs = PrefsManager(Path(env.installation.prefs_path))
        prefs.set_values({"hardware_acceleration_mode_enabled": "false"})
        plan = build_plan(request("prefs.hardware_acceleration"), env,
                          registry=FakeRegistry())
        assert plan.is_empty()
        assert any(s.operation_id == "prefs.hardware_acceleration" for s in plan.skipped)

    def test_plan_lists_cache_directories(self, tmp_path):
        env = make_env(tmp_path)
        plan = build_plan(request("cache.browser", "cache.code"), env,
                          registry=FakeRegistry())
        assert len(plan.changes) == 2
        assert all(change.kind == "cache" for change in plan.changes)
        assert plan.cache_bytes >= 4096
        text = "\n".join(plan.describe())
        assert "Cache" in text

    def test_plan_requires_spotify_closed(self, tmp_path):
        env = make_env(tmp_path)
        plan = build_plan(request("cache.browser"), env, registry=FakeRegistry())
        assert plan.requires_spotify_closed is True

    def test_unsupported_operation_is_reported_not_planned(self, tmp_path):
        env = make_env(tmp_path)
        env.cache_readable = False
        plan = build_plan(request("cache.browser"), env, registry=FakeRegistry())
        assert plan.is_empty()
        assert any(s.operation_id == "cache.browser" for s in plan.unsupported)


class TestExecution:
    def test_prefs_change_is_applied_and_verified(self, tmp_path):
        env = make_env(tmp_path)
        plan = build_plan(request("prefs.hardware_acceleration"), env,
                          registry=FakeRegistry())
        report = Optimizer(env, registry=FakeRegistry()).apply(plan)
        assert len(report.applied) == 1
        assert report.outcomes[0].verified is True
        values = PrefsManager(Path(env.installation.prefs_path)).read_all()
        assert values["hardware_acceleration_mode_enabled"] == "false"
        # Unknown keys and comments are preserved.
        assert values["some.unknown.key"] == "keep-me"

    def test_registry_is_untouched_without_explicit_permission(self, tmp_path):
        env = make_env(tmp_path)
        registry = FakeRegistry(env.startup_entries)
        plan = build_plan(request("startup.run_entry"), env, registry=registry)
        assert plan.changes
        report = Optimizer(env, registry=registry).apply(plan, allow_registry=False)
        assert registry.calls == []
        assert registry.entries  # still present
        assert report.outcomes[0].status == "skipped"

    def test_registry_change_applies_when_permitted(self, tmp_path):
        env = make_env(tmp_path)
        registry = FakeRegistry(env.startup_entries)
        plan = build_plan(request("startup.run_entry"), env, registry=registry)
        report = Optimizer(env, registry=registry).apply(plan, allow_registry=True)
        assert registry.calls == [("disable", "Spotify")]
        assert registry.entries == {}
        assert report.applied

    def test_cache_cleanup_skipped_while_spotify_runs(self, tmp_path):
        env = make_env(tmp_path, spotify_running=True)
        plan = build_plan(request("cache.browser"), env, registry=FakeRegistry())
        report = Optimizer(env, registry=FakeRegistry()).apply(plan)
        assert report.outcomes[0].status == "skipped"
        assert (Path(env.cache_root) / "Cache" / "tile").exists()

    def test_cache_cleanup_removes_only_cache_contents(self, tmp_path):
        env = make_env(tmp_path)
        cache_root = Path(env.cache_root)
        protected = cache_root / "Local Storage"
        protected.mkdir()
        (protected / "leveldb").write_bytes(b"personal")
        plan = build_plan(request("cache.browser", "cache.code"), env,
                          registry=FakeRegistry())
        Optimizer(env, registry=FakeRegistry()).apply(plan)
        assert not (cache_root / "Cache" / "tile").exists()
        assert (cache_root / "Cache").is_dir(), "cache directory itself is kept"
        assert (protected / "leveldb").exists(), "personal data must survive"

    def test_rollback_restores_prefs_when_a_later_change_fails(self, tmp_path, monkeypatch):
        env = make_env(tmp_path)
        plan = build_plan(
            request("prefs.hardware_acceleration", "prefs.cache_size"), env,
            registry=FakeRegistry(),
        )
        assert len(plan.changes) == 2

        real_set_values = PrefsManager.set_values
        calls = {"count": 0}

        def flaky(self, updates):
            calls["count"] += 1
            if calls["count"] >= 2:
                return False
            return real_set_values(self, updates)

        monkeypatch.setattr(PrefsManager, "set_values", flaky)
        report = Optimizer(env, registry=FakeRegistry()).apply(plan)

        assert report.rolled_back is True
        assert report.rollback_details
        values = PrefsManager(Path(env.installation.prefs_path)).read_all()
        assert values["hardware_acceleration_mode_enabled"] == "true", \
            "the first change must have been undone"


class TestRestoreConflicts:
    def _prepared_session(self, tmp_path, env):
        from src.core.backup_manager import BackupManager, BackupMetadata
        root = tmp_path / "backups"
        manager = BackupManager(root)
        session = manager.create_session()
        prefs_path = Path(env.installation.prefs_path)
        assert manager.backup_prefs(session, prefs_path)
        manager.write_metadata(session, BackupMetadata(created_at="test"))
        assert manager.write_manifest(session)
        # Pretend the optimisation wrote a value, so the live file now differs
        # from what was recorded.
        manager.update_post_write_hash(session, "prefs", "0" * 64)
        return root, session, prefs_path

    def test_engine_refuses_to_overwrite_newer_preferences(self, tmp_path):
        from src.core.engine import OptimizationEngine
        env = make_env(tmp_path)
        root, session, prefs_path = self._prepared_session(tmp_path, env)
        prefs_path.write_text("hardware_acceleration_mode_enabled=false\n")

        engine = OptimizationEngine(installation=env.installation, backup_root=root)
        result = engine.restore_session(session)

        assert result.conflicts
        assert result.success is False
        assert "false" in prefs_path.read_text(), \
            "conflicting settings must not be overwritten silently"

    def test_engine_restores_when_conflict_is_allowed(self, tmp_path):
        from src.core.engine import OptimizationEngine
        env = make_env(tmp_path)
        root, session, prefs_path = self._prepared_session(tmp_path, env)
        prefs_path.write_text("hardware_acceleration_mode_enabled=false\n")

        engine = OptimizationEngine(installation=env.installation, backup_root=root)
        result = engine.restore_session(session, allow_conflict=True)

        assert not result.conflicts
        assert "true" in prefs_path.read_text()


class TestPlanFormatting:
    def test_describe_mentions_files_and_registry(self, tmp_path):
        env = make_env(tmp_path)
        plan = build_plan(
            request("prefs.hardware_acceleration", "startup.run_entry"), env,
            registry=FakeRegistry(env.startup_entries),
        )
        text = "\n".join(plan.describe())
        assert "hardware_acceleration_mode_enabled" in text
        assert "startup entry 'spotify'" in text.lower()
        assert "prefs" in plan.files_to_modify[0]

    def test_summary_is_human_readable(self, tmp_path):
        env = make_env(tmp_path)
        plan = build_plan(request("cache.browser"), env, registry=FakeRegistry())
        summary = plan.summary()
        assert "planned change" in summary
        assert "Spotify must be closed" in summary
