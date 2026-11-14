"""Measurement records, percentiles, overheads and the interleaved run schedule."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass


def percentile(values: Sequence[float], q: float) -> float:
    """The ``q``-th percentile (0-100) of ``values``, linearly interpolated."""
    if not values:
        msg = "percentile of an empty sequence"
        raise ValueError(msg)
    if not 0 <= q <= 100:
        msg = f"percentile must be within 0-100, got {q}"
        raise ValueError(msg)
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q / 100
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


@dataclass(frozen=True)
class RunResult:
    """One measured run of one mode: every saga of the plan, all started together."""

    mode: str
    round: int
    sagas: int
    wall_seconds: float
    p50_ms: float
    p95_ms: float
    p99_ms: float

    @property
    def throughput(self) -> float:
        """Completed sagas per second of wall time."""
        return self.sagas / self.wall_seconds

    @classmethod
    def from_latencies(
        cls, mode: str, round_: int, latencies: Sequence[float], wall_seconds: float
    ) -> RunResult:
        """Summarize per-saga latencies (seconds) of one run."""
        return cls(
            mode=mode,
            round=round_,
            sagas=len(latencies),
            wall_seconds=wall_seconds,
            p50_ms=percentile(latencies, 50) * 1000,
            p95_ms=percentile(latencies, 95) * 1000,
            p99_ms=percentile(latencies, 99) * 1000,
        )


@dataclass(frozen=True)
class ModeSummary:
    """Median over the measured runs of one mode (and the spread of throughput)."""

    mode: str
    runs: int
    throughput: float
    throughput_min: float
    throughput_max: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


@dataclass(frozen=True)
class Overhead:
    """How much slower ``mode`` is than ``reference``, paired round by round.

    Overhead is the extra wall time for the same sagas, in percent:
    ``wall(mode) / wall(reference) - 1``. Pairing runs of the same round cancels
    most slow drift of machine load; the median and range are over rounds.
    """

    mode: str
    reference: str
    median_pct: float
    min_pct: float
    max_pct: float


def summarize(runs: Sequence[RunResult]) -> ModeSummary:
    """Median throughput and latencies of runs of a single mode."""
    if not runs:
        msg = "no runs to summarize"
        raise ValueError(msg)
    modes = {run.mode for run in runs}
    if len(modes) != 1:
        msg = f"runs of several modes: {sorted(modes)}"
        raise ValueError(msg)
    throughputs = [run.throughput for run in runs]
    return ModeSummary(
        mode=runs[0].mode,
        runs=len(runs),
        throughput=statistics.median(throughputs),
        throughput_min=min(throughputs),
        throughput_max=max(throughputs),
        p50_ms=statistics.median(run.p50_ms for run in runs),
        p95_ms=statistics.median(run.p95_ms for run in runs),
        p99_ms=statistics.median(run.p99_ms for run in runs),
    )


def paired_overhead(runs: Sequence[RunResult], mode: str, reference: str) -> Overhead:
    """Overhead of ``mode`` over ``reference`` from runs of the same rounds."""
    walls: dict[tuple[str, int], float] = {(run.mode, run.round): run.wall_seconds for run in runs}
    rounds = sorted({r for m, r in walls if m == mode} & {r for m, r in walls if m == reference})
    if not rounds:
        msg = f"no round has both '{mode}' and '{reference}'"
        raise ValueError(msg)
    pcts = [(walls[mode, r] / walls[reference, r] - 1) * 100 for r in rounds]
    return Overhead(
        mode=mode,
        reference=reference,
        median_pct=statistics.median(pcts),
        min_pct=min(pcts),
        max_pct=max(pcts),
    )


def schedule(modes: Sequence[str], rounds: int) -> list[tuple[int, str]]:
    """``(round, mode)`` pairs, the mode order rotated each round.

    Every round runs each mode once, back to back, so paired runs see nearly the
    same machine load. Rotating the order (AB, BA, AB, ... for two modes) keeps
    any mode from always running first, when caches are coldest.
    """
    if rounds < 1:
        msg = f"rounds must be >= 1, got {rounds}"
        raise ValueError(msg)
    if not modes:
        msg = "no modes to schedule"
        raise ValueError(msg)
    plan: list[tuple[int, str]] = []
    for round_ in range(rounds):
        shift = round_ % len(modes)
        plan.extend((round_, mode) for mode in [*modes[shift:], *modes[:shift]])
    return plan
