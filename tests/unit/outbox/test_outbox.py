"""
Tests for the Outbox Pattern implementation.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from sagaz.outbox import (
    BrokerConnectionError,
    BrokerError,
    InMemoryBroker,
    InMemoryOutboxStorage,
    InvalidStateTransitionError,
    OutboxConfig,
    OutboxEvent,
    OutboxStateMachine,
    OutboxStatus,
    OutboxWorker,
)


class TestOutboxEvent:
    """Tests for OutboxEvent dataclass."""

    def test_create_basic_event(self):
        """Test creating a basic event."""
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="OrderCreated",
            payload={"order_id": "ORD-456"},
        )

        assert event.saga_id == "saga-123"
        assert event.event_type == "OrderCreated"
        assert event.payload == {"order_id": "ORD-456"}
        assert event.status == OutboxStatus.PENDING
        assert event.aggregate_type == "saga"
        assert event.aggregate_id == "saga-123"  # Defaults to saga_id
        assert event.retry_count == 0

    def test_create_event_with_all_fields(self):
        """Test creating an event with all fields."""
        now = datetime.now(UTC)

        event = OutboxEvent(
            event_id="evt-123",
            saga_id="saga-123",
            aggregate_type="order",
            aggregate_id="ORD-456",
            event_type="OrderCreated",
            payload={"items": []},
            headers={"trace_id": "abc"},
            status=OutboxStatus.PENDING,
            created_at=now,
        )

        assert event.event_id == "evt-123"
        assert event.aggregate_type == "order"
        assert event.aggregate_id == "ORD-456"
        assert event.headers == {"trace_id": "abc"}

    def test_to_dict(self):
        """Test serializing event to dict."""
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={"key": "value"},
        )

        data = event.to_dict()

        assert data["saga_id"] == "saga-123"
        assert data["event_type"] == "Test"
        assert data["payload"] == {"key": "value"}
        assert data["status"] == "pending"
        assert "event_id" in data
        assert "created_at" in data

    def test_from_dict(self):
        """Test deserializing event from dict."""
        data = {
            "event_id": "evt-123",
            "saga_id": "saga-123",
            "event_type": "Test",
            "payload": {"key": "value"},
            "status": "sent",
        }

        event = OutboxEvent.from_dict(data)

        assert event.event_id == "evt-123"
        assert event.saga_id == "saga-123"
        assert event.status == OutboxStatus.SENT


class TestOutboxStatus:
    """Tests for OutboxStatus enum."""

    def test_all_statuses_exist(self):
        """Test that all expected statuses exist."""
        assert OutboxStatus.PENDING.value == "pending"
        assert OutboxStatus.CLAIMED.value == "claimed"
        assert OutboxStatus.SENT.value == "sent"
        assert OutboxStatus.FAILED.value == "failed"
        assert OutboxStatus.DEAD_LETTER.value == "dead_letter"


class TestOutboxStateMachine:
    """Tests for OutboxStateMachine."""

    def test_claim_event(self):
        """Test claiming a pending event."""
        sm = OutboxStateMachine()
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={},
        )

        event = sm.claim(event, "worker-1")

        assert event.status == OutboxStatus.CLAIMED
        assert event.worker_id == "worker-1"
        assert event.claimed_at is not None

    def test_claim_non_pending_fails(self):
        """Test that claiming non-pending event fails."""
        sm = OutboxStateMachine()
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={},
        )
        event.status = OutboxStatus.SENT

        with pytest.raises(InvalidStateTransitionError):
            sm.claim(event, "worker-1")

    def test_mark_sent(self):
        """Test marking event as sent."""
        sm = OutboxStateMachine()
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={},
        )
        event.status = OutboxStatus.CLAIMED

        event = sm.mark_sent(event)

        assert event.status == OutboxStatus.SENT
        assert event.sent_at is not None

    def test_mark_failed(self):
        """Test marking event as failed."""
        sm = OutboxStateMachine()
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={},
        )
        event.status = OutboxStatus.CLAIMED

        event = sm.mark_failed(event, "Connection refused")

        assert event.status == OutboxStatus.FAILED
        assert event.retry_count == 1
        assert event.last_error == "Connection refused"

    def test_retry(self):
        """Test retrying a failed event."""
        sm = OutboxStateMachine(max_retries=3)
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={},
        )
        event.status = OutboxStatus.FAILED
        event.retry_count = 1

        event = sm.retry(event)

        assert event.status == OutboxStatus.PENDING
        assert event.worker_id is None
        assert event.claimed_at is None

    def test_retry_exceeds_max(self):
        """Test that retry fails when max exceeded."""
        sm = OutboxStateMachine(max_retries=3)
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={},
        )
        event.status = OutboxStatus.FAILED
        event.retry_count = 3

        with pytest.raises(ValueError, match="exceeded max retries"):
            sm.retry(event)

    def test_move_to_dead_letter(self):
        """Test moving to dead letter queue."""
        sm = OutboxStateMachine()
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={},
        )
        event.status = OutboxStatus.FAILED

        event = sm.move_to_dead_letter(event)

        assert event.status == OutboxStatus.DEAD_LETTER

    def test_can_retry(self):
        """Test can_retry check."""
        sm = OutboxStateMachine(max_retries=3)

        event = OutboxEvent(saga_id="s", event_type="t", payload={})
        event.status = OutboxStatus.FAILED
        event.retry_count = 1

        assert sm.can_retry(event) is True

        event.retry_count = 3
        assert sm.can_retry(event) is False

    def test_should_dead_letter(self):
        """Test should_dead_letter check."""
        sm = OutboxStateMachine(max_retries=3)

        event = OutboxEvent(saga_id="s", event_type="t", payload={})
        event.status = OutboxStatus.FAILED
        event.retry_count = 3

        assert sm.should_dead_letter(event) is True

        event.retry_count = 2
        assert sm.should_dead_letter(event) is False

    def test_transition_callback(self):
        """Test transition callback is called."""
        transitions = []

        def on_transition(event, old_status, new_status):
            transitions.append((old_status, new_status))

        sm = OutboxStateMachine(on_transition=on_transition)
        event = OutboxEvent(saga_id="s", event_type="t", payload={})

        sm.claim(event, "worker-1")

        assert len(transitions) == 1
        assert transitions[0] == (OutboxStatus.PENDING, OutboxStatus.CLAIMED)


class TestInMemoryBroker:
    """Tests for InMemoryBroker."""

    @pytest.mark.asyncio
    async def test_connect_and_publish(self):
        """Test connecting and publishing."""
        broker = InMemoryBroker()
        await broker.connect()

        assert broker.is_connected is True

        await broker.publish("topic1", b"message1")

        messages = broker.get_messages("topic1")
        assert len(messages) == 1
        assert messages[0]["message"] == b"message1"

    @pytest.mark.asyncio
    async def test_publish_with_headers(self):
        """Test publishing with headers."""
        broker = InMemoryBroker()
        await broker.connect()

        await broker.publish("topic1", b"message", headers={"trace_id": "abc"}, key="order-123")

        messages = broker.get_messages("topic1")
        assert messages[0]["headers"] == {"trace_id": "abc"}
        assert messages[0]["key"] == "order-123"

    @pytest.mark.asyncio
    async def test_publish_without_connect_fails(self):
        """Test that publishing without connect fails."""
        broker = InMemoryBroker()

        with pytest.raises(BrokerConnectionError):
            await broker.publish("topic1", b"message")

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check."""
        broker = InMemoryBroker()

        assert await broker.health_check() is False

        await broker.connect()
        assert await broker.health_check() is True

        await broker.close()
        assert await broker.health_check() is False

    @pytest.mark.asyncio
    async def test_publish_event(self):
        """Test publishing an OutboxEvent."""
        broker = InMemoryBroker()
        await broker.connect()

        event = OutboxEvent(
            saga_id="saga-123",
            event_type="OrderCreated",
            payload={"order_id": "ORD-456"},
        )

        await broker.publish_event(event)

        messages = broker.get_messages("OrderCreated")
        assert len(messages) == 1


