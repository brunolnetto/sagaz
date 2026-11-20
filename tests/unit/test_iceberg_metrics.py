"""The flow summary from the Iceberg history, as Prometheus metrics (ADR-013)."""

from __future__ import annotations

from uuid import uuid4

import pytest

pa = pytest.importorskip("pyarrow")
pytest.importorskip("pyiceberg")
pytest.importorskip("duckdb")
pytest.importorskip("sqldim")
prometheus_client = pytest.importorskip("prometheus_client")

from click.testing import CliRunner  # noqa: E402
from prometheus_client import CollectorRegistry, generate_latest  # noqa: E402

from sagaz.cli.app import cli  # noqa: E402
from sagaz.core.storage.saga_log import (  # noqa: E402
    InMemorySagaLogStore,
    SagaLogExporter,
    SagaLogReader,
)
from sagaz.integrations.fluss import _arrow_schema, fluss_row  # noqa: E402
from sagaz.integrations.iceberg_metrics import (  # noqa: E402
    ExporterCollector,
    IcebergFlowCollector,
    IcebergLogSource,
    flow_summary,
)
from tests.unit.analytics.test_unified_analytics import fill, reports  # noqa: E402


class ListSink:
    """Collects exported events (an ExportSink)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def write(self, events) -> None:
        self.rows += [fluss_row(e) for e in events]

    async def close(self) -> None:
        pass


async def exported(log) -> list[dict]:
    sink = ListSink()  # a new exporter name each time: from the start of the log
    await SagaLogExporter(SagaLogReader(log, f"test-{uuid4().hex}"), sink).export()
    return sink.rows


@pytest.fixture
async def log():
    store = InMemorySagaLogStore()
    await fill(store)
    await fill(store)  # choreographed transactions get new ids each time
    yield store
    await store.close()


@pytest.fixture
def catalog(tmp_path):
    """A pyiceberg SQL catalog: the same tables a JDBC catalog keeps (Fluss writes one)."""
    from pyiceberg.catalog.sql import SqlCatalog

    catalog = SqlCatalog(
        "iceberg",
        uri=f"sqlite:///{tmp_path / 'catalog.db'}",
        warehouse=f"file://{tmp_path / 'warehouse'}",
    )
    yield catalog
    catalog.engine.dispose()


def tier(catalog, rows: list[dict]) -> None:
    """What Fluss's tiering service does: the exported rows into the Iceberg table."""
    catalog.create_namespace_if_not_exists("sagaz")
    table = catalog.create_table_if_not_exists("sagaz.saga_log_event", schema=_arrow_schema())
    table.append(pa.Table.from_pylist(rows, schema=_arrow_schema()))


def _without_timings(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if "duration" not in k} for r in rows]


class TestFlowSummary:
    async def test_matches_the_embedded_pipeline(self, log, catalog):
        tier(catalog, await exported(log))
        from_iceberg = flow_summary(IcebergLogSource(catalog).read())
        (embedded,) = (await reports(log, "FLOW_SUMMARY")).values()
        assert _without_timings(from_iceberg) == _without_timings(embedded)
        by_flow = {(r["coordination"], r["flow"]): r for r in from_iceberg}
        choreographed = by_flow[("choreographed", "order.created")]
        assert (choreographed["transactions"], choreographed["completed"]) == (6, 4)
        # Embedded durations are in microseconds, exported ones in milliseconds.
        for row, reference in zip(from_iceberg, embedded, strict=True):
            for column in ("p50_duration_ms", "p95_duration_ms"):
                assert row[column] == pytest.approx(reference[column], abs=1.0)

    async def test_days_prunes_old_partitions(self, log, catalog):
        tier(catalog, await exported(log))
        assert len(IcebergLogSource(catalog, days=30).read()) > 0
        assert len(IcebergLogSource(catalog).read()) == len(await exported(log))
        old = [dict(r, dt="2020-01-01") for r in await exported(log)]
        catalog.load_table("sagaz.saga_log_event").append(
            pa.Table.from_pylist(old, schema=_arrow_schema())
        )
        assert len(IcebergLogSource(catalog, days=30).read()) == len(old)

    def test_a_catalog_from_properties(self, tmp_path, catalog):
        tier(catalog, [])
        source = IcebergLogSource(
            {"type": "sql", "uri": f"sqlite:///{tmp_path / 'catalog.db'}"},
            catalog_name="iceberg",
        )
        assert source.read().num_rows == 0
        source._load_catalog().engine.dispose()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestCollector:
    async def test_metrics(self, log, catalog):
        tier(catalog, await exported(log))
        registry = CollectorRegistry()
        registry.register(IcebergFlowCollector(IcebergLogSource(catalog)))
        text = generate_latest(registry).decode()
        assert (
            'sagaz_flow_transactions{coordination="choreographed",flow="order.created",'
            'status="completed"} 4.0' in text
        )
        assert (
            'sagaz_flow_compensation_rate_percent{coordination="orchestrated",flow="order"}' in text
        )
        assert 'quantile="0.95"' in text
        assert "sagaz_flow_report_age_seconds 0.0" in text
        assert "sagaz_flow_report_errors_total 0.0" in text

    async def test_cached_between_refreshes_and_kept_on_failure(self, log, catalog):
        tier(catalog, await exported(log))
        source = IcebergLogSource(catalog)
        clock = Clock()
        collector = IcebergFlowCollector(source, refresh_seconds=60, clock=clock)
        reads = []
        real_read = source.read
        source.read = lambda: reads.append(1) or real_read()  # type: ignore[method-assign]
        list(collector.collect())
        clock.now += 30
        list(collector.collect())
        assert len(reads) == 1  # cached

        def broken():
            msg = "catalog unreachable"
            raise ConnectionError(msg)

        source.read = broken  # type: ignore[method-assign]
        clock.now += 60
        metrics = {m.name: m for m in collector.collect()}
        assert metrics["sagaz_flow_report_errors"].samples[0].value == 1
        assert metrics["sagaz_flow_report_age_seconds"].samples[0].value == 90
        assert metrics["sagaz_flow_transactions"].samples  # the last report is still served

    async def test_the_background_thread_refreshes(self, log, catalog):
        import time

        tier(catalog, await exported(log))
        source = IcebergLogSource(catalog)
        collector = IcebergFlowCollector(source, refresh_seconds=0.05)
        reads = []
        real_read = source.read
        source.read = lambda: reads.append(1) or real_read()  # type: ignore[method-assign]
        collector.start()
        collector.start()  # already running
        for _ in range(200):
            if len(reads) >= 2:
                break
            time.sleep(0.02)
        metrics = {m.name: m for m in collector.collect()}  # served from the last report
        assert metrics["sagaz_flow_transactions"].samples
        collector.stop()
        assert len(reads) >= 2

        def broken():
            msg = "catalog unreachable"
            raise ConnectionError(msg)

        source.read = broken  # type: ignore[method-assign]
        collector.refresh_seconds = 10
        collector.start()
        for _ in range(200):
            if collector._errors:
                break
            time.sleep(0.02)
        collector.stop()
        assert collector._errors == 1

    def test_nothing_computed_yet(self, catalog):
        source = IcebergLogSource(catalog)  # the table does not exist
        metrics = {m.name: m for m in IcebergFlowCollector(source).collect()}
        assert metrics["sagaz_flow_report_age_seconds"].samples == []
        assert metrics["sagaz_flow_report_errors"].samples[0].value == 1


