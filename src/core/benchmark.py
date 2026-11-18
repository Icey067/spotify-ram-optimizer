"""
Sampling-based Spotify benchmark.

Why sampling
------------
A single ``memory_info()`` reading is noise.  This module samples over a
configurable interval and reports the **mean working set**, **mean private
memory** (when the OS exposes it), and **mean/maximum CPU** measured from
per-process deltas — never from a one-shot ``cpu_percent()`` which always
returns 0.0 the first time it is called.

Honesty rules
-------------
* Measurements are only *comparable* when Spotify was running for both
  measurements with the same process count range and version.
* A "freed memory" number is never produced when Spotify was stopped: the
  comparison reports ``comparable=False`` and explains why.
* Nothing here writes to disk or modifies Spotify.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import psutil

from .cache_manager import CacheManager
from .logger import get_logger
from .process_manager import get_spotify_processes

log = get_logger("benchmark")

ProgressCallback = Callable[[str, float], None]


@dataclass
class Sample:
    ts: float
    working_set_mb: float
    private_mb: Optional[float]
    cpu_percent: float
    process_count: int


@dataclass
class BenchmarkResult:
    label: str = ""
    started_at: str = ""
    duration_seconds: float = 0.0
    sample_count: int = 0
    spotify_running: bool = False
    process_count: int = 0
    working_set_mb: Optional[float] = None
    private_mb: Optional[float] = None
    cpu_mean: Optional[float] = None
    cpu_max: Optional[float] = None
    cache_bytes: int = 0
    spotify_version: Optional[str] = None
    uptime_seconds: Optional[float] = None
    notes: list[str] = field(default_factory=list)
    samples: list[Sample] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "started_at": self.started_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "sample_count": self.sample_count,
            "spotify_running": self.spotify_running,
            "process_count": self.process_count,
            "working_set_mb": self.working_set_mb,
            "private_mb": self.private_mb,
            "cpu_mean": self.cpu_mean,
            "cpu_max": self.cpu_max,
            "cache_bytes": self.cache_bytes,
            "spotify_version": self.spotify_version,
            "uptime_seconds": self.uptime_seconds,
            "notes": list(self.notes),
        }

    def summary(self) -> str:
        if not self.spotify_running:
            return f"[{self.label}] Spotify is not running"
        parts = [f"{self.process_count} process(es)",
                 f"{self.working_set_mb:.1f} MB working set"]
        if self.cpu_mean is not None:
            parts.append(f"{self.cpu_mean:.1f}% CPU")
        return f"[{self.label}] " + ", ".join(parts)


def _spotify_uptime() -> Optional[float]:
    """Uptime of the oldest Spotify process, in seconds."""
    oldest = None
    for proc in get_spotify_processes():
        try:
            created = proc.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if oldest is None or created < oldest:
            oldest = created
    if oldest is None:
        return None
    return max(0.0, time.time() - oldest)


def measure(
    *,
    label: str = "",
    duration: float = 3.0,
    interval: float = 0.5,
    cache_root: Optional[Path] = None,
    spotify_version: Optional[str] = None,
    progress: Optional[ProgressCallback] = None,
) -> BenchmarkResult:
    """
    Sample Spotify for ``duration`` seconds.

    Never raises for missing processes — a result with
    ``spotify_running=False`` is returned instead.
    """
    result = BenchmarkResult(
        label=label,
        started_at=datetime.now().isoformat(timespec="seconds"),
        spotify_version=spotify_version,
    )
    duration = max(0.5, float(duration))
    interval = max(0.1, min(float(interval), duration))

    if cache_root is not None:
        manager = CacheManager(cache_root)
        if manager.exists():
            result.cache_bytes = manager.get_cache_size()

    processes = get_spotify_processes()
    if not processes:
        result.notes.append(
            "Spotify is not running, so no memory or CPU measurement was taken."
        )
        result.duration_seconds = 0.0
        return result

    # Prime CPU counters so the first delta is meaningful.
    for proc in processes:
        try:
            proc.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    samples: list[Sample] = []
    start = time.monotonic()
    deadline = start + duration
    last_emit = 0.0

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
        now = time.monotonic()
        working = 0.0
        private = 0.0
        private_ok = False
        cpu = 0.0
        count = 0

        for proc in get_spotify_processes():
            try:
                with proc.oneshot():
                    working += proc.memory_info().rss
                    try:
                        private += proc.memory_full_info().uss
                        private_ok = True
                    except (psutil.AccessDenied, AttributeError, NotImplementedError):
                        pass
                    cpu += proc.cpu_percent(None)
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if count == 0:
            result.notes.append("Spotify exited during the measurement.")
            break

        samples.append(Sample(
            ts=time.time(),
            working_set_mb=round(working / (1024 * 1024), 2),
            private_mb=round(private / (1024 * 1024), 2) if private_ok else None,
            cpu_percent=round(cpu, 2),
            process_count=count,
        ))

        if progress and duration > 0:
            elapsed = now - start
            if elapsed - last_emit >= 0.25:
                progress("Measuring Spotify…", min(1.0, elapsed / duration))
                last_emit = elapsed

    result.duration_seconds = round(time.monotonic() - start, 2)
    result.samples = samples
    result.sample_count = len(samples)
    result.spotify_running = bool(samples)
    result.uptime_seconds = _spotify_uptime()

    if samples:
        result.process_count = samples[-1].process_count
        result.working_set_mb = round(
            sum(s.working_set_mb for s in samples) / len(samples), 2
        )
        private_values = [s.private_mb for s in samples if s.private_mb is not None]
        result.private_mb = (
            round(sum(private_values) / len(private_values), 2)
            if private_values else None
        )
        cpus = [s.cpu_percent for s in samples]
        result.cpu_mean = round(sum(cpus) / len(cpus), 2)
        result.cpu_max = round(max(cpus), 2)
        if result.sample_count < 3:
            result.notes.append(
                "Fewer than three samples were collected; treat the numbers as rough."
            )

    log.info(result.summary())
    return result


def compare(before: BenchmarkResult, after: BenchmarkResult) -> dict:
    """
    Compare two measurements without inventing a causal claim.

    Returns a dict with deltas and an explicit ``comparable`` flag plus a note
    explaining the limitation.
    """
    notes: list[str] = []

    comparable = (
        before.spotify_running
        and after.spotify_running
        and before.working_set_mb is not None
        and after.working_set_mb is not None
    )
    if not before.spotify_running:
        notes.append("'Before' measurement had Spotify closed.")
    if not after.spotify_running:
        notes.append(
            "'After' measurement had Spotify closed (for example because "
            "optimisation stopped it), so memory cannot be compared."
        )
    if before.spotify_version and after.spotify_version and \
            before.spotify_version != after.spotify_version:
        notes.append("Spotify version changed between measurements.")
    if comparable and before.process_count and after.process_count and \
            abs(before.process_count - after.process_count) >= 3:
        notes.append(
            f"Process count changed from {before.process_count} to "
            f"{after.process_count}; the comparison is affected."
        )

    delta_ws = None
    delta_private = None
    delta_cpu = None
    noise = False
    if comparable:
        delta_ws = round(after.working_set_mb - before.working_set_mb, 2)
        if before.working_set_mb and abs(delta_ws) / before.working_set_mb < 0.05:
            noise = True
            notes.append(
                "The working-set difference is under 5% and is within normal "
                "run-to-run variance; do not read it as an optimisation effect."
            )
        if before.private_mb is not None and after.private_mb is not None:
            delta_private = round(after.private_mb - before.private_mb, 2)
        if before.cpu_mean is not None and after.cpu_mean is not None:
            delta_cpu = round(after.cpu_mean - before.cpu_mean, 2)
    if not notes:
        notes.append(
            "Differences reflect this machine at this moment; they are not a "
            "guarantee of future performance."
        )

    return {
        "comparable": comparable,
        "before_mb": before.working_set_mb,
        "after_mb": after.working_set_mb,
        "delta_mb": delta_ws,
        "delta_private_mb": delta_private,
        "delta_cpu": delta_cpu,
        "within_noise": noise,
        "before": before.to_dict(),
        "after": after.to_dict(),
        "notes": notes,
    }
