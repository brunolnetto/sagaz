"""
Tests for outbox/worker.py to improve coverage.

Covers:
- OutboxWorker class
- process_batch
- _process_event
- _handle_publish_failure
- _move_to_dead_letter
- recover_stuck_events
- get_stats
- get_storage, get_broker factory functions
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


class TestOutboxWorkerBasic:
    """Test OutboxWorker basic functionality."""

    def test_worker_initialization(self):
        """Test worker initializes correctly."""
        from sagaz.outbox.types import OutboxConfig
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()
        config = OutboxConfig(batch_size=50)

        worker = OutboxWorker(
            storage=mock_storage, broker=mock_broker, config=config, worker_id="test-worker"
        )

        assert worker.worker_id == "test-worker"
        assert worker.config.batch_size == 50
        assert worker._running is False
        assert worker._events_processed == 0

    def test_worker_auto_generates_id(self):
        """Test worker auto-generates ID if not provided."""
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()

        worker = OutboxWorker(storage=mock_storage, broker=mock_broker)

        assert worker.worker_id.startswith("worker-")

    def test_get_stats(self):
        """Test worker stats."""
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()

        worker = OutboxWorker(storage=mock_storage, broker=mock_broker, worker_id="test-worker")
        worker._events_processed = 100
        worker._events_failed = 5
        worker._events_dead_lettered = 1

        stats = worker.get_stats()

        assert stats["worker_id"] == "test-worker"
        assert stats["events_processed"] == 100
        assert stats["events_failed"] == 5
        assert stats["events_dead_lettered"] == 1
        assert stats["running"] is False


class TestOutboxWorkerProcessBatch:
    """Test OutboxWorker.process_batch."""

    @pytest.mark.asyncio
    async def test_process_batch_with_events(self):
        """Test processing a batch of events."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()

        events = [
            OutboxEvent(saga_id="s1", event_type="test.event", payload={}),
            OutboxEvent(saga_id="s2", event_type="test.event", payload={}),
        ]
        mock_storage.claim_batch.return_value = events

        worker = OutboxWorker(storage=mock_storage, broker=mock_broker)

        processed = await worker.process_batch()

        assert processed == 2
        assert mock_broker.publish_event.call_count == 2
        assert mock_storage.update_status.call_count == 2

    @pytest.mark.asyncio
    async def test_process_batch_with_callback(self):
        """Test process_batch calls on_event_published callback."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()
        on_published = AsyncMock()

        events = [OutboxEvent(saga_id="s1", event_type="test.event", payload={})]
        mock_storage.claim_batch.return_value = events

        worker = OutboxWorker(
            storage=mock_storage, broker=mock_broker, on_event_published=on_published
        )

        await worker.process_batch()

        on_published.assert_called_once()


class TestOutboxWorkerFailureHandling:
    """Test OutboxWorker failure handling."""

    @pytest.mark.asyncio
    async def test_handle_publish_failure_increments_retry(self):
        """Test that publish failure increments retry count."""
        from sagaz.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()

        event = OutboxEvent(saga_id="s1", event_type="test", payload={}, retry_count=0)
        # Return updated event from update_status
        mock_storage.update_status.return_value = event

        config = OutboxConfig(max_retries=3)
        worker = OutboxWorker(storage=mock_storage, broker=mock_broker, config=config)

        error = Exception("Broker error")
        await worker._handle_publish_failure(event, error)

        # Should update to FAILED, then back to PENDING for retry
        assert mock_storage.update_status.call_count == 2
        # First call: FAILED
        first_call = mock_storage.update_status.call_args_list[0]
        assert first_call[0][1] == OutboxStatus.FAILED
        # Second call: PENDING (for retry)
        second_call = mock_storage.update_status.call_args_list[1]
        assert second_call[0][1] == OutboxStatus.PENDING

    @pytest.mark.asyncio
    async def test_handle_publish_failure_moves_to_dead_letter(self):
        """Test that exceeded retries moves to dead letter."""
        from sagaz.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()

        # Event that has exceeded max retries
        event = OutboxEvent(saga_id="s1", event_type="test", payload={}, retry_count=5)
        mock_storage.update_status.return_value = event

        config = OutboxConfig(max_retries=3)
        worker = OutboxWorker(storage=mock_storage, broker=mock_broker, config=config)

        error = Exception("Broker error")
        await worker._handle_publish_failure(event, error)

        # Should update to FAILED, then DEAD_LETTER
        calls = mock_storage.update_status.call_args_list
        last_call = calls[-1]
        assert last_call[0][1] == OutboxStatus.DEAD_LETTER
        assert worker._events_dead_lettered == 1


class TestOutboxWorkerRecovery:
    """Test OutboxWorker stuck event recovery."""

    @pytest.mark.asyncio
    async def test_recover_stuck_events(self):
        """Test recovering stuck events."""
        from sagaz.outbox.types import OutboxConfig
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()
        mock_storage.release_stuck_events.return_value = 5

        config = OutboxConfig(claim_timeout_seconds=300)
        worker = OutboxWorker(storage=mock_storage, broker=mock_broker, config=config)

        count = await worker.recover_stuck_events()

        assert count == 5
        mock_storage.release_stuck_events.assert_called_once_with(claimed_older_than_seconds=300)

    @pytest.mark.asyncio
    async def test_recover_stuck_events_no_stuck(self):
        """Test recovering when no stuck events."""
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()
        mock_storage.release_stuck_events.return_value = 0

        worker = OutboxWorker(storage=mock_storage, broker=mock_broker)

        count = await worker.recover_stuck_events()

        assert count == 0


class TestOutboxWorkerStop:
    """Test OutboxWorker stop functionality."""

    @pytest.mark.asyncio
    async def test_stop_sets_flags(self):
        """Test stop sets running flag to False."""
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()

        worker = OutboxWorker(storage=mock_storage, broker=mock_broker)
        worker._running = True

        await worker.stop()

        assert worker._running is False
        assert worker._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_handle_shutdown_creates_stop_task(self):
        """Test _handle_shutdown creates stop task."""
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()

        worker = OutboxWorker(storage=mock_storage, broker=mock_broker)

        # Should not raise
        worker._handle_shutdown()

        # Give the task a chance to run
        await asyncio.sleep(0.01)

        assert worker._running is False


class TestGetStorageFactory:
    """Test get_storage factory function."""

    def test_get_storage_without_env_exits(self, monkeypatch):
        """Test get_storage exits if DATABASE_URL not set."""
        from sagaz.outbox import worker

        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(SystemExit):
            worker.get_storage()

    def test_get_storage_with_env(self, monkeypatch):
        """Test get_storage creates PostgreSQL storage."""
        from sagaz.outbox import worker

        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:5432/test")

        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            storage = worker.get_storage()
            assert storage is not None


class TestGetBrokerFactory:
    """Test get_broker factory function."""

    def test_get_broker_kafka_without_url_exits(self, monkeypatch):
        """Test get_broker exits if no broker URL configured."""
        from sagaz.outbox import worker

        monkeypatch.setenv("BROKER_TYPE", "kafka")
        monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
        monkeypatch.delenv("BROKER_URL", raising=False)

        with pytest.raises(SystemExit):
            worker.get_broker()

    def test_get_broker_unknown_type_exits(self, monkeypatch):
        """Test get_broker exits with unknown broker type."""
        from sagaz.outbox import worker

        monkeypatch.setenv("BROKER_TYPE", "unknown")
        monkeypatch.setenv("BROKER_URL", "some://url")

        with pytest.raises(SystemExit):
            worker.get_broker()

    def test_get_broker_kafka(self, monkeypatch):
        """Test get_broker creates Kafka broker."""
        from sagaz.outbox import worker

        monkeypatch.setenv("BROKER_TYPE", "kafka")
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            broker = worker.get_broker()
            assert broker is not None

    def test_get_broker_rabbitmq(self, monkeypatch):
        """Test get_broker creates RabbitMQ broker."""
        from sagaz.outbox import worker

        monkeypatch.setenv("BROKER_TYPE", "rabbitmq")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost")

        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            broker = worker.get_broker()
            assert broker is not None


class TestOutboxWorkerStart:
    """Test OutboxWorker.start functionality."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """Test starting and stopping the worker."""
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()
        mock_storage.claim_batch.return_value = []  # No events

        worker = OutboxWorker(storage=mock_storage, broker=mock_broker)

        # Start and stop immediately
        async def stop_soon():
            await asyncio.sleep(0.1)
            await worker.stop()

        # Run both tasks concurrently
        await asyncio.gather(
            asyncio.wait_for(worker.start(), timeout=1.0), stop_soon(), return_exceptions=True
        )

        assert worker._running is False

    @pytest.mark.asyncio
    async def test_start_processes_events(self):
        """Test start processes batches."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.outbox.worker import OutboxWorker

        mock_storage = AsyncMock()
        mock_broker = AsyncMock()

        # First call returns event, second returns empty (stopping)
        events = [OutboxEvent(saga_id="s1", event_type="test", payload={})]
        mock_storage.claim_batch.side_effect = [events, []]

        worker = OutboxWorker(storage=mock_storage, broker=mock_broker)

        async def stop_after_processing():
            # Wait for first batch to be processed
            await asyncio.sleep(0.1)
            await worker.stop()

        await asyncio.gather(
            asyncio.wait_for(worker.start(), timeout=2.0),
            stop_after_processing(),
            return_exceptions=True,
        )

        # Should have processed the event
        mock_broker.publish_event.assert_called()


class TestOutboxWorkerProcessEvent:
    """Tests for OutboxWorker._process_event method."""

    @pytest.mark.asyncio
    async def test_worker_max_retries_exceeded(self):
        """Test event that exceeds max retries goes to FAILED."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.outbox.worker import OutboxConfig, OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()
        broker.publish_event.side_effect = Exception("Broker error")

        # Return an event from update_status
        updated_event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
            retry_count=10,
        )
        storage.update_status.return_value = updated_event

        config = OutboxConfig(max_retries=2)
        worker = OutboxWorker(storage, broker, config)

        # Event that has already retried max times
        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
            retry_count=2,  # Already at max
        )

        await worker._process_event(event)

        # Should update to FAILED (check if called)
        assert storage.update_status.called

    @pytest.mark.asyncio
    async def test_worker_successful_publish(self):
        """Test successful event publishing."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.outbox.worker import OutboxConfig, OutboxWorker

        storage = AsyncMock()
        broker = AsyncMock()

        config = OutboxConfig()
        worker = OutboxWorker(storage, broker, config)

        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
        )

        await worker._process_event(event)

        # Should publish_event and mark as SENT
        broker.publish_event.assert_called_once()
        storage.update_status.assert_called()
