"""Exporting the saga log to Fluss (ADR-013, #481).

``FakeFluss`` stands in for the ``fluss`` client module (pyfluss): the
connection, admin, table and upsert writer of its documented API, with a
primary-key table that can be made to fail.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from sagaz.cli.app import cli
from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.storage.saga_log import (
    STATUS_CHANGED,
    Coordination,
    EventKind,
    ExportedEvent,
    InMemorySagaLogStore,
    LogEvent,
    LogWrite,
    SagaLogExporter,
    SagaLogReader,
    Transaction,
)
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore
from sagaz.core.tenant import tenant_scope
from sagaz.integrations.fluss import FlussSink, fluss_ddl, fluss_row, table_properties

pa = pytest.importorskip("pyarrow")

T0 = datetime(2026, 11, 1, 23, 30, tzinfo=UTC)


class FakeFluss:
    """The subset of the ``fluss`` module the sink uses."""

    def __init__(self) -> None:
        self.rows: dict[tuple, dict] = {}  # the primary-key table
        self.upserts = 0
        self.fail_after: int | None = None  # fail the upsert after this many
        self.created: list = []
        self.hang = False
        self.partitions: list = []
        self.connections = 0
        self.closed = 0
        fake = self

        class Handle:
            def __init__(self, row, ok):
                self.row, self.ok = row, ok

            async def wait(self):
                if fake.hang:  # a server that went away: never acknowledged
                    await asyncio.Event().wait()
                if not self.ok:
                    msg = "tablet server unreachable"
                    raise ConnectionError(msg)
                key = tuple(self.row[k] for k in ("dt", "tenant_id", "transaction_id", "sequence"))
                fake.rows[key] = self.row

        class Writer:
            def upsert(self, row):
                fake.upserts += 1
                ok = fake.fail_after is None or fake.upserts <= fake.fail_after
                return Handle(dict(row), ok)

            async def flush(self):
                await asyncio.sleep(0)

        class Admin:
            async def create_database(self, name, ignore_if_exists=False):
                fake.created.append(("database", name, ignore_if_exists))

            async def create_table(self, path, descriptor, ignore_if_exists=False):
                fake.created.append(("table", path, descriptor, ignore_if_exists))

            async def create_partition(self, path, spec, ignore_if_exists=False):
                fake.partitions.append((path, spec, ignore_if_exists))

        class Connection:
            def get_admin(self):
                return Admin()

            async def get_table(self, path):
                return SimpleNamespace(new_upsert=lambda: SimpleNamespace(create_writer=Writer))

            async def close(self):
                fake.closed += 1
                if fake.hang:
                    await asyncio.Event().wait()

        async def create(config):
            fake.connections += 1
            fake.config = config
            return Connection()

        self.Config = lambda properties: dict(properties)
        self.FlussConnection = SimpleNamespace(create=create)
        self.TablePath = lambda database, table: (database, table)
        self.Schema = lambda schema, primary_keys=None: SimpleNamespace(
            schema=schema, primary_keys=primary_keys
        )
        self.TableDescriptor = lambda schema, **kw: SimpleNamespace(schema=schema, **kw)


async def fill(log) -> int:
    """Two tenants, an orchestrated and a choreographed transaction: 5 events."""
    with tenant_scope("acme"):
        await log.write(
            LogWrite(
                transaction=Transaction("t-1", "order", Coordination.ORCHESTRATED, started_at=T0),
                events=[
                    LogEvent("t-1", "SagaStarted", EventKind.LIFECYCLE, occurred_at=T0),
                    LogEvent("t-1", "SagaCompleted", EventKind.LIFECYCLE, occurred_at=T0),
                ],
            )
        )
    with tenant_scope("globex"):
        await log.write(
            LogWrite(
                transaction=Transaction(
                    "t-2", "order.created", Coordination.CHOREOGRAPHED, started_at=T0
                ),
                events=[
                    LogEvent(
                        "t-2",
                        "order.created",
                        EventKind.BUSINESS,
                        source="orders",
                        payload={"amount": 40},
                        occurred_at=T0 + timedelta(hours=1),  # the next day
                    ),
                    LogEvent("t-2", "inventory.reserved", EventKind.BUSINESS, occurred_at=T0),
                    LogEvent("t-2", "order.shipped", EventKind.BUSINESS, occurred_at=T0),
                ],
            )
        )
    return 5


@pytest.fixture(params=["memory", "sqlite"])
async def log(request, tmp_path):
    store = (
        InMemorySagaLogStore()
        if request.param == "memory"
        else SQLiteSagaLogStore(str(tmp_path / "log.db"))
    )
    yield store
    await store.close()


def exporter(log, fake, name="fluss", **kw) -> SagaLogExporter:
    sink = FlussSink("fluss:9123", client=fake)
    return SagaLogExporter(SagaLogReader(log, name, batch_size=2), sink, **kw)


class TestRows:
    def test_a_log_event_as_a_fluss_row(self):
        late = datetime(2026, 11, 19, 22, 0, tzinfo=timezone(timedelta(hours=-3)))
        event = LogEvent(
            "t-1",
            "order.created",
            EventKind.BUSINESS,
            source="orders",
            causation_id="c-1",
            payload={"b": 1, "a": [1]},
            occurred_at=late,
            sequence=4,
            tenant_id="acme",
        )
        row = fluss_row(ExportedEvent(event, "choreographed", "order.created"))
        assert row["dt"] == "2026-11-20"  # the UTC day
        assert row["occurred_at"] == late.astimezone(UTC)
        assert row["occurred_at_ms"] == 1795136400000  # 2026-11-20T01:00:00Z
        assert row["payload"] == '{"a": [1], "b": 1}'
        assert (row["kind"], row["coordination"], row["flow"]) == (
            "business",
            "choreographed",
            "order.created",
        )
        assert (row["tenant_id"], row["sequence"], row["causation_id"]) == ("acme", 4, "c-1")

    def test_the_ddl(self):
        ddl = fluss_ddl("analytics.events")
        assert ddl.startswith("CREATE TABLE IF NOT EXISTS analytics.events (")
        assert "PRIMARY KEY (`dt`, `tenant_id`, `transaction_id`, `sequence`) NOT ENFORCED" in ddl
        assert "'table.datalake.enabled' = 'true'" in ddl
        assert "datalake" not in fluss_ddl(datalake=False)


class TestExport:
    async def test_every_event_once(self, log):
        fake = FakeFluss()
        await fill(log)
        job = exporter(log, fake)
        assert await job.export() == 5
        assert len(fake.rows) == 5
        assert {(k[0], k[1]) for k in fake.rows} == {
            ("2026-11-01", "acme"),
            ("2026-11-02", "globex"),
            ("2026-11-01", "globex"),
        }
        assert await job.export() == 0  # caught up
        metrics = job.metrics()
        assert (metrics["exported"], metrics["errors"], metrics["exporter"]) == (5, 0, "fluss")
        assert metrics["lag_seconds"] > 0
        await job.close()
        assert fake.closed == 1

    async def test_the_table_is_created_once_with_the_log_key(self, log):
        fake = FakeFluss()
        await fill(log)
        await exporter(log, fake).export()
        (database, table) = fake.created[:2]
        assert database == ("database", "sagaz", True)
        _, path, descriptor, ignore = table
        assert (path, ignore) == (("sagaz", "saga_log_event"), True)
        assert descriptor.schema.primary_keys == ["dt", "tenant_id", "transaction_id", "sequence"]
        assert descriptor.partition_keys == ["dt"]
        assert descriptor.bucket_keys == ["transaction_id"]
        assert descriptor.properties == {"table.datalake.enabled": "true"}
        schema = descriptor.schema.schema
        assert schema.field("occurred_at").type == pa.timestamp("us", tz="UTC")
        assert not schema.field("dt").nullable
        assert schema.field("flow").nullable
        assert fake.config == {"bootstrap.servers": "fluss:9123"}

    async def test_each_day_partition_is_created_once_per_session(self, log):
        fake = FakeFluss()
        await fill(log)
        job = exporter(log, fake)
        await job.export()
        days = [(path, spec["dt"], ignore) for path, spec, ignore in fake.partitions]
        assert days == [
            (("sagaz", "saga_log_event"), "2026-11-01", True),
            (("sagaz", "saga_log_event"), "2026-11-02", True),
        ]
        await job.close()  # a new session checks again (ignore_if_exists)
        with tenant_scope("acme"):
            await log.write(
                LogWrite(events=[LogEvent("t-1", "x", EventKind.LIFECYCLE, occurred_at=T0)])
            )
        await job.export()
        assert [spec["dt"] for _, spec, _ in fake.partitions][2:] == ["2026-11-01"]

    async def test_freshness_is_set_on_a_created_table(self, log):
        fake = FakeFluss()
        await fill(log)
        sink = FlussSink("fluss:9123", client=fake, freshness="30s")
        await SagaLogExporter(SagaLogReader(log, "f"), sink).export()
        descriptor = fake.created[1][2]
        assert descriptor.properties["table.datalake.freshness"] == "30s"
        assert table_properties(datalake=False, freshness="30s") == {}  # no lake, no freshness

    async def test_an_outage_loses_nothing(self, log):
        """Fluss fails in the middle of a batch; the exporter resumes and every event lands."""
        fake = FakeFluss()
        await fill(log)
        fake.fail_after = 3  # the second batch fails half-way
        job = exporter(log, fake)
        with pytest.raises(ConnectionError):
            await job.export()
        assert len(fake.rows) == 3  # one event of the failed batch landed

        fake.fail_after = None
        restarted = exporter(log, fake)  # a new process, from the stored cursor
        assert await restarted.export() == 3  # the failed batch again, then the rest
        assert len(fake.rows) == 5
        assert fake.connections == 2  # the failed session was dropped

    async def test_the_background_exporter_backs_off_and_recovers(self, log):
        fake = FakeFluss()
        await fill(log)
        fake.fail_after = 0
        job = exporter(log, fake, poll_interval=0.01, max_backoff=0.02)
        await job.start()
        await job.start()  # already running
        for _ in range(200):
            if job.errors >= 2:
                break
            await asyncio.sleep(0.005)
        assert job.metrics()["last_error"] == "ConnectionError: tablet server unreachable"
        fake.fail_after = None
        for _ in range(2000):  # up to 10 s on a loaded machine
            if len(fake.rows) == 5:
                break
            await asyncio.sleep(0.005)
        await job.close()
        assert len(fake.rows) == 5
        assert not job.running

    async def test_nothing_to_write_opens_no_connection(self):
        fake = FakeFluss()
        sink = FlussSink("fluss:9123", client=fake)
        await sink.write([])
        await sink.close()
        assert fake.connections == 0


class TestTimeout:
    async def test_a_write_fluss_never_acknowledges_times_out(self, log):
        """The client waits forever on a server that went away: the sink must not."""
        fake = FakeFluss()
        await fill(log)
        fake.hang = True
        sink = FlussSink("fluss:9123", client=fake, timeout=0.05)
        job = SagaLogExporter(SagaLogReader(log, "fluss", batch_size=2), sink)
        with pytest.raises(TimeoutError):
            await job.export()
        assert fake.closed == 1  # the stuck session was dropped (its close timed out too)
        fake.hang = False
        assert await job.export() == 5  # a new session, from the cursor
        assert len(fake.rows) == 5
        assert fake.connections == 2

    async def test_the_background_exporter_recovers_from_a_hang(self, log):
        fake = FakeFluss()
        await fill(log)
        fake.hang = True
        sink = FlussSink("fluss:9123", client=fake, timeout=0.05)
        job = SagaLogExporter(
            SagaLogReader(log, "fluss"), sink, poll_interval=0.01, max_backoff=0.02
        )
        await job.start()
        for _ in range(500):
            if job.errors:
                break
            await asyncio.sleep(0.01)
        assert job.metrics()["last_error"].startswith("TimeoutError")
        fake.hang = False
        for _ in range(2000):
            if len(fake.rows) == 5:
                break
            await asyncio.sleep(0.005)
        await job.close()
        assert len(fake.rows) == 5


class TestSinkSetup:
    def test_the_table_name_needs_a_database(self):
        with pytest.raises(ValueError, match="database.table"):
            FlussSink("fluss:9123", "events")

    async def test_a_failed_setup_closes_the_connection(self):
        fake = FakeFluss()

        def not_authorized(*args, **kwargs):
            msg = "not authorized"
            raise PermissionError(msg)

        fake.Schema = not_authorized  # creating the table fails
        sink = FlussSink("fluss:9123", client=fake)
        with pytest.raises(PermissionError):
            await sink.write([ExportedEvent(LogEvent("t", "e", EventKind.LIFECYCLE))])
        assert fake.closed == 1

    async def test_an_existing_table_is_used_as_is(self):
        fake = FakeFluss()
        sink = FlussSink("fluss:9123", "a.b", create_table=False, properties={"x": "1"})
        sink._client = fake
        await sink.write([ExportedEvent(LogEvent("t", "e", EventKind.LIFECYCLE, sequence=1))])
        assert fake.created == []
        assert fake.config == {"bootstrap.servers": "fluss:9123", "x": "1"}

    def test_without_the_client(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "fluss", None)  # importing it fails
        with pytest.raises(MissingDependencyError, match="pyfluss"):
            _ = FlussSink("fluss:9123").client


class TestRealClient:
    """The sink's calls against the real pyfluss module (installed up to Python 3.12)."""

    def test_the_table_descriptor_is_accepted(self):
        fluss = pytest.importorskip("fluss")
        from sagaz.integrations.fluss import (
            BUCKET_KEYS,
            PARTITION_KEY,
            PRIMARY_KEY,
            _arrow_schema,
            table_properties,
        )

        schema = fluss.Schema(_arrow_schema(), primary_keys=list(PRIMARY_KEY))
        fluss.TableDescriptor(
            schema,
            partition_keys=[PARTITION_KEY],
            bucket_keys=list(BUCKET_KEYS),
            properties=table_properties(),
        )
        fluss.TablePath("sagaz", "saga_log_event")
        fluss.Config({"bootstrap.servers": "localhost:9123"})
        assert callable(fluss.FlussConnection.create)


