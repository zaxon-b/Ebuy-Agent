"""Unbiased pass@k and observed all-runs-pass stability metrics."""

from __future__ import annotations

import math


def pass_at_k(n: int, c: int, k: int) -> float:
    if min(n, c, k) < 0 or c > n:
        raise ValueError("require 0 <= c <= n and k >= 0")
    if k == 0:
        return 1.0
    if n < k:
        raise ValueError("n must be >= k")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def aggregate_pass_at_k(task_runs: dict[str, list[bool]], k: int) -> float:
    if not task_runs:
        return 0.0
    values = [pass_at_k(len(runs), sum(runs), k) for runs in task_runs.values()]
    return sum(values) / len(values)


def observed_pass_power_k(task_runs: dict[str, list[bool]], k: int) -> float:
    """Fraction of tasks whose first k observed runs all passed."""
    eligible = [runs[:k] for runs in task_runs.values() if len(runs) >= k]
    if not eligible:
        return 0.0
    return sum(all(runs) for runs in eligible) / len(eligible)
