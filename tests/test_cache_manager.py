"""
Tests for cache manager.

Uses temporary directories — never cleans real Spotify cache.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.cache_manager import CacheManager, _dir_size, PROTECTED_PATHS


class TestCacheManager:
    @pytest.fixture
    def cache_root(self, tmp_path):
        """Create a fake Spotify cache directory structure."""
        root = tmp_path / "SpotifyData"
        root.mkdir()

        # Browser cache
        browser = root / "Cache"
        browser.mkdir()
        (browser / "index").write_bytes(b"x" * 1024)
        (browser / "data_0").write_bytes(b"y" * 2048)

        # Code cache
        code = root / "Code Cache"
        code.mkdir()
        (code / "js" ).write_bytes(b"z" * 512)

        # GPU cache
        gpu = root / "GPUCache"
        gpu.mkdir()
        (gpu / "shader_cache").write_bytes(b"g" * 256)

        # Protected: Local Storage — must NOT be deleted
        ls = root / "Local Storage"
        ls.mkdir()
        (ls / "leveldb").write_bytes(b"p" * 100)

        return root

    def test_get_safe_dirs_lists_existing(self, cache_root):
        mgr = CacheManager(cache_root)
        dirs = mgr.get_safe_cache_dirs()
        names = [d[0] for d in dirs]
        assert "Cache" in names
        assert "Code Cache" in names

    def test_clean_browser_cache(self, cache_root):
        mgr = CacheManager(cache_root)
        stats = mgr.clean_cache_dirs(
            clean_browser_cache=True,
            clean_code_cache=False,
            clean_gpu_cache=False,
        )
        assert stats.files_deleted > 0
        assert stats.freed_mb >= 0
        # Code cache should still exist
        assert (cache_root / "Code Cache").exists()

    def test_clean_code_cache(self, cache_root):
        mgr = CacheManager(cache_root)
        stats = mgr.clean_cache_dirs(
            clean_browser_cache=False,
            clean_code_cache=True,
            clean_gpu_cache=False,
        )
        assert stats.files_deleted > 0

    def test_protected_path_not_deleted(self, cache_root):
        mgr = CacheManager(cache_root)
        mgr.clean_cache_dirs(
            clean_browser_cache=True,
            clean_code_cache=True,
            clean_gpu_cache=True,
        )
        # Local Storage must survive
        assert (cache_root / "Local Storage").exists()

    def test_clean_nothing_selected(self, cache_root):
        mgr = CacheManager(cache_root)
        stats = mgr.clean_cache_dirs(
            clean_browser_cache=False,
            clean_code_cache=False,
            clean_gpu_cache=False,
        )
        assert stats.files_deleted == 0

    def test_missing_cache_root_no_error(self, tmp_path):
        mgr = CacheManager(tmp_path / "NonExistentDir")
        stats = mgr.clean_cache_dirs()
        assert stats.files_deleted == 0

    def test_dir_size(self, tmp_path):
        f = tmp_path / "file.bin"
        f.write_bytes(b"a" * 1000)
        assert _dir_size(tmp_path) == 1000

    def test_freed_bytes_calculated(self, cache_root):
        mgr = CacheManager(cache_root)
        before = _dir_size(cache_root)
        stats = mgr.clean_cache_dirs(
            clean_browser_cache=True,
            clean_code_cache=True,
            clean_gpu_cache=True,
        )
        assert stats.total_bytes_before == before
        assert stats.freed_bytes >= 0