class TestInMemoryOutboxStorage:
    """Tests for InMemoryOutboxStorage."""

    @pytest.mark.asyncio
    async def test_insert_and_get(self):
        """Test inserting and retrieving events."""
        storage = InMemoryOutboxStorage()

        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={"key": "value"},
        )

        await storage.insert(event)

        retrieved = await storage.get_by_id(event.event_id)
        assert retrieved is not None
        assert retrieved.saga_id == "saga-123"

    @pytest.mark.asyncio
    async def test_claim_batch(self):
        """Test claiming a batch of events."""
        storage = InMemoryOutboxStorage()

        # Insert multiple events
        for i in range(5):
            await storage.insert(
                OutboxEvent(
                    saga_id=f"saga-{i}",
                    event_type="Test",
                    payload={},
                )
            )

        # Claim batch
        claimed = await storage.claim_batch("worker-1", batch_size=3)

        assert len(claimed) == 3
        for event in claimed:
            assert event.status == OutboxStatus.CLAIMED
            assert event.worker_id == "worker-1"

    @pytest.mark.asyncio
    async def test_update_status(self):
        """Test updating event status."""
        storage = InMemoryOutboxStorage()

        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={},
        )
        await storage.insert(event)

        updated = await storage.update_status(event.event_id, OutboxStatus.SENT)

        assert updated.status == OutboxStatus.SENT
        assert updated.sent_at is not None

    @pytest.mark.asyncio
    async def test_get_events_by_saga(self):
        """Test getting events by saga ID."""
        storage = InMemoryOutboxStorage()

        for i in range(3):
            await storage.insert(
                OutboxEvent(
                    saga_id="saga-123",
                    event_type=f"Event{i}",
                    payload={},
                )
            )

        await storage.insert(
            OutboxEvent(
                saga_id="saga-456",
                event_type="Other",
                payload={},
            )
        )

        events = await storage.get_events_by_saga("saga-123")
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_get_pending_count(self):
        """Test getting pending event count."""
        storage = InMemoryOutboxStorage()

        for i in range(5):
            await storage.insert(
                OutboxEvent(
                    saga_id=f"saga-{i}",
                    event_type="Test",
                    payload={},
                )
            )

        # Claim some
        await storage.claim_batch("worker-1", batch_size=2)

        count = await storage.get_pending_count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_stuck_events(self):
        """Test stuck event detection and recovery."""
        storage = InMemoryOutboxStorage()

        event = OutboxEvent(
            saga_id="saga-123",
            event_type="Test",
            payload={},
        )
        await storage.insert(event)

        # Claim the event
        await storage.claim_batch("worker-1", batch_size=1)

        # Modify claimed_at to simulate stuck event
        event = await storage.get_by_id(event.event_id)
        event.claimed_at = datetime.now(UTC) - timedelta(minutes=10)

        # Get stuck events
        stuck = await storage.get_stuck_events(claimed_older_than_seconds=300)
        assert len(stuck) == 1

        # Release stuck events
        released = await storage.release_stuck_events(claimed_older_than_seconds=300)
        assert released == 1

        # Verify released
        event = await storage.get_by_id(event.event_id)
        assert event.status == OutboxStatus.PENDING