class TestExporterCollector:
    async def test_metrics(self, log):
        exporter = SagaLogExporter(SagaLogReader(log, "fluss"), ListSink())
        registry = CollectorRegistry()
        registry.register(ExporterCollector(exporter))
        before = generate_latest(registry).decode()
        assert "sagaz_log_export_lag_seconds{" not in before  # nothing exported yet
        await exporter.export()
        text = generate_latest(registry).decode()
        assert 'sagaz_log_export_events_total{exporter="fluss"}' in text
        assert 'sagaz_log_export_errors_total{exporter="fluss"} 0.0' in text
        assert 'sagaz_log_export_lag_seconds{exporter="fluss"}' in text


def test_the_metrics_command_needs_a_catalog():
    result = CliRunner().invoke(cli, ["analytics", "metrics"], env={"SAGAZ_ICEBERG_URI": None})
    assert result.exit_code != 0
    assert "--catalog-uri" in result.output


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_the_metrics_command_serves_the_report(log, catalog, tmp_path, monkeypatch):
    import asyncio
    import urllib.request

    tier(catalog, await exported(log))
    monkeypatch.setattr("sagaz.cli.analytics._wait_forever", lambda: None)
    port = _free_port()
    args = ["analytics", "metrics", "--catalog-uri", f"sqlite:///{tmp_path / 'catalog.db'}"]
    result = CliRunner().invoke(cli, [*args, "--port", str(port), "--host", "127.0.0.1"])
    assert result.exit_code == 0, result.output
    text = ""
    for _ in range(100):  # the first report is computed in the background
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=10) as response:
            text = response.read().decode()
        if 'sagaz_flow_transactions{coordination="choreographed"' in text:
            break
        await asyncio.sleep(0.1)
    assert 'sagaz_flow_transactions{coordination="choreographed"' in text


def test_catalog_uris():
    from sagaz.cli.analytics import _catalog_properties

    assert _catalog_properties("postgresql://u@h/iceberg", "s3://b") == {
        "type": "sql",
        "uri": "postgresql+psycopg2://u@h/iceberg",
        "warehouse": "s3://b",
    }
    assert _catalog_properties("sqlite:///c.db", None) == {"type": "sql", "uri": "sqlite:///c.db"}


def test_the_exporter_serves_its_metrics(tmp_path, monkeypatch):
    import asyncio
    import urllib.request

    from sagaz.cli.analytics import _export

    port = _free_port()
    seen = {}

    async def interrupt(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=10) as response:
            seen["text"] = response.read().decode()
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio.Event, "wait", interrupt)
    asyncio.run(_export("memory://", ListSink(), "fluss", False, 0.01, port))
    assert 'sagaz_log_export_events_total{exporter="fluss"}' in seen["text"]
