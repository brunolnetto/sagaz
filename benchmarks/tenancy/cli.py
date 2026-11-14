"""Command line of the multi-tenancy overhead benchmark."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from benchmarks.tenancy.backends import BACKENDS, BackendOptions
from benchmarks.tenancy.report import Report, environment_info, render
from benchmarks.tenancy.runner import run_benchmark
from benchmarks.tenancy.workload import POSTGRES_ABLATIONS, STANDARD_MODES, Plan

DESCRIPTION = """\
Measure the cost of multi-tenancy (ADR-020): the same sagas run as one tenant
(baseline) and spread over many tenants (multi), interleaved over several rounds.

Scaled-down default: 100 tenants x 10 concurrent sagas. Full size (#54):
  python -m benchmarks.tenancy --tenants 1000 --sagas-per-tenant 10
"""


def _backends(value: str) -> list[str]:
    names = [name.strip() for name in value.split(",") if name.strip()]
    unknown = sorted(set(names) - set(BACKENDS))
    if unknown or not names:
        msg = f"backends must be a comma-separated subset of {','.join(BACKENDS)}"
        raise argparse.ArgumentTypeError(msg)
    return names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.tenancy",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add = parser.add_argument
    add("--backends", type=_backends, default=["memory", "sqlite"], help="default: memory,sqlite")
    add("--tenants", type=int, default=100)
    add("--sagas-per-tenant", type=int, default=10, help="concurrent sagas of each tenant")
    add("--sagas-per-worker", type=int, default=1, help="sagas each concurrent worker runs")
    add("--rounds", type=int, default=10, help="measured runs of each mode, interleaved")
    add("--warmup", type=int, default=1, help="unmeasured runs of each mode first")
    add("--step-sleep-ms", type=float, default=0.0, help="simulated work per step")
    add("--postgres-admin-url", help="provision (and drop) a scratch database and app role")
    add("--postgres-url", help="use this database and role as they are; rows are left behind")
    add("--postgres-pool-size", type=int, default=20)
    add(
        "--postgres-async-commit",
        action="store_true",
        help="synchronous_commit=off: commits skip the WAL flush wait (exposes per-query costs)",
    )
    add(
        "--postgres-ablations",
        action="store_true",
        help="also run with RLS off and without set_config, to attribute PostgreSQL costs",
    )
    add("--redis-url")
    add("--json", dest="json_path", help="also write the results to this JSON file")
    return parser


async def _run(args: argparse.Namespace) -> Report:
    plan = Plan(args.tenants, args.sagas_per_tenant, args.sagas_per_worker, args.step_sleep_ms)
    options = BackendOptions(
        postgres_url=args.postgres_url,
        postgres_admin_url=args.postgres_admin_url,
        postgres_pool_size=args.postgres_pool_size,
        postgres_synchronous_commit=not args.postgres_async_commit,
        redis_url=args.redis_url,
    )
    config = {
        "backends": ",".join(args.backends),
        "tenants": plan.tenants,
        "sagas_per_tenant": plan.sagas_per_tenant,
        "sagas_per_worker": plan.sagas_per_worker,
        "sagas_per_run": plan.total_sagas,
        "rounds": args.rounds,
        "warmup": args.warmup,
        "step_sleep_ms": plan.step_sleep_ms,
        "postgres_ablations": args.postgres_ablations,
        "postgres_async_commit": args.postgres_async_commit,
    }
    report = Report(config=config, environment=environment_info())
    report.backends = await run_benchmark(
        args.backends,
        options,
        plan,
        STANDARD_MODES,
        args.rounds,
        args.warmup,
        POSTGRES_ABLATIONS if args.postgres_ablations else (),
        progress=lambda message: print(message, file=sys.stderr),  # noqa: T201
    )
    report.environment["loadavg_end"] = environment_info()["loadavg"]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = asyncio.run(_run(args))
    sys.stdout.write(render(report) + "\n")
    if args.json_path:
        report.write_json(args.json_path)
    return 0
