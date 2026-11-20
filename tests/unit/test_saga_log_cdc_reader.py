"""The saga log's CDC reader with a fake replication source (#495)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner

from sagaz.cli.app import cli
from sagaz.core.storage.saga_log import (
    Coordination,
    EventKind,
    InMemorySagaLogStore,
    LogEvent,
    LogWrite,
    SagaLogExporter,
    Transaction,
)
from sagaz.core.tenant import tenant_scope
from sagaz.integrations.cdc._types import CDCChange, CDCError
from sagaz.integrations.cdc.saga_log import SagaLogCDCReader, log_event_from_row

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def row(tid="t-1", sequence=1, **overrides) -> dict:
    """A ``saga_log_event`` row as pgoutput hands it over: text values."""
    values = {
        "tenant_id": "acme",
        "transaction_id": tid,
        "sequence": str(sequence),
        "event_id": f"{tid}-{sequence}",
        "event_type": "order.created",
        "kind": "business",
        "source": "orders",
        "causation_id": None,
        "payload": json.dumps({"amount": 40}),
        "occurred_at": "2026-11-20 12:00:00.5+00",
        "event_version": "1",
        "writer_xid": "1234",
    }
    return {**values, **overrides}


class FakeSource:
    def __init__(self, batches: list[list[CDCChange]]) -> None:
        self.batches = batches
        self.acked: list[int] = []
        self.started = self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1

    async def poll(self, timeout: float) -> list[CDCChange]:
        return self.batches.pop(0) if self.batches else []

    async def ack(self, position) -> None:
        self.acked.append(int(position))


def change(lsn: int, **row_values) -> CDCChange:
    return CDCChange(log_event_from_row(row(**row_values)), T0, lsn)


class TestRowMapping:
    def test_a_row_becomes_a_log_event(self):
        event = log_event_from_row(row(sequence=7))
        assert (event.tenant_id, event.transaction_id, event.sequence) == ("acme", "t-1", 7)
        assert event.kind == EventKind.BUSINESS
        assert event.payload == {"amount": 40}
        assert event.occurred_at == datetime(2026, 11, 20, 12, 0, 0, 500000, tzinfo=UTC)

    def test_defaults_for_optional_columns(self):
        event = log_event_from_row(row(tenant_id=None, payload=None, event_version=None))
        assert (event.tenant_id, event.payload, event.event_version) == ("default", {}, 1)

    @pytest.mark.parametrize(
        "broken", [{"kind": "nope"}, {"sequence": "x"}, {"occurred_at": None}, {"payload": "{"}]
    )
    def test_rows_it_cannot_map(self, broken):
        with pytest.raises(CDCError, match="saga_log_event"):
            log_event_from_row(row(**broken))


async def make_log() -> InMemorySagaLogStore:
    log = InMemorySagaLogStore()
    with tenant_scope("acme"):
        await log.write(
            LogWrite(transaction=Transaction("t-1", "order.created", Coordination.CHOREOGRAPHED))
        )
    return log


class TestReader:
    async def test_batches_and_acknowledgements(self):
        log = await make_log()
        source = FakeSource([[change(100), change(100, sequence=2)], [change(250, tid="t-9")]])
        reader = SagaLogCDCReader(log, "unused", name="fluss", source=source)

        first = await reader.read()
        assert [e.event.sequence for e in first.events] == [1, 2]
        assert (first.events[0].coordination, first.events[0].flow) == (
            "choreographed",
            "order.created",
        )
        assert first.position == "100"
        await reader.acknowledge(first)
        assert (source.acked, reader.position) == ([100], "100")

        second = await reader.read()  # a transaction the log does not know
        assert (second.events[0].coordination, second.events[0].flow) == (None, None)
        idle = await reader.read()
        assert (idle.events, idle.position) == ([], "100")  # nothing acknowledged since
        await reader.acknowledge(idle)  # a no-op
        assert source.acked == [100]
        await reader.close()
        await reader.close()
        assert (source.started, source.stopped) == (1, 1)

    async def test_the_exporter_closes_the_reader(self):
        log = await make_log()
        source = FakeSource([[change(100)]])
        written = []

        class Sink:
            async def write(self, events):
                written.extend(events)

            async def close(self):
                pass

        exporter = SagaLogExporter(SagaLogCDCReader(log, "unused", source=source), Sink())
        assert await exporter.export() == 1
        await exporter.close()
        assert source.acked == [100]
        assert source.stopped == 1

    def test_a_default_source_is_named_after_the_reader(self):
        reader = SagaLogCDCReader(InMemorySagaLogStore(), "postgresql://h/db", name="Fluss-EU")
        assert (reader.source.slot, reader.source.publication) == (
            "sagaz_log_fluss_eu",
            "sagaz_log_fluss_eu_pub",
        )
        assert reader.source.table == "saga_log_event"


def test_the_cli_needs_a_postgresql_log_for_cdc():
    args = ["analytics", "export", "--saga-log", "memory://", "--to", "fluss://f:9123", "--cdc"]
    result = CliRunner().invoke(cli, [*args, "--once"])
    assert result.exit_code != 0
    assert "PostgreSQL saga log" in result.output


def test_events_are_logged_in_commit_order():
    """The LogEvent fields the exporter relies on survive the mapping."""
    event = log_event_from_row(row(causation_id="c-1", source=None))
    assert isinstance(event, LogEvent)
    assert (event.causation_id, event.source) == ("c-1", None)
