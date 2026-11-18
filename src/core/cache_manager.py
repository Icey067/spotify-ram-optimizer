"""
Cache inspection and selective cleanup.

Spotify is a Chromium-based application, so it keeps a handful of disposable
caches (HTTP cache, compiled JS cache, shader cache).  This module can report
their size and remove only those directories.

Hard safety rules
-----------------
1. Only a fixed allow-list of relative paths is ever considered.
2. The resolved target must be inside the resolved cache root
   (defeats ``..`` segments, symlinks and junctions pointing elsewhere).
3. Symlinked/junctioned cache directories are reported but never traversed.
4. Personal data directories (login data, cookies, local storage, IndexedDB,
   databases, downloads, user prefs) are protected by name **and** by never
   appearing in the allow-list.
5. The cache root itself is never deleted.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .app_paths import is_within
from .logger import get_logger

log = get_logger("cache")

# Grouped allow-list: group id -> relative directories that are disposable.
CACHE_GROUPS: dict[str, tuple[str, ...]] = {
    "browser": (
        "Cache",
        "Cache_Data",
        "blob_storage",
        Path("Service Worker") / "CacheStorage",
        Path("Service Worker") / "ScriptCache",
    ),
    "code": ("Code Cache",),
    "gpu": ("GPUCache",),
}

GROUP_LABELS: dict[str, str] = {
    "browser": "Web and network cache",
    "code": "Compiled code cache",
    "gpu": "GPU shader cache",
}

GROUP_DESCRIPTIONS: dict[str, str] = {
    "browser": "HTTP tiles and service-worker blobs. Spotify re-downloads them as needed.",
    "code": "Compiled JavaScript bytecode. Regenerated on next start.",
    "gpu": "Shader programs. Regenerated on next start; safe but causes a brief "
           "re-compile on first launch.",
}

SAFE_CACHE_SUBPATHS = [
    str(relative)
    for relatives in CACHE_GROUPS.values()
    for relative in relatives
]

# Names that must never be removed, regardless of allow-list mistakes.
PROTECTED_PATHS = frozenset({
    "prefs",
    "spotify_prefs",
    "Users",
    "storage",
    "Downloads",
    ".lock",
    "Local Storage",
    "Session Storage",
    "Databases",
    "IndexedDB",
    "cookies",
    "Cookies",
    "Network",
    "Login Data",
    "History",
    "Bookmarks",
    "Preferences",
    "Local State",
})

_PROTECTED_LOWER = frozenset(name.lower() for name in PROTECTED_PATHS)


@dataclass
class CacheStats:
    total_bytes_before: int = 0
    total_bytes_after: int = 0
    files_deleted: int = 0
    dirs_cleaned: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def freed_bytes(self) -> int:
        return self.total_bytes_before - self.total_bytes_after

    @property
    def freed_mb(self) -> float:
        return round(self.freed_bytes / (1024 * 1024), 2)


@dataclass(frozen=True)
class CacheDirInfo:
    """One inspectable (and possibly removable) cache directory."""
    group: str
    relative: str
    path: Path
    size_bytes: int
    file_count: int
    eligible: bool
    reason: str = ""


class CacheManager:
    def __init__(self, cache_root: Path) -> None:
        """
        ``cache_root`` is the Spotify data/storage directory, e.g.
        ``%APPDATA%\\Spotify\\Data`` or ``%LOCALAPPDATA%\\Spotify\\Storage``.
        """
        self.cache_root = Path(cache_root)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        return self.cache_root.is_dir()

    def get_cache_size(self, subpath: Optional[str] = None) -> int:
        """Total bytes in ``subpath`` (or the whole cache root)."""
        target = self.cache_root / subpath if subpath else self.cache_root
        if not target.exists():
            return 0
        return _dir_size(target)

    def get_safe_cache_dirs(self) -> list[tuple[str, int]]:
        """Existing allow-listed directories as ``(relative_path, size_bytes)``."""
        result: list[tuple[str, int]] = []
        for relative in SAFE_CACHE_SUBPATHS:
            full = self.cache_root / relative
            if full.is_dir():
                result.append((relative, _dir_size(full)))
        return result

    def inventory(self) -> list[CacheDirInfo]:
        """
        Describe every allow-listed directory that exists, including whether
        it is safe to remove and why not when it is not.
        """
        items: list[CacheDirInfo] = []
        for group, relatives in CACHE_GROUPS.items():
            for relative in relatives:
                relative_str = str(relative)
                full = self.cache_root / relative
                if not full.exists():
                    continue
                eligible, reason = self._validate_target(full)
                items.append(CacheDirInfo(
                    group=group,
                    relative=relative_str,
                    path=full,
                    size_bytes=_dir_size(full),
                    file_count=_count_files(full),
                    eligible=eligible,
                    reason=reason,
                ))
        return items

    def inventory_by_group(self) -> dict[str, list[CacheDirInfo]]:
        grouped: dict[str, list[CacheDirInfo]] = {group: [] for group in CACHE_GROUPS}
        for item in self.inventory():
            grouped[item.group].append(item)
        return grouped

    def eligible_bytes(self, groups: Iterable[str] | None = None) -> int:
        wanted = set(groups) if groups is not None else set(CACHE_GROUPS)
        return sum(
            item.size_bytes
            for item in self.inventory()
            if item.group in wanted and item.eligible
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def clean_cache_dirs(
        self,
        clean_browser_cache: bool = True,
        clean_code_cache: bool = True,
        clean_gpu_cache: bool = True,
    ) -> CacheStats:
        """Clean the selected cache groups (backwards-compatible API)."""
        groups: list[str] = []
        if clean_browser_cache:
            groups.append("browser")
        if clean_code_cache:
            groups.append("code")
        if clean_gpu_cache:
            groups.append("gpu")
        return self.clean_groups(groups)

    def clean_groups(self, groups: Iterable[str]) -> CacheStats:
        """Remove the allow-listed directories inside the selected groups."""
        stats = CacheStats()
        if not self.cache_root.exists():
            log.info(f"Cache root does not exist, nothing to clean: {self.cache_root}")
            return stats

        stats.total_bytes_before = _dir_size(self.cache_root)
        wanted = [group for group in groups if group in CACHE_GROUPS]

        for group in wanted:
            for relative in CACHE_GROUPS[group]:
                target = self.cache_root / relative
                if not target.is_dir():
                    continue
                eligible, reason = self._validate_target(target)
                if not eligible:
                    log.warning(f"Refusing to clean cache directory {target}: {reason}")
                    stats.errors.append(f"Skipped {relative}: {reason}")
                    continue

                log.info(f"Cleaning cache directory: {target}")
                before = stats.files_deleted
                _clean_directory(target, stats)
                if stats.files_deleted > before:
                    stats.dirs_cleaned += 1

        stats.total_bytes_after = _dir_size(self.cache_root)
        log.info(
            f"Cache cleanup done: freed {stats.freed_mb} MB, "
            f"{stats.files_deleted} entries removed, {len(stats.errors)} skipped"
        )
        return stats

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def _validate_target(self, target: Path) -> tuple[bool, str]:
        """Return ``(eligible, reason)`` for a candidate cleanup target."""
        try:
            relative = target.relative_to(self.cache_root)
        except ValueError:
            return False, "path escapes the cache root"

        for part in relative.parts:
            if part.lower() in _PROTECTED_LOWER:
                return False, f"'{part}' is protected personal data"

        if target.is_symlink() or _is_junction(target):
            return False, "symlink or junction (not traversed)"

        if not is_within(target, self.cache_root):
            return False, "resolved path escapes the cache root"

        if target.resolve() == self.cache_root.resolve():
            return False, "cache root itself is never deleted"

        return True, ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except OSError:
        return False


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


def _count_files(path: Path) -> int:
    count = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    count += 1
                elif entry.is_dir(follow_symlinks=False):
                    count += _count_files(Path(entry.path))
            except (OSError, PermissionError):
                pass
    except (OSError, PermissionError):
        pass
    return count


def _clean_directory(directory: Path, stats: CacheStats) -> None:
    """Remove the contents of ``directory`` but keep the directory itself."""
    try:
        for entry in os.scandir(directory):
            entry_path = Path(entry.path)
            try:
                if entry.is_file(follow_symlinks=False):
                    entry_path.unlink()
                    stats.files_deleted += 1
                elif entry.is_symlink():
                    # Remove the link, never follow it.
                    entry_path.unlink()
                    stats.files_deleted += 1
                elif entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry_path, ignore_errors=True)
                    stats.files_deleted += 1
            except OSError as exc:
                stats.errors.append(f"{entry_path.name}: {exc}")
                log.debug(f"Could not delete {entry_path}: {exc}")
    except OSError as exc:
        stats.errors.append(f"{directory}: {exc}")
        log.error(f"Could not scan {directory}: {exc}")
