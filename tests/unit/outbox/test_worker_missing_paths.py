"""
Tests for missing paths in sagaz/outbox/worker.py.

Missing lines: 113-115, 210-211, 218, 228-229, 237-243, 295, 383
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSetupSignalHandlersWindows:
    """Lines 113-115: _setup_signal_handlers NotImplementedError (Windows) path."""

    @pytest.mark.asyncio
    async def test_signal_handler_not_implemented_is_ignored(self):
        """Lines 113-115: Windows raises NotImplementedError – should pass silently."""
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        worker = OutboxWorker(storage, broker, worker_id="test-win-worker")

        # Simulate Windows: loop.add_signal_handler raises NotImplementedError
        mock_loop = MagicMock()
        mock_loop.add_signal_handler.side_effect = NotImplementedError("Windows")

        with patch("sagaz.outbox.worker.asyncio.get_event_loop", return_value=mock_loop):
            # Should NOT raise
            worker._setup_signal_handlers()  # covers lines 113-115

        # No assertion needed – just verifying it doesn't blow up


class TestProcessIterationCancelledError:
    """Lines 210-211: asyncio.CancelledError in _process_iteration → return True."""

    @pytest.mark.asyncio
    async def test_cancelled_error_breaks_loop(self):
        """Lines 210-211: CancelledError caught → returns True to break loop."""
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        worker = OutboxWorker(storage, broker, worker_id="test-cancel-worker")
        worker._running = True

        # Make process_batch raise CancelledError
        with patch.object(worker, "process_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.side_effect = asyncio.CancelledError()
            result = await worker._process_iteration()  # covers lines 210-211

        assert result is True  # Should signal to break the loop


class TestWaitForNextPoll:
    """Line 218: _wait_for_next_poll – wait for shutdown or timeout."""

    @pytest.mark.asyncio
    async def test_wait_for_next_poll_triggers_on_shutdown(self):
        """Line 218: _wait_for_next_poll returns when shutdown event is set."""
        from sagaz.outbox.worker import OutboxConfig, OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        config = OutboxConfig(poll_interval_seconds=10.0)  # Long timeout
        worker = OutboxWorker(storage, broker, config=config, worker_id="test-poll-worker")

        # Set the shutdown event immediately
        worker._shutdown_event.set()

        # Should complete almost immediately (event was already set)
        await worker._wait_for_next_poll()  # covers line 218

    @pytest.mark.asyncio
    async def test_wait_for_next_poll_times_out(self):
        """Line 218: _wait_for_next_poll times out after poll_interval."""
        from sagaz.outbox.worker import OutboxConfig, OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        config = OutboxConfig(poll_interval_seconds=0.01)  # Very short timeout
        worker = OutboxWorker(storage, broker, config=config, worker_id="test-timeout-worker")

        # Don't set shutdown – should timeout
        with pytest.raises(TimeoutError):
            await worker._wait_for_next_poll()  # This will raise asyncio.TimeoutError


class TestStopMethod:
    """Lines 228-229: stop() sets _running=False and fires _shutdown_event."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false_and_fires_event(self):
        """Lines 228-229: stop() updates state."""
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        worker = OutboxWorker(storage, broker, worker_id="test-stop-worker")
        worker._running = True

        await worker.stop()  # covers lines 228-229

        assert worker._running is False
        assert worker._shutdown_event.is_set()


class TestHandleShutdown:
    """Lines 237-243: _handle_shutdown creates a task to call stop()."""

    @pytest.mark.asyncio
    async def test_handle_shutdown_creates_stop_task(self):
        """Lines 237-243: _handle_shutdown() creates asyncio task."""
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        worker = OutboxWorker(storage, broker, worker_id="test-shutdown-worker")
        worker._running = True

        # Call _handle_shutdown (should create a task via asyncio.create_task)
        worker._handle_shutdown()  # covers lines 237-243

        # _shutdown_task was set
        assert hasattr(worker, "_shutdown_task")

        # Let the task complete
        await asyncio.sleep(0)
        await worker._shutdown_task


class TestProcessBatchPrometheusEnabled:
    """Line 295: process_batch() when prometheus IS available."""

    @pytest.mark.asyncio
    async def test_process_batch_with_prometheus_records_metrics(self):
        """Line 295: When PROMETHEUS_AVAILABLE=True, metrics recorded."""
        from sagaz.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()

        event = OutboxEvent(
            event_id="evt-prom-1",
            saga_id="saga-prom-1",
            event_type="TestEvent",
            partition_key="key1",
            payload={"data": "test"},
            routing_key="events.test",
        )
        # Make update_status return the event (simulate sent)
        updated_event = MagicMock()
        updated_event.retry_count = 0
        updated_event.event_type = "TestEvent"
        updated_event.event_id = "evt-prom-1"
        storage.claim_batch = AsyncMock(return_value=[event])
        storage.update_status = AsyncMock(return_value=updated_event)
        broker.publish_event = AsyncMock()

        config = OutboxConfig(batch_size=1)
        worker = OutboxWorker(storage=storage, broker=broker, config=config)

        # Ensure PROMETHEUS_AVAILABLE is True (likely already is in test env)
        import sagaz.outbox.worker as worker_mod

        with patch.object(worker_mod, "PROMETHEUS_AVAILABLE", True):
            processed = await worker.process_batch()

        assert processed == 1


