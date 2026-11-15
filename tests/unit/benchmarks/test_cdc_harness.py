"""Pure parts of the CDC outbox benchmark harness (#50)."""

from __future__ import annotations

from benchmarks.cdc.__main__ import parse, table
from benchmarks.cdc.runner import Load, RecordingBroker, _result


def test_result_measures_lag_from_commit_to_publication():
    load = Load(events=3, rate=100, rows_per_tx=1)
    committed = {"a": 10.0, "b": 10.0, "c": 11.0}
    published = {"a": 10.010, "b": 10.050, "c": 11.100}

    result = _result("cdc", load, committed, published, started=9.9, produced_end=11.0)

    assert result.published == 3
    assert result.lag_p50_ms == 50.0
    assert result.lag_max_ms == 100.0
    assert result.throughput == round(3 / (11.1 - 9.9), 1)
    assert result.produced_rate == round(3 / 1.1, 1)


def test_result_with_nothing_published():
    result = _result("polling", Load(2, 0, 1), {"a": 1.0, "b": 1.0}, {}, 0.0, 1.0)
    assert (result.published, result.lag_p99_ms, result.lag_max_ms) == (0, 0.0, 0.0)


def test_table_and_arguments():
    result = _result("cdc", Load(1, 0, 1), {"a": 1.0}, {"a": 1.002}, 0.0, 1.0)
    lines = table([result]).splitlines()
    assert lines[0].startswith("| mode | events |")
    assert lines[2].startswith("| cdc | 1 | 0 |")

    args = parse(["--dsn", "postgresql://x/y", "--rates", "1000", "0", "--producers", "4"])
    assert (args.rates, args.producers, args.max_batch_delay, args.modes) == (
        [1000.0, 0.0],
        4,
        0.005,
        ["cdc", "polling"],
    )


async def test_recording_broker_records_publication_times():
    from sagaz.core.outbox.types import OutboxEvent

    broker = RecordingBroker()
    event = OutboxEvent(saga_id="s", event_type="t", payload={})
    await broker.publish_event(event)
    assert set(broker.published_at) == {event.event_id}
