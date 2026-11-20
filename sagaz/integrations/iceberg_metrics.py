"""Saga analytics from the Iceberg history, as Prometheus metrics (ADR-013).

Fluss tiers the exported saga log to the Iceberg table
``sagaz.saga_log_event``. :class:`IcebergFlowCollector` reads it with pyiceberg,
through the same catalog Fluss writes to, and computes the flow summary with
DuckDB. It is the same report as ``sagaz analytics flink-sql flow-summary`` and
the embedded ``SagaQueries.FLOW_SUMMARY``. Prometheus scrapes the result, so
Grafana needs no SQL data source::

    sagaz analytics metrics --catalog-uri postgresql://.../iceberg \\
        --warehouse file:///data/warehouse --port 9464

The report is cached for ``refresh_seconds``, so a scrape never waits on a
table scan. If a refresh fails, the last report keeps being served,
``sagaz_flow_report_errors_total`` counts the failure, and
``sagaz_flow_report_age_seconds`` keeps growing. ``days`` limits the scan to
recent day partitions.

Install with ``pip install 'sagaz[iceberg]'``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.core.exceptions import MissingDependencyError

logger = logging.getLogger(__name__)

#: The flow summary over the exported log, in DuckDB. Same semantics as
#: ``sagaz.integrations.flink_sql.FLOW_SUMMARY``.
FLOW_SUMMARY = """
WITH events AS (
    SELECT tenant_id, transaction_id, coordination, flow, kind, sequence, occurred_at_ms,
        CASE
            WHEN kind <> 'lifecycle' THEN NULL
            WHEN event_type = 'SagaStarted' THEN 'executing'
            WHEN event_type = 'CompensationStarted' THEN 'compensating'
            WHEN event_type = 'SagaCompleted' THEN 'completed'
            WHEN event_type = 'SagaRolledBack' THEN 'compensated'
            WHEN event_type = 'SagaFailed' THEN 'failed'
            WHEN event_type = 'TransactionStatusChanged'
                THEN json_extract_string(payload, '$.status')
        END AS status
    FROM log
),
latest AS (
    SELECT tenant_id, transaction_id, status, occurred_at_ms AS status_ms
    FROM events WHERE status IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY tenant_id, transaction_id ORDER BY sequence DESC) = 1
),
transactions AS (
    SELECT tenant_id, transaction_id,
           MAX(coordination) AS coordination, MAX(flow) AS flow,
           MIN(occurred_at_ms) AS first_ms,
           MIN(occurred_at_ms) FILTER (WHERE kind <> 'lifecycle') AS first_event_ms,
           MAX(occurred_at_ms) FILTER (WHERE kind <> 'lifecycle') AS last_event_ms
    FROM events GROUP BY tenant_id, transaction_id
),
flows AS (
    SELECT t.coordination, t.flow, COALESCE(l.status, 'executing') AS status,
           CASE
               WHEN t.coordination = 'choreographed'
                    AND COALESCE(l.status, 'executing') IN ('completed', 'compensated', 'failed')
                   THEN CAST(t.last_event_ms - t.first_event_ms AS DOUBLE)
               WHEN t.coordination = 'orchestrated' AND l.status IN ('completed', 'compensated')
                   THEN CAST(l.status_ms - t.first_ms AS DOUBLE)
           END AS duration_ms
    FROM transactions t
    LEFT JOIN latest l USING (tenant_id, transaction_id)
)
SELECT coordination, flow,
       COUNT(*) AS transactions,
       COUNT(*) FILTER (WHERE status = 'completed') AS completed,
       COUNT(*) FILTER (WHERE status = 'compensated') AS compensated,
       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
       COUNT(*) FILTER (WHERE status IN ('executing', 'compensating')) AS in_flight,
       ROUND(100.0 * COUNT(*) FILTER (WHERE status IN ('compensated', 'failed'))
           / NULLIF(COUNT(*) FILTER (WHERE status IN ('completed', 'compensated', 'failed')), 0),
           2) AS compensation_rate_pct,
       ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms), 2) AS p50_duration_ms,
       ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms), 2) AS p95_duration_ms
FROM flows
GROUP BY coordination, flow
ORDER BY transactions DESC, coordination, flow
"""

_COLUMNS = (
    "tenant_id",
    "transaction_id",
    "sequence",
    "event_type",
    "kind",
    "coordination",
    "flow",
    "payload",
    "occurred_at_ms",
)
_STATUSES = ("completed", "compensated", "failed", "in_flight")


def flow_summary(log: Any) -> list[dict[str, Any]]:
    """The flow summary of *log*, an Arrow table of exported saga log rows."""
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - installed with the extra
        msg = "duckdb"
        raise MissingDependencyError(msg, "Iceberg metrics") from exc
    conn = duckdb.connect()
    try:
        conn.register("log", log)
        cursor = conn.execute(FLOW_SUMMARY)
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    finally:
        conn.close()


class IcebergLogSource:
    """Reads the exported saga log from an Iceberg catalog (pyiceberg).

    Args:
        catalog: A pyiceberg catalog, or the properties to load one with
            (``{"type": "sql", "uri": "postgresql+psycopg2://...", "warehouse": ...}``).
        table: ``namespace.table`` in the catalog.
        catalog_name: The catalog's name. A SQL catalog files tables under
            it, so it must be the name Fluss uses (``datalake.iceberg.name``).
        days: Read only the last *days* day partitions (all when ``None``).
    """

    def __init__(
        self,
        catalog: Any,
        table: str = "sagaz.saga_log_event",
        *,
        catalog_name: str = "iceberg",
        days: int | None = None,
    ) -> None:
        self._catalog = catalog
        self.catalog_name = catalog_name
        self.table = table
        self.days = days

    def _load_catalog(self) -> Any:
        if not isinstance(self._catalog, dict):
            return self._catalog
        try:
            from pyiceberg.catalog import load_catalog
        except ImportError as exc:
            msg = "pyiceberg"
            raise MissingDependencyError(msg, "Iceberg metrics") from exc
        self._catalog = load_catalog(self.catalog_name, **self._catalog)
        return self._catalog

    def read(self) -> Any:
        """The table's rows (the columns the report needs) as an Arrow table."""
        table = self._load_catalog().load_table(self.table)
        scan: dict[str, Any] = {"selected_fields": _COLUMNS}
        if self.days is not None:  # prunes day partitions
            since = (datetime.now(UTC) - timedelta(days=self.days)).strftime("%Y-%m-%d")
            scan["row_filter"] = f"dt >= '{since}'"
        return table.scan(**scan).to_arrow()