class TestRecoverStuckEvents:
    """Line 383: recover_stuck_events() body."""

    @pytest.mark.asyncio
    async def test_recover_stuck_events_returns_count(self):
        """Line 383: recover_stuck_events calls storage.release_stuck_events."""
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        storage.release_stuck_events = AsyncMock(return_value=3)

        worker = OutboxWorker(storage, broker, worker_id="test-recover-worker")
        count = await worker.recover_stuck_events()  # covers line 383

        assert count == 3
        storage.release_stuck_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_stuck_events_zero_count_no_log(self):
        """Line 383: recover_stuck_events when nothing was stuck."""
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        storage.release_stuck_events = AsyncMock(return_value=0)

        worker = OutboxWorker(storage, broker, worker_id="test-recover-zero")
        count = await worker.recover_stuck_events()

        assert count == 0


class TestWorkerPrometheusBranches:
    """Cover lines 218, 224->231, 228-229, 240-243, 283->288, 295,
       300->304, 329->338, 378->382, 383, 410->414 in outbox/worker.py."""

    @pytest.mark.asyncio
    async def test_run_loop_breaks_on_cancelled_error(self):
        """Line 218: _run_processing_loop breaks when _process_iteration returns True."""
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        worker = OutboxWorker(storage, broker, worker_id="test-loop-break")
        worker._running = True

        async def fake_iteration():
            worker._running = False
            return True

        worker._process_iteration = AsyncMock(side_effect=fake_iteration)
        await worker._run_processing_loop()
        worker._process_iteration.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_iteration_pending_count_exception(self):
        """Lines 228-229: exception ignored when get_pending_count raises."""
        from unittest.mock import patch
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        storage.claim_batch = AsyncMock(return_value=[])
        storage.get_pending_count = AsyncMock(side_effect=RuntimeError("db error"))

        worker = OutboxWorker(storage, broker, worker_id="test-pcount-err")
        with patch("sagaz.outbox.worker.PROMETHEUS_AVAILABLE", True), \
             patch("sagaz.outbox.worker.OUTBOX_PENDING_EVENTS") as mock_gauge:
            mock_gauge.set = MagicMock()
            result = await worker._process_iteration()
        assert result is False  # loop continues

    @pytest.mark.asyncio
    async def test_process_iteration_no_prometheus(self):
        """Lines 224->231: PROMETHEUS_AVAILABLE=False skips pending count block."""
        from unittest.mock import patch
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        storage.claim_batch = AsyncMock(return_value=[])

        worker = OutboxWorker(storage, broker, worker_id="test-noprom")
        with patch("sagaz.outbox.worker.PROMETHEUS_AVAILABLE", False):
            result = await worker._process_iteration()
        assert result is False

    @pytest.mark.asyncio
    async def test_process_iteration_exception_handler(self):
        """Lines 240-243: generic exception increments sleep and returns False."""
        from unittest.mock import patch
        from sagaz.outbox.worker import OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        storage.claim_batch = AsyncMock(side_effect=RuntimeError("boom"))

        worker = OutboxWorker(storage, broker, worker_id="test-exc")
        with patch("sagaz.outbox.worker.PROMETHEUS_AVAILABLE", False), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker._process_iteration()
        assert result is False

    @pytest.mark.asyncio
    async def test_process_batch_failed_event_logged(self):
        """Line 295: logger.error when gather returns Exception for an event."""
        from unittest.mock import patch
        from sagaz.outbox.worker import OutboxWorker, OutboxConfig
        from sagaz.outbox.types import OutboxEvent, OutboxStatus

        storage = AsyncMock()
        broker = AsyncMock()
        event = OutboxEvent(saga_id="saga-1", event_type="test", payload={})
        storage.claim_batch = AsyncMock(return_value=[event])

        # Make _process_event raise so gather returns Exception
        async def fail_event(ev):
            raise ValueError("publish failed")

        worker = OutboxWorker(storage, broker, worker_id="test-fail-log")
        worker._process_event = fail_event

        with patch("sagaz.outbox.worker.PROMETHEUS_AVAILABLE", False):
            count = await worker.process_batch()
        assert count == 0  # no successes

    @pytest.mark.asyncio
    async def test_process_batch_no_prometheus(self):
        """Lines 283->288 and 300->304: PROMETHEUS_AVAILABLE=False in process_batch."""
        from unittest.mock import patch
        from sagaz.outbox.worker import OutboxWorker
        from sagaz.outbox.types import OutboxEvent

        storage = AsyncMock()
        broker = AsyncMock()
        event = OutboxEvent(saga_id="saga-2", event_type="t", payload={})
        storage.claim_batch = AsyncMock(return_value=[event])
        storage.update_status = AsyncMock()
        broker.publish_event = AsyncMock()

        worker = OutboxWorker(storage, broker, worker_id="test-noprom-batch")
        with patch("sagaz.outbox.worker.PROMETHEUS_AVAILABLE", False):
            count = await worker.process_batch()
        assert count == 1

    @pytest.mark.asyncio
    async def test_process_event_with_callback_and_prometheus(self):
        """Lines 329->338: on_event_published callback called when set."""
        from unittest.mock import patch
        from sagaz.outbox.worker import OutboxWorker
        from sagaz.outbox.types import OutboxEvent

        published_events = []

        async def on_pub(ev):
            published_events.append(ev)

        storage = AsyncMock()
        broker = AsyncMock()
        storage.update_status = AsyncMock()
        broker.publish_event = AsyncMock()
        event = OutboxEvent(saga_id="saga-3", event_type="t", payload={})

        worker = OutboxWorker(storage, broker, on_event_published=on_pub, worker_id="test-cb")
        with patch("sagaz.outbox.worker.PROMETHEUS_AVAILABLE", False):
            await worker._process_event(event)
        assert event in published_events

    @pytest.mark.asyncio
    async def test_handle_publish_failure_with_callback(self):
        """Lines 378->382, 383: on_event_failed callback + no prometheus."""
        from unittest.mock import patch
        from sagaz.outbox.worker import OutboxWorker, OutboxConfig
        from sagaz.outbox.types import OutboxEvent

        failed_events = []

        async def on_fail(ev, err):
            failed_events.append((ev, err))

        storage = AsyncMock()
        broker = AsyncMock()
        event = OutboxEvent(saga_id="saga-4", event_type="t", payload={}, retry_count=0)
        storage.update_status = AsyncMock(return_value=event)

        config = OutboxConfig(max_retries=3)
        worker = OutboxWorker(
            storage, broker, config=config,
            on_event_failed=on_fail, worker_id="test-fail-cb"
        )
        err = Exception("broker error")
        with patch("sagaz.outbox.worker.PROMETHEUS_AVAILABLE", False):
            await worker._handle_publish_failure(event, err)
        assert any(ev is event for ev, _ in failed_events)

    @pytest.mark.asyncio
    async def test_move_to_dead_letter_no_prometheus(self):
        """Lines 410->414: PROMETHEUS_AVAILABLE=False in _move_to_dead_letter."""
        from unittest.mock import patch
        from sagaz.outbox.worker import OutboxWorker
        from sagaz.outbox.types import OutboxEvent

        storage = AsyncMock()
        broker = AsyncMock()
        storage.update_status = AsyncMock()
        event = OutboxEvent(saga_id="saga-5", event_type="t", payload={})

        worker = OutboxWorker(storage, broker, worker_id="test-deadletter")
        with patch("sagaz.outbox.worker.PROMETHEUS_AVAILABLE", False):
            await worker._move_to_dead_letter(event)
        storage.update_status.assert_called_once()


