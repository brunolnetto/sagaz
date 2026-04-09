"""
Unit tests for PR #67 — Fluss + Iceberg monitoring:
  - sagaz/monitoring/fluss.py  (FlussAnalyticsListener)
  - sagaz/monitoring/iceberg.py (IcebergTieringJob)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.monitoring.fluss import FlussAnalyticsListener, FlussEvent
from sagaz.monitoring.iceberg import IcebergRecord, IcebergTieringJob

# ---------------------------------------------------------------------------
# FlussEvent
# ---------------------------------------------------------------------------


class TestFlussEvent:
    def test_to_row_contains_required_fields(self):
        ev = FlussEvent(saga_id="s1", event_type="saga_completed", duration_ms=99.0)
        row = ev.to_row()
        assert row["saga_id"] == "s1"
        assert row["event_type"] == "saga_completed"
        assert row["duration_ms"] == 99.0
        assert "ts" in row


# ---------------------------------------------------------------------------
# FlussAnalyticsListener
# ---------------------------------------------------------------------------


class TestFlussAnalyticsListener:
    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        with patch.object(listener, "_write_rows", new=AsyncMock()):
            await listener.start()
            assert listener._running
            await listener.stop()
            assert not listener._running

    @pytest.mark.asyncio
    async def test_on_saga_completed_buffers_event(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        await listener.on_saga_completed("s1", duration_ms=50.0)
        assert len(listener._buffer) == 1
        assert listener._buffer[0].event_type == "saga_completed"

    @pytest.mark.asyncio
    async def test_on_saga_started_buffers_event(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        await listener.on_saga_started("s1")
        assert listener._buffer[0].event_type == "saga_started"

    @pytest.mark.asyncio
    async def test_on_saga_failed_buffers_event(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        await listener.on_saga_failed("s1")
        assert listener._buffer[0].event_type == "saga_failed"

    @pytest.mark.asyncio
    async def test_on_saga_rolled_back_buffers_event(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        await listener.on_saga_rolled_back("s1")
        assert listener._buffer[0].event_type == "saga_rolled_back"

    @pytest.mark.asyncio
    async def test_on_step_executed_buffers_event(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        await listener.on_step_executed("s1", "reserve", duration_ms=5.0)
        assert listener._buffer[0].step_name == "reserve"

    @pytest.mark.asyncio
    async def test_on_step_failed_buffers_event(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        await listener.on_step_failed("s1", "pay")
        assert listener._buffer[0].event_type == "step_failed"

    @pytest.mark.asyncio
    async def test_flush_writes_rows(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        written = []

        async def fake_write(rows):
            written.extend(rows)

        with patch.object(listener, "_write_rows", new=fake_write):
            await listener.on_saga_completed("s1")
            await listener._do_flush()

        assert len(written) == 1
        assert written[0].saga_id == "s1"

    @pytest.mark.asyncio
    async def test_flush_clears_buffer(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        with patch.object(listener, "_write_rows", new=AsyncMock()):
            await listener.on_saga_completed("s1")
            await listener._do_flush()
        assert len(listener._buffer) == 0

    @pytest.mark.asyncio
    async def test_write_error_increments_errors(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)

        async def bad_write(rows):
            msg = "refused"
            raise ConnectionError(msg)

        with patch.object(listener, "_write_rows", new=bad_write):
            await listener.on_saga_completed("s1")
            await listener._do_flush()

        assert listener._errors == 1

    @pytest.mark.asyncio
    async def test_buffer_auto_flush_on_buffer_size_exceeded(self):
        listener = FlussAnalyticsListener(flush_interval=100.0, buffer_size=2)
        flushed = []

        async def fake_write(rows):
            flushed.extend(rows)

        with patch.object(listener, "_write_rows", new=fake_write):
            await listener.start()
            await listener.on_saga_completed("s1")
            await listener.on_saga_completed("s2")
            # Give ensure_future a chance to run
            await asyncio.sleep(0.05)
            await listener.stop()

    @pytest.mark.asyncio
    async def test_metrics_structure(self):
        listener = FlussAnalyticsListener()
        m = listener.metrics()
        assert "events_written" in m
        assert "errors" in m
        assert "buffer_size" in m

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining_buffer(self):
        listener = FlussAnalyticsListener(flush_interval=100.0)
        written = []

        async def fake_write(rows):
            written.extend(rows)

        with patch.object(listener, "_write_rows", new=fake_write):
            await listener.start()
            await listener.on_saga_completed("s1")
            await listener.stop()

        assert len(written) == 1


# ---------------------------------------------------------------------------
# IcebergRecord
# ---------------------------------------------------------------------------


class TestIcebergRecord:
    def test_to_dict(self):
        rec = IcebergRecord(
            saga_id="s1",
            saga_name="OrderSaga",
            status="completed",
            started_at="2024-01-01T00:00:00+00:00",
            completed_at="2024-01-01T00:01:00+00:00",
            duration_ms=60000.0,
            step_count=4,
        )
        d = rec.to_dict()
        assert d["saga_id"] == "s1"
        assert d["step_count"] == 4


# ---------------------------------------------------------------------------
# IcebergTieringJob
# ---------------------------------------------------------------------------


class TestIcebergTieringJob:
    @pytest.mark.asyncio
    async def test_lifecycle(self):
        job = IcebergTieringJob(flush_interval=100.0)
        with patch.object(job, "_write_batch", new=AsyncMock()):
            await job.start()
            assert job.is_running
            await job.stop()
            assert not job.is_running

    def test_tier_event_buffers_record(self):
        job = IcebergTieringJob()
        rec = IcebergRecord("s1", "X", "completed", "t1", "t2", 10.0, 1)
        job.tier_event(rec)
        assert len(job._buffer) == 1

    @pytest.mark.asyncio
    async def test_do_tier_writes_records(self):
        job = IcebergTieringJob(batch_size=10)
        written = []

        async def fake_write(batch):
            written.extend(batch)

        with patch.object(job, "_write_batch", new=fake_write):
            rec = IcebergRecord("s1", "X", "completed", "t1", "t2", 10.0, 1)
            job.tier_event(rec)
            await job._do_tier()

        assert len(written) == 1
        assert job._records_written == 1

    @pytest.mark.asyncio
    async def test_write_error_increments_errors(self):
        job = IcebergTieringJob()

        async def bad_write(batch):
            msg = "S3 unreachable"
            raise ConnectionError(msg)

        with patch.object(job, "_write_batch", new=bad_write):
            job.tier_event(IcebergRecord("s1", "X", "completed", "t1", None, 0.0, 0))
            await job._do_tier()

        assert job._errors == 1

    @pytest.mark.asyncio
    async def test_metrics_structure(self):
        job = IcebergTieringJob()
        m = job.metrics()
        assert "records_written" in m
        assert "errors" in m
        assert "buffer_size" in m

    @pytest.mark.asyncio
    async def test_stop_flushes_buffer(self):
        job = IcebergTieringJob(flush_interval=100.0)
        written = []

        async def fake_write(batch):
            written.extend(batch)

        with patch.object(job, "_write_batch", new=fake_write):
            await job.start()
            job.tier_event(IcebergRecord("s1", "Y", "completed", "t1", "t2", 1.0, 2))
            await job.stop()

        assert len(written) == 1

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        """stop() with _tier_task=None should not raise."""
        job = IcebergTieringJob()
        await job.stop()
        assert not job.is_running

    @pytest.mark.asyncio
    async def test_write_batch_makes_http_request(self):
        """_write_batch sends a POST to the catalog URL."""
        job = IcebergTieringJob(catalog_url="http://catalog:8181")
        rec = IcebergRecord("s1", "X", "completed", "t1", "t2", 5.0, 1)
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read = MagicMock(return_value=b"ok")
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            await job._write_batch([rec])
        mock_open.assert_called_once()

    @pytest.mark.asyncio
    async def test_do_tier_empty_buffer_is_noop(self):
        job = IcebergTieringJob()
        await job._do_tier()
        assert job._records_written == 0


class TestFlussWriteRows:
    @pytest.mark.asyncio
    async def test_write_rows_makes_http_request(self):
        """_write_rows sends a POST to the Fluss endpoint."""
        listener = FlussAnalyticsListener(fluss_url="http://fluss:9000")
        ev = FlussEvent(saga_id="s1", event_type="saga_started")
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read = MagicMock(return_value=b"ok")
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            await listener._write_rows([ev])
        mock_open.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_requeues_on_error(self):
        """On write failure, events are partially re-queued."""
        listener = FlussAnalyticsListener(flush_interval=100.0, buffer_size=10)
        call_count = 0

        async def bad_write(rows):
            nonlocal call_count
            call_count += 1
            msg = "network error"
            raise OSError(msg)

        with patch.object(listener, "_write_rows", new=bad_write):
            await listener.on_saga_completed("s1")
            await listener.on_saga_completed("s2")
            await listener._do_flush()

        assert listener._errors == 1
        # partial re-queue (up to buffer_size // 2 = 5 items)
        assert len(listener._buffer) <= listener._buffer_size // 2

    @pytest.mark.asyncio
    async def test_stop_without_flush_task_is_safe(self):
        """stop() before start() should not raise."""
        listener = FlussAnalyticsListener()
        await listener.stop()
        assert not listener._running
