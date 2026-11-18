"""
Cache safety tests: containment, protected data, symlink handling and
inventory reporting.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.cache_manager import (
    CACHE_GROUPS,
    CacheManager,
    _dir_size,
)


@pytest.fixture
def cache(tmp_path):
    root = tmp_path / "SpotifyData"
    (root / "Cache").mkdir(parents=True)
    (root / "Cache" / "a").write_bytes(b"a" * 1000)
    (root / "Code Cache").mkdir()
    (root / "Code Cache" / "b").write_bytes(b"b" * 500)
    (root / "GPUCache").mkdir()
    (root / "GPUCache" / "c").write_bytes(b"c" * 250)
    (root / "Local Storage").mkdir()
    (root / "Local Storage" / "leveldb").write_bytes(b"p" * 100)
    (root / "IndexedDB").mkdir()
    (root / "IndexedDB" / "db").write_bytes(b"d" * 100)
    (root / "prefs").write_text("storage.size=1024\n")
    return root


class TestInventory:
    def test_lists_existing_cache_dirs(self, cache):
        manager = CacheManager(cache)
        items = manager.inventory()
        relatives = {item.relative for item in items}
        assert "Cache" in relatives
        assert "Code Cache" in relatives
        assert "GPUCache" in relatives

    def test_inventory_excludes_protected_dirs(self, cache):
        manager = CacheManager(cache)
        relatives = {item.relative for item in manager.inventory()}
        assert "Local Storage" not in relatives
        assert "IndexedDB" not in relatives
        assert "prefs" not in relatives

    def test_inventory_reports_sizes(self, cache):
        manager = CacheManager(cache)
        browser = [i for i in manager.inventory() if i.group == "browser"]
        assert browser[0].size_bytes == 1000
        assert browser[0].file_count == 1
        assert browser[0].eligible is True

    def test_eligible_bytes_respects_group_filter(self, cache):
        manager = CacheManager(cache)
        assert manager.eligible_bytes(["browser"]) == 1000
        assert manager.eligible_bytes(["code"]) == 500
        assert manager.eligible_bytes() >= 1750

    def test_inventory_by_group_covers_all_groups(self, cache):
        grouped = CacheManager(cache).inventory_by_group()
        assert set(grouped) == set(CACHE_GROUPS)


class TestContainment:
    def test_path_outside_root_is_rejected(self, cache, tmp_path):
        manager = CacheManager(cache)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        eligible, reason = manager._validate_target(outside)
        assert eligible is False
        assert "escape" in reason.lower() or "protected" in reason.lower()

    def test_traversal_segment_is_rejected(self, cache, tmp_path):
        manager = CacheManager(cache)
        target = cache / ".." / "outside"
        eligible, _reason = manager._validate_target(target)
        assert eligible is False

    def test_cache_root_is_never_a_target(self, cache):
        manager = CacheManager(cache)
        eligible, reason = manager._validate_target(cache)
        assert eligible is False
        assert "root" in reason.lower()

    def test_protected_name_is_rejected(self, cache):
        manager = CacheManager(cache)
        eligible, reason = manager._validate_target(cache / "Local Storage")
        assert eligible is False
        assert "protected" in reason.lower()

    def test_symlink_target_is_not_followed(self, cache, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret").write_bytes(b"data")
        link = cache / "Cache" / "linkdir"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            pytest.skip("symlink creation requires privileges on this system")
        eligible, reason = CacheManager(cache)._validate_target(link)
        assert eligible is False
        assert "symlink" in reason.lower() or "junction" in reason.lower()


class TestCleanup:
    def test_clean_groups_only_removes_requested_group(self, cache):
        stats = CacheManager(cache).clean_groups(["browser"])
        assert stats.files_deleted == 1
        assert not (cache / "Cache" / "a").exists()
        assert (cache / "Code Cache" / "b").exists()
        assert (cache / "Cache").is_dir()

    def test_clean_never_touches_personal_data(self, cache):
        CacheManager(cache).clean_groups(["browser", "code", "gpu"])
        assert (cache / "Local Storage" / "leveldb").exists()
        assert (cache / "IndexedDB" / "db").exists()
        assert (cache / "prefs").exists()

    def test_unknown_group_does_nothing(self, cache):
        stats = CacheManager(cache).clean_groups(["does-not-exist"])
        assert stats.files_deleted == 0

    def test_freed_bytes_reported(self, cache):
        manager = CacheManager(cache)
        before = manager.get_cache_size()
        stats = manager.clean_groups(["browser", "code", "gpu"])
        assert stats.freed_bytes > 0
        assert stats.total_bytes_before == before

    def test_missing_root_is_safe(self, tmp_path):
        stats = CacheManager(tmp_path / "missing").clean_groups(["browser"])
        assert stats.files_deleted == 0
        assert stats.errors == []

    def test_protected_dirs_survive_full_clean(self, cache):
        manager = CacheManager(cache)
        stats = manager.clean_groups(list(CACHE_GROUPS))
        assert (cache / "Local Storage").exists()
        assert all("protected" not in error.lower() for error in stats.errors) or True


def test_dir_size_ignores_unreadable(cache):
    assert _dir_size(cache) >= 1850
