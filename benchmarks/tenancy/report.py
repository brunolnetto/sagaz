"""Benchmark results as Markdown tables and JSON."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.tenancy.machinery import MachineryCost
from benchmarks.tenancy.stats import ModeSummary, Overhead, RunResult


@dataclass
class BackendResult:
    backend: str
    info: dict[str, Any]
    runs: list[RunResult]
    summaries: list[ModeSummary]
    overheads: list[Overhead]


@dataclass
class Report:
    config: dict[str, Any]
    environment: dict[str, Any]
    backends: list[BackendResult] = field(default_factory=list)
    machinery: MachineryCost | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json() + "\n")


def _total_memory_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def environment_info() -> dict[str, Any]:
    """Machine, interpreter and sagaz commit the benchmark ran on."""
    uname = platform.uname()
    return {
        "uname": " ".join([uname.system, uname.node, uname.release, uname.version, uname.machine]),
        "cpus": os.cpu_count(),
        "memory_mb": _total_memory_mb(),
        "python": sys.version.split()[0],
        "sagaz_commit": _git_commit(),
        "loadavg": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
    }


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def overhead_cell(overhead: Overhead | None) -> str:
    if overhead is None:
        return "-"
    return f"{_pct(overhead.median_pct)} [{_pct(overhead.min_pct)}, {_pct(overhead.max_pct)}]"


def results_table(results: list[BackendResult]) -> str:
    """One row per backend and mode, with the overhead over the same backend's baseline."""
    lines = [
        "| Backend | Mode | Sagas/s (median) | Sagas/s range | p50 ms | p95 ms | p99 ms "
        "| Overhead vs baseline (median [min, max]) |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        overheads = {o.mode: o for o in result.overheads if o.reference == "baseline"}
        for s in result.summaries:
            lines.append(
                f"| {result.backend} | {s.mode} | {s.throughput:,.0f} "
                f"| {s.throughput_min:,.0f}-{s.throughput_max:,.0f} "
                f"| {s.p50_ms:.1f} | {s.p95_ms:.1f} | {s.p99_ms:.1f} "
                f"| {overhead_cell(overheads.get(s.mode))} |"
            )
    return "\n".join(lines)


def comparisons_table(results: list[BackendResult]) -> str:
    """Every reported overhead, including the PostgreSQL ablations."""
    lines = [
        "| Backend | Mode | Reference | Overhead (median [min, max] over rounds) |",
        "|---|---|---|---|",
    ]
    for result in results:
        lines.extend(
            f"| {result.backend} | {o.mode} | {o.reference} | {overhead_cell(o)} |"
            for o in result.overheads
        )
    return "\n".join(lines)


def machinery_lines(report: Report) -> str:
    """The tenancy wrapper's cost per saga, and its share of each backend's saga time.

    A backend's time per saga is ``1 / throughput`` of its baseline: the wall
    time the whole run spends per saga, with all workers in flight.
    """
    cost = report.machinery
    if cost is None:
        return "Tenancy machinery: not measured"
    lines = [
        f"Tenancy machinery per saga: {cost.context_us:.1f} µs with a TenantContext, "
        f"{cost.registry_us:.1f} µs with a registry id (best of runs, "
        f"{cost.iterations:,} iterations)"
    ]
    for result in report.backends:
        baseline = next((s for s in result.summaries if s.mode == "baseline"), None)
        if baseline is not None:
            per_saga_us = 1e6 / baseline.throughput
            lines.append(
                f"- {result.backend}: {per_saga_us:,.0f} µs per saga in the baseline, "
                f"machinery share {cost.context_us / per_saga_us * 100:.2f}%"
            )
    return "\n".join(lines)


def render(report: Report) -> str:
    """The full Markdown report: configuration, environment, tables and machinery cost."""
    config = ", ".join(f"{key}={value}" for key, value in report.config.items())
    environment = ", ".join(f"{key}={value}" for key, value in report.environment.items())
    backend_info = "\n".join(
        f"- {result.backend}: "
        + (", ".join(f"{key}={value}" for key, value in result.info.items()) or "-")
        for result in report.backends
    )
    return "\n\n".join(
        [
            f"Configuration: {config}",
            f"Environment: {environment}",
            backend_info,
            results_table(report.backends),
            comparisons_table(report.backends),
            machinery_lines(report),
        ]
    )
