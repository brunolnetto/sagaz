"""``sagaz analytics``: export the unified saga log (ADR-013, #481).

``sagaz analytics export`` moves committed log events to Fluss at least once,
resuming from the exporter's cursor in the log's database.
``sagaz analytics fluss-ddl`` prints the Fluss table for catalogs managed by
hand, ``sagaz analytics flink-sql`` the reports in Flink SQL, and
``sagaz analytics metrics`` serves the flow summary of the Iceberg history to
Prometheus.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import click


@click.group()
def analytics_cli() -> None:
    """Export the saga log to streaming analytics (Fluss, tiered to Iceberg)."""


def _sink(target: str, table: str, freshness: str | None = None) -> Any:
    if not target.startswith("fluss://"):
        msg = f"Unsupported target {target!r}: use fluss://host:port"
        raise click.BadParameter(msg, param_hint="--to")
    from sagaz.integrations.fluss import FlussSink

    return FlussSink(target[len("fluss://") :], table, freshness=freshness)


def _serve(collector: Any, port: int, host: str) -> None:
    """Serve *collector* on ``http://host:port/metrics`` (a background thread)."""
    from prometheus_client import CollectorRegistry, start_http_server

    registry = CollectorRegistry()
    registry.register(collector)
    start_http_server(port, addr=host, registry=registry)


async def _export(
    log_url: str,
    sink: Any,
    name: str,
    once: bool,
    interval: float,
    metrics_port: int | None = None,
) -> int:
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
            if metrics_port is not None:
                from sagaz.integrations.iceberg_metrics import ExporterCollector

                _serve(ExporterCollector(exporter), metrics_port, "0.0.0.0")
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
@click.option("--freshness", default=None,
              help="How far behind the lake may be (a created table), e.g. 1min.")  # fmt: skip
@click.option("--poll-interval", default=0.5, show_default=True, type=float,
              help="Seconds between polls when running continuously.")  # fmt: skip
@click.option("--metrics-port", type=int, default=None,
              help="Serve the exporter's Prometheus metrics on this port.")  # fmt: skip
def export_cmd(
    log_url: str,
    target: str,
    table: str,
    name: str,
    once: bool,
    freshness: str | None,
    poll_interval: float,
    metrics_port: int | None,
) -> None:
    """Export committed saga log events, at least once, resuming from the cursor."""
    sink = _sink(target, table, freshness)
    try:
        count = asyncio.run(_export(log_url, sink, name, once, poll_interval, metrics_port))
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


@analytics_cli.command("flink-sql")
@click.argument("report_name", metavar="REPORT")
@click.option("--table", default="iceberg.sagaz.saga_log_event", show_default=True,
              help="catalog.database.table to read, in batch mode.")  # fmt: skip
def flink_sql_cmd(report_name: str, table: str) -> None:
    """Print a saga analytics report in Flink SQL (flow-summary, throughput)."""
    from sagaz.integrations.flink_sql import report

    try:
        click.echo(report(report_name, table), nl=False)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="REPORT") from exc


def _catalog_properties(
    uri: str, warehouse: str | None, extra: tuple[str, ...] = ()
) -> dict[str, str]:
    """pyiceberg SQL catalog properties for a JDBC-style catalog database URL.

    *extra* are ``key=value`` pyiceberg properties, e.g. ``s3.endpoint=http://...``.
    """
    if uri.startswith(("postgresql://", "postgres://")):
        uri = "postgresql+psycopg2://" + uri.split("://", 1)[1]
    properties = {"type": "sql", "uri": uri}
    if warehouse:
        properties["warehouse"] = warehouse
    for item in extra:
        key, sep, value = item.partition("=")
        if not sep or not key:
            msg = f"Expected key=value, got {item!r}"
            raise click.BadParameter(msg, param_hint="--catalog-property")
        properties[key.strip()] = value.strip()
    return properties


def _wait_forever() -> None:  # pragma: no cover - interactive
    import threading

    threading.Event().wait()


@analytics_cli.command("metrics")
@click.option("--catalog-uri", envvar="SAGAZ_ICEBERG_URI", required=True,
              help="Iceberg catalog database (Fluss's datalake.iceberg.uri), e.g. "
                   "postgresql://user@host/iceberg (or SAGAZ_ICEBERG_URI).")  # fmt: skip
@click.option("--catalog-name", default="iceberg", show_default=True,
              help="Fluss's datalake.iceberg.name.")  # fmt: skip
@click.option("--warehouse", default=None, help="Warehouse location, e.g. s3://bucket/path.")
@click.option("--catalog-property", "catalog_properties", multiple=True, metavar="KEY=VALUE",
              help="A pyiceberg property, e.g. s3.endpoint=http://localhost:9000 (repeatable).")  # fmt: skip
@click.option("--table", default="sagaz.saga_log_event", show_default=True)
@click.option("--days", type=int, default=None, help="Only the last DAYS day partitions.")
@click.option("--refresh", default=60.0, show_default=True, type=float,
              help="Seconds a computed report is served before it is recomputed.")  # fmt: skip
@click.option("--port", default=9464, show_default=True, type=int)
@click.option("--host", default="0.0.0.0", show_default=True)
def metrics_cmd(
    catalog_uri: str,
    catalog_name: str,
    warehouse: str | None,
    catalog_properties: tuple[str, ...],
    table: str,
    days: int | None,
    refresh: float,
    port: int,
    host: str,
) -> None:
    """Serve the flow summary of the Iceberg history as Prometheus metrics."""
    from sagaz.integrations.iceberg_metrics import IcebergFlowCollector, IcebergLogSource

    source = IcebergLogSource(
        _catalog_properties(catalog_uri, warehouse, catalog_properties),
        table,
        catalog_name=catalog_name,
        days=days,
    )
    collector = IcebergFlowCollector(source, refresh_seconds=refresh)
    collector.start()  # scrapes serve the last report, never wait on a scan
    _serve(collector, port, host)
    click.echo(f"Serving the flow summary of {table} on http://{host}:{port}/metrics")
    _wait_forever()
