"""
Cache cleanup module.

Cleans Spotify's Chromium-based cache directories safely.
Never deletes personal data (playlists, downloads, login info).

Safe-to-clean directories inside Spotify's cache root:
  - Cache / Cache_Data          (browser tile / HTTP cache)
  - Code Cache                  (compiled JavaScript)
  - GPUCache                    (GPU shader cache)
  - blob_storage/*              (temporary blobs, usually safe)
  - Service Worker/CacheStorage (service worker cache)
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .logger import get_logger

log = get_logger("cache")

# Sub-paths that are safe to clean, relative to the Spotify Data root
SAFE_CACHE_SUBPATHS = [
    "Cache",
    "Cache_Data",
    "Code Cache",
    "GPUCache",
    "blob_storage",
    Path("Service Worker") / "CacheStorage",
    Path("Service Worker") / "ScriptCache",
]

# Paths that must NEVER be deleted
PROTECTED_PATHS = {
    "prefs",
    "spotify_prefs",
    "Users",
    "storage",
    "Downloads",
    ".lock",
    "Local Storage",
    "Databases",
    "IndexedDB",
    "cookies",
    "Login Data",
    "History",
    "Bookmarks",
}


@dataclass
class CacheStats:
    total_bytes_before: int = 0
    total_bytes_after: int = 0
    files_deleted: int = 0
    dirs_cleaned: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def freed_bytes(self) -> int:
        return self.total_bytes_before - self.total_bytes_after

    @property
    def freed_mb(self) -> float:
        return round(self.freed_bytes / (1024 * 1024), 2)


class CacheManager:
    def __init__(self, cache_root: Path) -> None:
        """
        cache_root should be the Spotify Data directory
        (e.g. %APPDATA%\\Spotify\\Data or %LOCALAPPDATA%\\Spotify\\Storage).
        """
        self.cache_root = cache_root

    def get_cache_size(self, subpath: Optional[str] = None) -> int:
        """Return total bytes in the given sub-directory (or entire cache root)."""
        target = self.cache_root / subpath if subpath else self.cache_root
        if not target.exists():
            return 0
        return _dir_size(target)

    def get_safe_cache_dirs(self) -> list[tuple[str, int]]:
        """
        Return list of (relative_path, size_bytes) for each safe-to-clean directory.
        Only returns directories that actually exist.
        """
        result = []
        for rel in SAFE_CACHE_SUBPATHS:
            full = self.cache_root / rel
            if full.exists():
                size = _dir_size(full)
                result.append((str(rel), size))
        return result

    def clean_cache_dirs(
        self,
        clean_browser_cache: bool = True,
        clean_code_cache: bool = True,
        clean_gpu_cache: bool = True,
    ) -> CacheStats:
        """
        Clean selected cache directories.
        Returns a CacheStats summary.
        """
        stats = CacheStats()
        stats.total_bytes_before = _dir_size(self.cache_root) if self.cache_root.exists() else 0

        targets: list[Path] = []
        if clean_browser_cache:
            targets += [
                self.cache_root / "Cache",
                self.cache_root / "Cache_Data",
                self.cache_root / "blob_storage",
                self.cache_root / "Service Worker" / "CacheStorage",
                self.cache_root / "Service Worker" / "ScriptCache",
            ]
        if clean_code_cache:
            targets.append(self.cache_root / "Code Cache")
        if clean_gpu_cache:
            targets.append(self.cache_root / "GPUCache")

        for target in targets:
            if not target.exists():
                continue
            # Safety check: never clean protected names
            if target.name in PROTECTED_PATHS:
                log.warning(f"Refusing to clean protected path: {target}")
                stats.errors.append(f"Skipped protected: {target.name}")
                continue
            # Safety check: must be under known Spotify data directory
            try:
                target.relative_to(self.cache_root)
            except ValueError:
                log.warning(f"Path escapes cache root, skipping: {target}")
                continue

            log.info(f"Cleaning cache directory: {target}")
            count_before = stats.files_deleted
            _clean_directory(target, stats)
            if stats.files_deleted > count_before:
                stats.dirs_cleaned += 1

        stats.total_bytes_after = _dir_size(self.cache_root) if self.cache_root.exists() else 0
        log.info(
            f"Cache cleanup done: freed {stats.freed_mb} MB, "
            f"{stats.files_deleted} files deleted, {len(stats.errors)} errors"
        )
        return stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dir_size(path: Path) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _dir_size(Path(entry.path))
            except (OSError, PermissionError):
                pass
    except (OSError, PermissionError):
        pass
    return total


def _clean_directory(directory: Path, stats: CacheStats) -> None:
    """Remove all files in directory; leave the directory itself."""
    try:
        for entry in os.scandir(directory):
            ep = Path(entry.path)
            try:
                if entry.is_file(follow_symlinks=False):
                    ep.unlink()
                    stats.files_deleted += 1
                elif entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(ep, ignore_errors=True)
                    stats.files_deleted += 1
            except Exception as e:
                stats.errors.append(f"{ep.name}: {e}")
                log.debug(f"Could not delete {ep}: {e}")
    except Exception as e:
        stats.errors.append(f"{directory}: {e}")
        log.error(f"Could not scan {directory}: {e}")
