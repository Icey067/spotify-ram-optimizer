"""
Performance snapshots and comparisons.

A snapshot is a *measurement*, not a claim.  Comparisons carry an explicit
``comparable`` flag and notes explaining when two measurements must not be
subtracted from each other (for example when Spotify was closed for the
"after" reading).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .benchmark import BenchmarkResult
from .logger import get_logger
from .process_manager import get_process_snapshot, get_spotify_processes

log = get_logger("perf")


@dataclass
class PerformanceSnapshot:
    timestamp: str
    process_count: int
    total_memory_mb: float
    per_process: list[dict] = field(default_factory=list)
    label: str = ""
    cpu_percent: float = 0.0
    private_mb: Optional[float] = None
    source: str = "instant"

    @staticmethod
    def capture(label: str = "") -> "PerformanceSnapshot":
        """One instantaneous reading (cheap; used for live UI updates)."""
        processes = get_spotify_processes()
        per_process = []
        total = 0.0
        cpu = 0.0
        for proc in processes:
            snapshot = get_process_snapshot(proc)
            if snapshot:
                per_process.append({
                    "pid": snapshot.pid,
                    "name": snapshot.name,
                    "memory_mb": snapshot.memory_mb,
                    "cpu_percent": snapshot.cpu_percent,
                })
                total += snapshot.memory_mb
                cpu += snapshot.cpu_percent

        return PerformanceSnapshot(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            process_count=len(processes),
            total_memory_mb=round(total, 2),
            per_process=per_process,
            label=label,
            cpu_percent=round(cpu, 2),
            source="instant",
        )

    @staticmethod
    def from_benchmark(result: BenchmarkResult, label: str = "") -> "PerformanceSnapshot":
        """Convert a sampled benchmark into a snapshot."""
        return PerformanceSnapshot(
            timestamp=result.started_at or datetime.now().strftime("%H:%M:%S"),
            process_count=result.process_count,
            total_memory_mb=result.working_set_mb or 0.0,
            per_process=[],
            label=label or result.label,
            cpu_percent=result.cpu_mean or 0.0,
            private_mb=result.private_mb,
            source="sampled",
        )

    def summary(self) -> str:
        if self.process_count == 0:
            return f"[{self.label}] Spotify not running"
        return (
            f"[{self.label}] {self.process_count} process(es), "
            f"{self.total_memory_mb:.1f} MB working set"
        )


@dataclass
class PerformanceComparison:
    before: PerformanceSnapshot
    after: PerformanceSnapshot
    operations_completed: int = 0
    operations_skipped: int = 0
    comparable: Optional[bool] = None
    notes: list[str] = field(default_factory=list)
    cache_freed_mb: float = 0.0

    def __post_init__(self) -> None:
        # Two zero readings are not a comparison. Only claim comparability when
        # Spotify was actually running for both measurements.
        if self.comparable is None:
            self.comparable = (self.before.process_count > 0
                               and self.after.process_count > 0)

    @property
    def memory_delta_mb(self) -> float:
        return round(self.after.total_memory_mb - self.before.total_memory_mb, 2)

    @property
    def memory_freed_mb(self) -> float:
        return round(self.before.total_memory_mb - self.after.total_memory_mb, 2)

    def report(self) -> dict:
        return {
            "before_mb": self.before.total_memory_mb,
            "after_mb": self.after.total_memory_mb,
            "delta_mb": self.memory_delta_mb,
            "freed_mb": self.memory_freed_mb,
            "before_processes": self.before.process_count,
            "after_processes": self.after.process_count,
            "before_cpu": self.before.cpu_percent,
            "after_cpu": self.after.cpu_percent,
            "cache_freed_mb": self.cache_freed_mb,
            "operations_completed": self.operations_completed,
            "operations_skipped": self.operations_skipped,
            "comparable": self.comparable,
            "notes": list(self.notes),
            "note": (
                "Working-set readings are approximate and vary with Spotify version, "
                "playback state and system activity. A difference is not proof that an "
                "optimisation caused it."
            ),
        }
