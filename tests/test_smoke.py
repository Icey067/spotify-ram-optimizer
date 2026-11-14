"""
Tests for standalone smoke test and self-verification runner.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from main import run_smoke_test


def test_smoke_test_runner():
    """Verify that run_smoke_test runs to completion and returns 0."""
    res = run_smoke_test()
    assert res == 0