class TestOutboxWorker:
    """Tests for OutboxWorker."""

    @pytest.mark.asyncio
    async def test_process_batch_success(self):
        """Test processing a batch successfully."""
        storage = InMemoryOutboxStorage()
        broker = InMemoryBroker()
        await broker.connect()

        # Insert events
        for i in range(3):
            await storage.insert(
                OutboxEvent(
                    saga_id=f"saga-{i}",
                    event_type="TestEvent",
                    payload={"index": i},
                )
            )

        worker = OutboxWorker(storage, broker)
        processed = await worker.process_batch()

        assert processed == 3
        assert worker._events_processed == 3

        # Verify events are marked as sent
        for i in range(3):
            events = await storage.get_events_by_saga(f"saga-{i}")
            assert events[0].status == OutboxStatus.SENT

        # Verify messages published to broker
        messages = broker.get_messages("TestEvent")
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_process_batch_with_failure(self):
        """Test processing with broker failure."""
        storage = InMemoryOutboxStorage()
        broker = InMemoryBroker()
        await broker.connect()

        # Make publish fail
        async def failing_publish(*args, **kwargs):
            msg = "Connection refused"
            raise BrokerError(msg)

        broker.publish = failing_publish

        # Insert event
        await storage.insert(
            OutboxEvent(
                saga_id="saga-123",
                event_type="TestEvent",
                payload={},
            )
        )

        worker = OutboxWorker(storage, broker, OutboxConfig(max_retries=3))
        await worker.process_batch()

        # Event should be back to pending for retry
        event = (await storage.get_events_by_saga("saga-123"))[0]
        assert event.status == OutboxStatus.PENDING
        assert event.retry_count == 1

    @pytest.mark.asyncio
    async def test_dead_letter_on_max_retries(self):
        """Test moving to dead letter after max retries."""
        storage = InMemoryOutboxStorage()
        broker = InMemoryBroker()
        await broker.connect()

        # Make publish fail
        async def failing_publish(*args, **kwargs):
            msg = "Connection refused"
            raise BrokerError(msg)

        broker.publish = failing_publish

        # Insert event with retries already at max
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="TestEvent",
            payload={},
        )
        event.retry_count = 9  # Will be 10 after failure
        await storage.insert(event)

        worker = OutboxWorker(storage, broker, OutboxConfig(max_retries=10))
        await worker.process_batch()

        # Event should be in dead letter
        event = (await storage.get_events_by_saga("saga-123"))[0]
        assert event.status == OutboxStatus.DEAD_LETTER
        assert worker._events_dead_lettered == 1

    @pytest.mark.asyncio
    async def test_callbacks(self):
        """Test event callbacks."""
        storage = InMemoryOutboxStorage()
        broker = InMemoryBroker()
        await broker.connect()

        published_events = []

        async def on_published(event):
            published_events.append(event)

        await storage.insert(
            OutboxEvent(
                saga_id="saga-123",
                event_type="TestEvent",
                payload={},
            )
        )

        worker = OutboxWorker(
            storage,
            broker,
            on_event_published=on_published,
        )
        await worker.process_batch()

        assert len(published_events) == 1

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting worker stats."""
        storage = InMemoryOutboxStorage()
        broker = InMemoryBroker()
        await broker.connect()

        await storage.insert(
            OutboxEvent(
                saga_id="saga-123",
                event_type="TestEvent",
                payload={},
            )
        )

        worker = OutboxWorker(storage, broker)
        await worker.process_batch()

        stats = worker.get_stats()

        assert stats["events_processed"] == 1
        assert stats["running"] is False
        assert "worker_id" in stats

    @pytest.mark.asyncio
    async def test_recover_stuck_events(self):
        """Test recovering stuck events."""
        storage = InMemoryOutboxStorage()
        broker = InMemoryBroker()
        await broker.connect()

        # Insert and claim an event
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="TestEvent",
            payload={},
        )
        await storage.insert(event)
        await storage.claim_batch("worker-old", batch_size=1)

        # Simulate stuck by setting old claimed_at
        event = await storage.get_by_id(event.event_id)
        event.claimed_at = datetime.now(UTC) - timedelta(minutes=10)

        worker = OutboxWorker(storage, broker, OutboxConfig(claim_timeout_seconds=300))
        recovered = await worker.recover_stuck_events()

        assert recovered == 1

        # Verify event is pending again
        event = await storage.get_by_id(event.event_id)
        assert event.status == OutboxStatus.PENDING


class TestOutboxConfig:
    """Tests for OutboxConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = OutboxConfig()

        assert config.batch_size == 100
        assert config.poll_interval_seconds == 1.0
        assert config.max_retries == 10
        assert config.optimistic_publish is True

    def test_from_env(self):
        """Test loading config from environment."""
        with patch.dict(
            "os.environ",
            {
                "OUTBOX_BATCH_SIZE": "50",
                "OUTBOX_MAX_RETRIES": "5",
                "OUTBOX_OPTIMISTIC": "false",
            },
        ):
            config = OutboxConfig.from_env()

            assert config.batch_size == 50
            assert config.max_retries == 5
            assert config.optimistic_publish is False
