"""CLI: ``python -m benchmarks.cdc --dsn postgresql://... [--events N] [--rates ...]``."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from benchmarks.cdc.runner import Load, Result, run

COLUMNS = (
    "mode",
    "events",
    "target_rate",
    "produced_rate",
    "published",
    "throughput",
    "lag_p50_ms",
    "lag_p95_ms",
    "lag_p99_ms",
    "lag_max_ms",
)


def table(results: list[Result]) -> str:
    """Markdown table of the results."""
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(str(getattr(r, c)) for c in COLUMNS) + " |" for r in results]
    return "\n".join(lines)


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CDC vs polling outbox lag and throughput")
    parser.add_argument("--dsn", required=True, help="superuser DSN, wal_level=logical, scratch DB")
    parser.add_argument("--events", type=int, default=20_000)
    parser.add_argument(
        "--rates",
        type=float,
        nargs="+",
        default=[1_000, 5_000, 0],
        help="target events/s per run; 0 = unthrottled",
    )
    parser.add_argument("--rows-per-tx", type=int, default=50)
    parser.add_argument("--producers", type=int, default=1, help="concurrent producer connections")
    parser.add_argument(
        "--modes", nargs="+", default=["cdc", "polling"], choices=["cdc", "polling"]
    )
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument(
        "--max-batch-delay", type=float, default=0.005, help="PgLogicalSource batching wait (s)"
    )
    parser.add_argument("--json", type=Path, help="also write the results as JSON")
    return parser.parse_args(argv)


async def _main(args: argparse.Namespace) -> list[Result]:
    results = []
    for rate in args.rates:
        for mode in args.modes:
            load = Load(args.events, rate, args.rows_per_tx, args.producers)
            results.append(
                await run(args.dsn, mode, load, args.poll_interval, args.max_batch_delay)
            )
            sys.stdout.write(table(results[-1:]).splitlines()[-1] + "\n")
            sys.stdout.flush()
    return results


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    results = asyncio.run(_main(args))
    sys.stdout.write("\n" + table(results) + "\n")
    if args.json:
        args.json.write_text(json.dumps([r.to_dict() for r in results], indent=2) + "\n")


if __name__ == "__main__":
    main()
