"""``sagaz benchmark`` command."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

import click

from sagaz.cli._benchmark import BenchmarkResult, profiles_for, run_benchmark, summary

# mypy reads the imports alone: no ignore is needed with or without the dependency.
if TYPE_CHECKING:
    from rich.console import Console
    from rich.table import Table

    console: Console | None = Console()
else:
    try:
        from rich.console import Console
        from rich.table import Table

        console: Console | None = Console()
    except ImportError:
        console = None
        Table = None

COLUMNS = (
    "profile",
    "storage",
    "sagas",
    "concurrency",
    "failed",
    "throughput",
    "p50_ms",
    "p95_ms",
    "p99_ms",
)


def _show(results: list[BenchmarkResult]) -> None:
    rows = [[str(getattr(r, c)) for c in COLUMNS] for r in results]
    if console is not None and Table is not None:
        table = Table(title="Sagaz benchmark (sagas/s, latency in ms)")
        for column in COLUMNS:
            table.add_column(
                column, justify="left" if column in ("profile", "storage") else "right"
            )
        for row in rows:
            table.add_row(*row)
        console.print(table)
        return
    click.echo("  ".join(COLUMNS))
    for row in rows:
        click.echo("  ".join(row))


@click.command()
@click.option(
    "--profile",
    type=click.Choice(["local", "production", "stress", "full"]),
    default="local",
    show_default=True,
    help="Workload size.",
)
@click.option("--quick", is_flag=True, help="Quick sanity check (20 sagas).")
@click.option(
    "--storage-url",
    envvar="SAGAZ_STORAGE_URL",
    default=None,
    metavar="URL",
    help="Saga storage to benchmark (default: in-memory). Benchmark sagas are deleted afterwards.",
)
@click.option("--output", type=click.Path(dir_okay=False), help="Write the results as JSON.")
@click.pass_context
def benchmark_cmd(
    ctx: click.Context, profile: str, quick: bool, storage_url: str | None, output: str | None
) -> None:
    """
    Measure saga throughput and latency with the installed sagaz.

    Runs a three-step saga (reserve -> charge -> notify) many times with bounded
    concurrency and reports sagas per second and p50/p95/p99 latency.

    \b
    Profiles (sagas x concurrency):
        local        500 x 20 (default)
        production   5,000 x 100
        stress       20,000 x 500
        full         all three

    \b
    Examples:
        sagaz benchmark --quick
        sagaz benchmark --profile production --storage-url postgresql://...
        sagaz benchmark --profile full --output results.json
    """
    results = [
        asyncio.run(run_benchmark(selected, storage_url))
        for selected in profiles_for(profile, quick)
    ]
    _show(results)

    if output:
        Path(output).write_text(json.dumps(summary(results), indent=2), encoding="utf-8")
        click.echo(f"Results saved to {output}")

    failed = sum(r.failed for r in results)
    if failed:
        click.echo(f"{failed} saga(s) failed during the benchmark.", err=True)
        ctx.exit(1)