class TestCli:
    def test_fluss_ddl(self):
        result = CliRunner().invoke(cli, ["analytics", "fluss-ddl", "--table", "a.b"])
        assert result.exit_code == 0, result.output
        assert "CREATE TABLE IF NOT EXISTS a.b" in result.output

    def test_export_once(self, tmp_path, monkeypatch):
        path = tmp_path / "log.db"

        async def record():
            async with SQLiteSagaLogStore(str(path)) as store:
                await fill(store)

        asyncio.run(record())
        fake = FakeFluss()
        monkeypatch.setattr("sagaz.integrations.fluss.importlib.import_module", lambda _: fake)
        args = ["analytics", "export", "--saga-log", f"sqlite://{path}", "--to", "fluss://f:9123"]
        result = CliRunner().invoke(cli, [*args, "--once", "--freshness", "1min"])
        assert result.exit_code == 0, result.output
        assert "Exported 5 events to fluss://f:9123" in result.output
        again = CliRunner().invoke(cli, [*args, "--once"])
        assert "Exported 0 events" in again.output  # resumed from the cursor
        assert len(fake.rows) == 5
        assert fake.created[1][2].properties["table.datalake.freshness"] == "1min"

    def test_export_needs_a_fluss_target(self, tmp_path):
        args = ["analytics", "export", "--saga-log", "memory://", "--to", "kafka://k:9092"]
        result = CliRunner().invoke(cli, args)
        assert result.exit_code != 0
        assert "fluss://host:port" in result.output

    def test_export_runs_until_interrupted(self, monkeypatch):
        fake = FakeFluss()
        monkeypatch.setattr("sagaz.integrations.fluss.importlib.import_module", lambda _: fake)

        async def interrupt(self):
            raise asyncio.CancelledError

        monkeypatch.setattr(asyncio.Event, "wait", interrupt)
        args = ["analytics", "export", "--saga-log", "memory://", "--to", "fluss://f:9123"]
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, result.output
        assert "Exported 0 events" in result.output

    def test_payloads_are_json(self):
        row = fluss_row(ExportedEvent(LogEvent("t", "e", EventKind.BUSINESS, payload={"at": T0})))
        assert json.loads(row["payload"]) == {"at": str(T0)}


