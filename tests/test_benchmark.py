"""
Benchmark honesty tests.

These use fabricated results for the comparison logic, and one real (very
short) measurement whose assertions are environment-independent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core.benchmark import BenchmarkResult, compare, measure


def result(*, running=True, working=500.0, private=300.0, cpu=2.0,
           count=4, version="1.2.3") -> BenchmarkResult:
    return BenchmarkResult(
        label="test",
        spotify_running=running,
        process_count=count if running else 0,
        working_set_mb=working if running else 0.0,
        private_mb=private if running else None,
        cpu_mean=cpu if running else None,
        cpu_max=cpu if running else None,
        spotify_version=version,
        sample_count=6 if running else 0,
        duration_seconds=3.0 if running else 0.0,
    )


class TestCompare:
    def test_comparable_when_both_running(self):
        data = compare(result(), result(working=450.0))
        assert data["comparable"] is True
        assert data["delta_mb"] == -50.0

    def test_not_comparable_when_after_closed(self):
        data = compare(result(), result(running=False, working=0.0))
        assert data["comparable"] is False
        assert data["delta_mb"] is None
        assert any("cannot be compared" in note for note in data["notes"])

    def test_not_comparable_when_before_closed(self):
        data = compare(result(running=False), result())
        assert data["comparable"] is False
        assert data["before_mb"] == 0.0

    def test_small_difference_is_flagged_as_noise(self):
        data = compare(result(working=500.0), result(working=495.0))
        assert data["comparable"] is True
        assert data["within_noise"] is True
        assert any("variance" in note for note in data["notes"])

    def test_version_change_is_noted(self):
        data = compare(result(version="1.0"), result(version="1.1"))
        assert any("version changed" in note for note in data["notes"])

    def test_process_count_change_is_noted(self):
        data = compare(result(count=4), result(count=12))
        assert any("Process count changed" in note for note in data["notes"])

    def test_report_always_contains_measurements(self):
        data = compare(result(), result(working=400.0))
        assert data["before"]["working_set_mb"] == 500.0
        assert data["after"]["working_set_mb"] == 400.0
        assert data["delta_private_mb"] is not None


class TestMeasure:
    def test_measure_returns_structured_result(self, tmp_path):
        result_value = measure(label="unit", duration=0.6, interval=0.2,
                              cache_root=tmp_path)
        assert result_value.label == "unit"
        assert result_value.duration_seconds >= 0
        if result_value.spotify_running:
            assert result_value.sample_count >= 1
            assert result_value.working_set_mb is not None
            assert result_value.working_set_mb > 0
            assert result_value.cpu_mean is not None
        else:
            assert result_value.notes, "a missing measurement must explain itself"
            assert result_value.working_set_mb is None

    def test_measure_never_raises_without_cache(self):
        result_value = measure(duration=0.5, interval=0.25, cache_root=None)
        assert isinstance(result_value, BenchmarkResult)

    def test_duration_is_bounded(self):
        result_value = measure(duration=2.0, interval=0.5)
        assert result_value.duration_seconds < 6.0
