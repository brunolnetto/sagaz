"""Runs the interleaved measurement schedule on each backend."""

from __future__ import annotations

import gc
from collections.abc import Callable, Sequence

from benchmarks.tenancy.backends import BackendOptions, BackendSession, open_backend
from benchmarks.tenancy.report import BackendResult
from benchmarks.tenancy.stats import RunResult, paired_overhead, schedule, summarize
from benchmarks.tenancy.workload import COMPARISONS, Mode, Plan, run_once

Progress = Callable[[str], None]


def _quiet(message: str) -> None:
    return None


async def measure(
    session: BackendSession,
    plan: Plan,
    modes: Sequence[Mode],
    rounds: int,
    warmup: int = 1,
    progress: Progress = _quiet,
) -> BackendResult:
    """Warm each mode up, then run ``rounds`` interleaved rounds of all modes.

    Before each run, every live object is moved out of the garbage collector's
    reach (``gc.freeze``): the in-memory store keeps every saga, and scanning
    that growing heap would otherwise slow each run more than the previous one.
    """
    by_name = {mode.name: mode for mode in modes}
    if len(by_name) != len(modes):
        msg = "mode names must be unique"
        raise ValueError(msg)
    try:
        for mode in modes:
            for i in range(warmup):
                await _run(session, plan, mode, -1, f"{mode.name}-w{i}")
        runs: list[RunResult] = []
        for round_, name in schedule(list(by_name), rounds):
            run = await _run(session, plan, by_name[name], round_, f"{name}-r{round_}")
            runs.append(run)
            progress(
                f"{session.name} round {round_ + 1}/{rounds} {name}: "
                f"{run.throughput:,.0f} sagas/s, p50 {run.p50_ms:.1f} ms"
            )
    finally:
        gc.unfreeze()
    return BackendResult(
        backend=session.name,
        info=session.info,
        runs=runs,
        summaries=[summarize([r for r in runs if r.mode == name]) for name in by_name],
        overheads=[
            paired_overhead(runs, mode, reference)
            for mode, reference in COMPARISONS
            if mode in by_name and reference in by_name
        ],
    )


async def _run(session: BackendSession, plan: Plan, mode: Mode, round_: int, label: str):
    await session.prepare(mode)
    gc.collect()
    gc.freeze()
    return await run_once(session.storage, plan, mode, round_, label)


async def run_benchmark(
    backends: Sequence[str],
    options: BackendOptions,
    plan: Plan,
    modes: Sequence[Mode],
    rounds: int,
    warmup: int = 1,
    ablation_modes: Sequence[Mode] = (),
    progress: Progress = _quiet,
) -> list[BackendResult]:
    """Measure every backend in turn; ablation modes only where supported."""
    results = []
    for name in backends:
        async with open_backend(name, options) as session:
            extra = list(ablation_modes) if session.supports_ablations else []
            results.append(await measure(session, plan, [*modes, *extra], rounds, warmup, progress))
    return results