class IcebergFlowCollector:
    """A Prometheus collector of the flow summary (``REGISTRY.register(collector)``).

    Metrics, labelled by ``coordination`` and ``flow``:

    - ``sagaz_flow_transactions{status}``: completed, compensated, failed, in_flight;
    - ``sagaz_flow_compensation_rate_percent``;
    - ``sagaz_flow_duration_milliseconds{quantile="0.5"|"0.95"}``;
    - ``sagaz_flow_report_age_seconds``, ``sagaz_flow_report_errors_total``.
    """

    def __init__(
        self,
        source: IcebergLogSource,
        *,
        refresh_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.refresh_seconds = refresh_seconds
        self._clock = clock
        self._rows: list[dict[str, Any]] = []
        self._refreshed_at: float | None = None
        self._errors = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Recompute in a background thread every ``refresh_seconds``, starting now.

        A scrape then never waits on a table scan (a cold read of the catalog
        and files can take longer than Prometheus's scrape timeout); it serves
        the last report.
        """
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="iceberg-flows", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._try_refresh()
            self._stop.wait(self.refresh_seconds)

    def _try_refresh(self) -> None:
        try:
            self.refresh()
        except Exception:  # serve the last report, count the failure
            logger.exception("Could not refresh the flow summary from Iceberg")
            self._errors += 1

    def refresh(self) -> list[dict[str, Any]]:
        """Read the table and recompute the report now."""
        rows = flow_summary(self.source.read())
        with self._lock:
            self._rows, self._refreshed_at = rows, self._clock()
        return rows

    def _current(self) -> list[dict[str, Any]]:
        stale = (
            self._refreshed_at is None or self._clock() - self._refreshed_at >= self.refresh_seconds
        )
        running = self._thread is not None and self._thread.is_alive()
        if stale and not running:  # without the background thread: on scrape
            self._try_refresh()
        return self._rows

    def collect(self) -> Iterator[Any]:
        from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

        rows = self._current()
        labels = ["coordination", "flow"]
        transactions = GaugeMetricFamily(
            "sagaz_flow_transactions",
            "Transactions per flow and status, from the Iceberg history",
            labels=[*labels, "status"],
        )
        rate = GaugeMetricFamily(
            "sagaz_flow_compensation_rate_percent",
            "Finished transactions compensated or failed, in percent",
            labels=labels,
        )
        duration = GaugeMetricFamily(
            "sagaz_flow_duration_milliseconds",
            "Transaction duration percentiles",
            labels=[*labels, "quantile"],
        )
        for row in rows:
            key = [str(row["coordination"]), str(row["flow"])]
            for status in _STATUSES:
                transactions.add_metric([*key, status], float(row[status]))
            if row["compensation_rate_pct"] is not None:
                rate.add_metric(key, float(row["compensation_rate_pct"]))
            for quantile, column in (("0.5", "p50_duration_ms"), ("0.95", "p95_duration_ms")):
                if row[column] is not None:
                    duration.add_metric([*key, quantile], float(row[column]))
        yield transactions
        yield rate
        yield duration
        age = GaugeMetricFamily(
            "sagaz_flow_report_age_seconds", "Seconds since the report was computed"
        )
        if self._refreshed_at is not None:
            age.add_metric([], self._clock() - self._refreshed_at)
        yield age
        yield CounterMetricFamily(
            "sagaz_flow_report_errors", "Failed report refreshes", value=self._errors
        )


class ExporterCollector:
    """A Prometheus collector of a ``SagaLogExporter``'s progress."""

    def __init__(self, exporter: Any) -> None:
        self.exporter = exporter

    def collect(self) -> Iterator[Any]:
        from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

        metrics = self.exporter.metrics()
        name = [metrics["exporter"]]
        exported = CounterMetricFamily(
            "sagaz_log_export_events", "Saga log events exported", labels=["exporter"]
        )
        exported.add_metric(name, metrics["exported"])
        yield exported
        errors = CounterMetricFamily(
            "sagaz_log_export_errors", "Failed export attempts", labels=["exporter"]
        )
        errors.add_metric(name, metrics["errors"])
        yield errors
        lag = GaugeMetricFamily(
            "sagaz_log_export_lag_seconds",
            "Seconds since the last exported event occurred",
            labels=["exporter"],
        )
        if metrics["lag_seconds"] is not None:
            lag.add_metric(name, metrics["lag_seconds"])
        yield lag
