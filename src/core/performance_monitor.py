"""
Performance monitor.

Measures Spotify memory usage before and after optimization.
Displays process count, RSS, and meaningful context.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psutil

from .process_manager import get_spotify_processes, get_process_snapshot
from .logger import get_logger

log = get_logger("perf")


@dataclass
class PerformanceSnapshot:
    timestamp: str
    process_count: int
    total_memory_mb: float
    per_process: list[dict]
    label: str = ""

    @staticmethod
    def capture(label: str = "") -> "PerformanceSnapshot":
        processes = get_spotify_processes()
        per_proc = []
        total = 0.0
        for p in processes:
            snap = get_process_snapshot(p)
            if snap:
                per_proc.append({
                    "pid": snap.pid,
                    "name": snap.name,
                    "memory_mb": snap.memory_mb,
                    "cpu_percent": snap.cpu_percent,
                })
                total += snap.memory_mb

        return PerformanceSnapshot(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            process_count=len(processes),
            total_memory_mb=round(total, 2),
            per_process=per_proc,
            label=label,
        )

    def summary(self) -> str:
        if self.process_count == 0:
            return f"[{self.label}] Spotify not running"
        return (
            f"[{self.label}] {self.process_count} process(es), "
            f"{self.total_memory_mb:.1f} MB total"
        )


@dataclass
class PerformanceComparison:
    before: PerformanceSnapshot
    after: PerformanceSnapshot
    operations_completed: int = 0
    operations_skipped: int = 0

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
            "operations_completed": self.operations_completed,
            "operations_skipped": self.operations_skipped,
            "note": (
                "Memory readings are approximate and vary with Spotify version, "
                "playback state, and system activity."
            ),
        }