class TestFlinkSql:
    def test_reports_read_the_given_table(self):
        from sagaz.integrations.flink_sql import REPORTS, report

        for name in REPORTS:
            sql = report(name, "cat.db.events")
            assert "cat.db.events" in sql
            assert "{table}" not in sql

    def test_flow_summary_derives_status_from_lifecycle_events(self):
        from sagaz.integrations.flink_sql import report

        sql = report("flow-summary")
        assert "FROM iceberg.sagaz.saga_log_event" in sql
        for event_type in ("SagaCompleted", "SagaRolledBack", "SagaFailed", STATUS_CHANGED):
            assert f"'{event_type}'" in sql
        assert sql.count("ROW_NUMBER()") == 2  # the last status, and the duration ranks

    def test_a_table_that_is_not_an_identifier_is_refused(self):
        from sagaz.integrations.flink_sql import report

        for table in ("t; DROP TABLE x", "a.b.c.d", "1t", "cat.db.`t`", ""):
            with pytest.raises(ValueError, match="invalid table"):
                report("flow-summary", table)

    def test_an_unknown_report(self):
        from sagaz.integrations.flink_sql import report

        with pytest.raises(ValueError, match="flow-summary"):
            report("nope")

    def test_the_cli_prints_a_report(self):
        result = CliRunner().invoke(
            cli, ["analytics", "flink-sql", "flow-summary", "--table", "a.b.c"]
        )
        assert result.exit_code == 0, result.output
        assert result.output.startswith("WITH events AS (")
        bad = CliRunner().invoke(cli, ["analytics", "flink-sql", "nope"])
        assert bad.exit_code != 0
        assert "Unknown report" in bad.output