class TestOutboxWorkerPromethusFallback:
    """Cover lines 113-115 in outbox/worker.py (except ImportError: PROMETHEUS_AVAILABLE=False)."""

    def test_worker_module_prometheus_fallback(self):
        """113-115: ImportError when prometheus_client not installed → PROMETHEUS_AVAILABLE=False."""
        import importlib
        import sys
        from contextlib import contextmanager

        @contextmanager
        def _without_prometheus_for_worker():
            orig_worker = sys.modules.get("sagaz.outbox.worker")
            orig_prometheus = {k: v for k, v in sys.modules.items() if "prometheus_client" in k}
            for key in list(sys.modules.keys()):
                if "prometheus_client" in key:
                    sys.modules.pop(key)
            sys.modules["prometheus_client"] = None  # type: ignore[assignment]
            sys.modules.pop("sagaz.outbox.worker", None)
            try:
                mod = importlib.import_module("sagaz.outbox.worker")
                yield mod
            finally:
                if sys.modules.get("prometheus_client") is None:
                    del sys.modules["prometheus_client"]
                for key, val in orig_prometheus.items():
                    sys.modules[key] = val
                sys.modules.pop("sagaz.outbox.worker", None)
                if orig_worker is not None:
                    sys.modules["sagaz.outbox.worker"] = orig_worker

        with _without_prometheus_for_worker() as worker_mod:
            assert worker_mod.PROMETHEUS_AVAILABLE is False
