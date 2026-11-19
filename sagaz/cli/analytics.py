"""``sagaz analytics``: export the unified saga log (ADR-013, #481).

``sagaz analytics export`` moves committed log events to Fluss at least once,
resuming from the exporter's cursor in the log's database.
``sagaz analytics fluss-ddl`` prints the Fluss table for catalogs managed by
hand.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import click


@click.group()
def analytics_cli() -> None:
    """Export the saga log to streaming analytics (Fluss, tiered to Iceberg)."""


def _sink(target: str, table: str) -> Any:
    if not target.startswith("fluss://"):
        msg = f"Unsupported target {target!r}: use fluss://host:port"
        raise click.BadParameter(msg, param_hint="--to")
    from sagaz.integrations.fluss import FlussSink

    return FlussSink(target[len("fluss://") :], table)


async def _export(log_url: str, sink: Any, name: str, once: bool, interval: float) -> int:
    from sagaz.core.storage.saga_log import (
        SagaLogExporter,
        SagaLogReader,
        create_saga_log_store,
    )

    async with create_saga_log_store(log_url) as log:
        exporter = SagaLogExporter(SagaLogReader(log, name), sink, poll_interval=interval)
        try:
            if once:
                return await exporter.export()
            await exporter.start()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.Event().wait()  # until interrupted
            return exporter.exported
        finally:
            await exporter.close()


@analytics_cli.command("export")
@click.option("--saga-log", "log_url", envvar="SAGAZ_SAGA_LOG_URL", required=True,
              help="Saga log URL (or SAGAZ_SAGA_LOG_URL).")  # fmt: skip
@click.option("--to", "target", required=True, help="Destination: fluss://host:port.")
@click.option("--table", default="sagaz.saga_log_event", show_default=True,
              help="Fluss table, database.table.")  # fmt: skip
@click.option("--name", default="fluss", show_default=True,
              help="Exporter name: its cursor in saga_export_cursor.")  # fmt: skip
@click.option("--once", is_flag=True, help="Export what is committed now, then exit.")
@click.option("--poll-interval", default=0.5, show_default=True, type=float,
              help="Seconds between polls when running continuously.")  # fmt: skip
def export_cmd(
    log_url: str, target: str, table: str, name: str, once: bool, poll_interval: float
) -> None:
    """Export committed saga log events, at least once, resuming from the cursor."""
    sink = _sink(target, table)
    try:
        count = asyncio.run(_export(log_url, sink, name, once, poll_interval))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return
    click.echo(f"Exported {count} events to {target} ({table}), exporter {name!r}.")


@analytics_cli.command("fluss-ddl")
@click.option("--table", default="sagaz.saga_log_event", show_default=True)
@click.option("--no-datalake", is_flag=True, help="Do not tier the table to the lake.")
def fluss_ddl_cmd(table: str, no_datalake: bool) -> None:
    """Print the Flink SQL CREATE TABLE of the Fluss table."""
    from sagaz.integrations.fluss import fluss_ddl

    click.echo(fluss_ddl(table, datalake=not no_datalake))
