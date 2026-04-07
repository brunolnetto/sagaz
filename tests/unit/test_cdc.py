"""
Unit tests for PR #66 — CDC/Debezium integration:
  - sagaz/integrations/cdc/metrics.py  (CDCMetrics)
  - sagaz/integrations/cdc/worker.py   (CDCEvent, CDCWorker)
  - sagaz/integrations/cdc/pg_logical.py (PgLogicalSource)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.integrations.cdc import CDCEvent, CDCEventType, CDCMetrics, CDCWorker, PgLogicalSource

# ---------------------------------------------------------------------------
# CDCMetrics
# ---------------------------------------------------------------------------


class TestCDCMetrics:
    def test_initial_state(self):
        m = CDCMetrics()
        assert m.events_total == 0
        assert m.errors_total == 0
        assert m.mean_lag_seconds == 0.0

    def test_record_event_increments_counter(self):
        m = CDCMetrics()
        m.record_event(lag_ms=50.0)
        assert m.events_total == 1

    def test_mean_lag_calculated(self):
        m = CDCMetrics()
        m.record_event(lag_ms=100.0)
        m.record_event(lag_ms=200.0)
        assert m.mean_lag_seconds == pytest.approx(0.15)

    def test_increment_error(self):
        m = CDCMetrics()
        m.increment_error()
        m.increment_error()
        assert m.errors_total == 2

    def test_snapshot_keys(self):
        m = CDCMetrics()
        snap = m.snapshot()
        assert "sagaz_cdc_events_total" in snap
        assert "sagaz_cdc_errors_total" in snap
        assert "sagaz_cdc_lag_seconds" in snap

    def test_reset_clears_counters(self):
        m = CDCMetrics()
        m.record_event(10.0)
        m.increment_error()
        m.reset()
        assert m.events_total == 0
        assert m.errors_total == 0

    def test_mean_lag_zero_when_no_events(self):
        m = CDCMetrics()
        assert m.mean_lag_seconds == 0.0


# ---------------------------------------------------------------------------
# CDCEvent
# ---------------------------------------------------------------------------


class TestCDCEvent:
    def test_from_debezium_payload_insert(self):
        payload = {
            "op": "c",
            "source": {"table": "saga_state", "lsn": "123456"},
            "before": None,
            "after": {"saga_id": "s1", "status": "executing"},
            "ts_ms": 1700000000000,
        }
        ev = CDCEvent.from_debezium_payload(payload)
        assert ev.table == "saga_state"
        assert ev.op == CDCEventType.INSERT
        assert ev.after["saga_id"] == "s1"
        assert ev.saga_id == "s1"

    def test_from_debezium_payload_delete(self):
        payload = {
            "op": "d",
            "source": {"table": "saga_events"},
            "before": {"saga_id": "s2"},
            "after": None,
        }
        ev = CDCEvent.from_debezium_payload(payload)
        assert ev.op == CDCEventType.DELETE
        assert ev.saga_id == "s2"

    def test_from_debezium_payload_unknown_op_defaults_to_read(self):
        payload = {"op": "x", "source": {}, "before": None, "after": None}
        ev = CDCEvent.from_debezium_payload(payload)
        assert ev.op == CDCEventType.READ

    def test_saga_id_none_when_no_row(self):
        ev = CDCEvent(table="t", op=CDCEventType.READ, before=None, after=None)
        assert ev.saga_id is None


# ---------------------------------------------------------------------------
# CDCWorker
# ---------------------------------------------------------------------------


class TestCDCWorker:
    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        worker = CDCWorker("http://debezium:8083")
        # Prevent actual polling
        with patch.object(worker, "_http_get", new=AsyncMock(return_value={"records": []})):
            await worker.start()
            assert worker.is_running
            await worker.stop()
            assert not worker.is_running

    @pytest.mark.asyncio
    async def test_events_dispatched_to_callback(self):
        received = []

        async def handle(ev: CDCEvent) -> None:
            received.append(ev)

        payload = {
            "records": [
                {
                    "op": "c",
                    "source": {"table": "saga_state", "lsn": "1"},
                    "before": None,
                    "after": {"saga_id": "s1"},
                    "ts_ms": 0,
                }
            ]
        }

        worker = CDCWorker("http://debezium:8083", on_event=handle, poll_interval=0.01)

        call_count = 0

        async def mock_http(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return payload
            await asyncio.sleep(1000)  # stall further
            return {"records": []}

        with patch.object(worker, "_http_get", new=mock_http):
            await worker.start()
            await asyncio.sleep(0.05)
            await worker.stop()

        assert any(ev.saga_id == "s1" for ev in received)

    @pytest.mark.asyncio
    async def test_metrics_updated_on_event(self):
        metrics = CDCMetrics()
        worker = CDCWorker("http://debezium:8083", metrics=metrics, poll_interval=0.01)

        payload = {
            "records": [
                {
                    "op": "u",
                    "source": {"table": "saga_state", "lsn": "2"},
                    "before": {"status": "executing"},
                    "after": {"status": "completed"},
                    "ts_ms": 0,
                }
            ]
        }

        call_count = 0

        async def mock_http(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return payload
            await asyncio.sleep(1000)
            return {"records": []}

        with patch.object(worker, "_http_get", new=mock_http):
            await worker.start()
            await asyncio.sleep(0.05)
            await worker.stop()

        assert metrics.events_total >= 1

    @pytest.mark.asyncio
    async def test_http_error_increments_error_counter(self):
        metrics = CDCMetrics()
        worker = CDCWorker("http://debezium:8083", metrics=metrics, poll_interval=0.01)

        async def bad_http(url):
            msg = "refused"
            raise ConnectionError(msg)

        call_count = 0

        async def once_then_block(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "refused"
                raise ConnectionError(msg)
            await asyncio.sleep(1000)

        with patch.object(worker, "_http_get", new=once_then_block):
            await worker.start()
            await asyncio.sleep(0.05)
            await worker.stop()

        assert metrics.errors_total >= 1

    @pytest.mark.asyncio
    async def test_get_metrics_returns_dict(self):
        worker = CDCWorker("http://debezium:8083")
        m = worker.get_metrics()
        assert "sagaz_cdc_events_total" in m


# ---------------------------------------------------------------------------
# PgLogicalSource
# ---------------------------------------------------------------------------


class TestPgLogicalSource:
    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        source = PgLogicalSource("postgresql://localhost/sagaz")

        # _connect raises RuntimeError (asyncpg not available or no server)
        # _replication_loop catches it and exits cleanly
        async def fake_connect():
            msg = "no server"
            raise RuntimeError(msg)

        with patch.object(source, "_connect", new=fake_connect):
            await source.start()
            await asyncio.sleep(0.02)  # let loop exit
            await source.stop()

        assert not source.is_running

    @pytest.mark.asyncio
    async def test_events_forwarded_to_callback(self):
        received = []

        async def handler(ev: CDCEvent) -> None:
            received.append(ev)

        source = PgLogicalSource("postgresql://localhost/sagaz", on_event=handler)

        fake_conn = MagicMock()

        async def fake_connect():
            return fake_conn

        async def fake_stream(conn):
            yield MagicMock(relation={"name": "saga_state"})

        async def fake_close(conn):
            pass

        with (
            patch.object(source, "_connect", new=fake_connect),
            patch.object(source, "_stream_messages", new=fake_stream),
            patch.object(source, "_close", new=fake_close),
        ):
            await source.start()
            await asyncio.sleep(0.05)
            await source.stop()

        assert len(received) >= 1

    @pytest.mark.asyncio
    async def test_get_metrics(self):
        source = PgLogicalSource("postgresql://localhost/sagaz")
        m = source.get_metrics()
        assert "sagaz_cdc_events_total" in m
