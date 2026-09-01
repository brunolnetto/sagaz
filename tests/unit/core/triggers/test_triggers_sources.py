"""
Tests for Phase 3: Event Sources & Integrations

Covers:
- Cron scheduler for periodic saga triggering
- Broker integration for message-driven triggers
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz import Saga, SagaConfig, action
from sagaz.core.config import configure, get_config
from sagaz.core.triggers import fire_event, trigger
from sagaz.core.triggers.registry import TriggerRegistry

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def reset_registry():
    """Clear the trigger registry before each test."""
    TriggerRegistry.clear()
    yield
    TriggerRegistry.clear()


@pytest.fixture
def memory_storage():
    """Provide fresh memory storage for each test."""
    from sagaz.core.storage import InMemorySagaStorage

    storage = InMemorySagaStorage()
    config = SagaConfig(storage=storage)
    configure(config)
    return storage


# =============================================================================
# Cron Scheduler Tests
# =============================================================================


class TestCronScheduler:
    """Tests for the cron scheduler."""

    def test_cron_trigger_decorator(self):
        """@trigger with cron source stores schedule config."""

        class CronSaga(Saga):
            @trigger(source="cron", schedule="*/5 * * * *")  # Every 5 minutes
            def on_schedule(self, event):
                return {"triggered_at": event.get("timestamp")}

            @action("process")
            async def process(self, ctx):
                return {}

        triggers = TriggerRegistry.get_triggers("cron")
        assert len(triggers) == 1
        assert triggers[0].metadata.config["schedule"] == "*/5 * * * *"

    def test_cron_trigger_with_timezone(self):
        """Cron trigger can specify timezone."""

        class TzCronSaga(Saga):
            @trigger(source="cron", schedule="0 9 * * *", timezone="America/New_York")
            def on_daily(self, event):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        triggers = TriggerRegistry.get_triggers("cron")
        assert triggers[0].metadata.config["timezone"] == "America/New_York"

    @pytest.mark.asyncio
    async def test_cron_scheduler_start_stop(self, memory_storage):
        """Cron scheduler can be started and stopped."""
        from sagaz.core.triggers.sources.cron import CronScheduler

        scheduler = CronScheduler()
        assert not scheduler.is_running

        await scheduler.start()
        assert scheduler.is_running

        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_cron_scheduler_fires_events(self, memory_storage):
        """Cron scheduler fires events on schedule."""
        from sagaz.core.triggers.sources.cron import CronScheduler

        fired_events = []

        class ScheduledSaga(Saga):
            saga_name = "scheduled"

            @trigger(source="cron", schedule="* * * * *")  # Every minute
            def on_tick(self, event):
                fired_events.append(event)
                return {"tick": True}

            @action("step")
            async def step(self, ctx):
                return {}

        scheduler = CronScheduler()

        # Manually trigger a tick (instead of waiting for real time)
        await scheduler._tick()

        # Check that event was processed
        assert len(fired_events) >= 1

    @pytest.mark.asyncio
    async def test_cron_scheduler_respects_schedule(self, memory_storage):
        """Cron scheduler only fires when schedule matches."""
        from sagaz.core.triggers.sources.cron import CronScheduler

        class FutureSaga(Saga):
            saga_name = "future"

            # Schedule that won't match current time (Feb 30th doesn't exist)
            @trigger(source="cron", schedule="0 0 30 2 *")
            def on_never(self, event):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        scheduler = CronScheduler()

        # This should not fire any events
        result = await scheduler._tick()

        # No sagas should have been triggered for this impossible schedule
        assert result == []


# =============================================================================
# Broker Integration Tests
# =============================================================================


class TestBrokerIntegration:
    """Tests for message broker integration."""

    def test_broker_trigger_decorator(self):
        """@trigger with broker source stores topic config."""

        class BrokerSaga(Saga):
            @trigger(source="broker", topic="orders.created")
            def on_order(self, event):
                return {"order_id": event["id"]}

            @action("process")
            async def process(self, ctx):
                return {}

        triggers = TriggerRegistry.get_triggers("broker")
        assert len(triggers) == 1
        assert triggers[0].metadata.config["topic"] == "orders.created"

    @pytest.mark.asyncio
    async def test_broker_consumer_processes_messages(self, memory_storage):
        """Broker consumer processes messages and triggers sagas."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        processed = []

        class OrderSaga(Saga):
            saga_name = "order_processor"

            @trigger(source="broker", topic="orders")
            def on_order(self, event):
                processed.append(event)
                return {"order_id": event["id"]}

            @action("process")
            async def step(self, ctx):
                return {}

        # Create consumer with mock broker
        mock_broker = MagicMock()
        consumer = BrokerTriggerConsumer(broker=mock_broker)

        # Simulate receiving a message
        message = {"id": "order-123", "amount": 99.99}
        await consumer.handle_message("orders", message)

        # Saga should have been triggered
        assert len(processed) == 1
        assert processed[0]["id"] == "order-123"

    @pytest.mark.asyncio
    async def test_broker_consumer_filters_by_topic(self, memory_storage):
        """Broker consumer only triggers sagas for matching topics."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        orders_processed = []
        payments_processed = []

        class OrderSaga(Saga):
            saga_name = "orders"

            @trigger(source="broker", topic="orders")
            def on_order(self, event):
                orders_processed.append(event)
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        class PaymentSaga(Saga):
            saga_name = "payments"

            @trigger(source="broker", topic="payments")
            def on_payment(self, event):
                payments_processed.append(event)
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        consumer = BrokerTriggerConsumer(broker=MagicMock())

        # Send order message
        await consumer.handle_message("orders", {"id": "1"})

        # Only orders saga should process
        assert len(orders_processed) == 1
        assert len(payments_processed) == 0

    @pytest.mark.asyncio
    async def test_broker_consumer_with_existing_outbox_broker(self, memory_storage):
        """Broker consumer integrates with existing outbox brokers."""
        from sagaz.core.outbox.brokers.memory import InMemoryBroker
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        # Use actual in-memory broker
        broker = InMemoryBroker()
        consumer = BrokerTriggerConsumer(broker=broker)

        processed = []

        class TestSaga(Saga):
            saga_name = "test"

            @trigger(source="broker", topic="test-topic")
            def on_test(self, event):
                processed.append(event)
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        # Publish and consume
        await broker.connect()
        await broker.publish("test-topic", {"data": "hello"})

        # Manually trigger consumption (real consumer would loop)
        # For testing, we call handle_message directly
        await consumer.handle_message("test-topic", {"data": "hello"})

        assert len(processed) == 1


# =============================================================================
# Combined Source Tests
# =============================================================================


class TestMultipleSources:
    """Tests for sagas that respond to multiple event sources."""

    def test_saga_with_multiple_sources(self):
        """Single saga can listen to multiple sources."""

        class MultiSourceSaga(Saga):
            saga_name = "multi"

            @trigger(source="webhook")
            def on_webhook(self, event):
                return {"source": "webhook", **event}

            @trigger(source="cron", schedule="0 * * * *")
            def on_hourly(self, event):
                return {"source": "cron"}

            @trigger(source="broker", topic="events")
            def on_message(self, event):
                return {"source": "broker", **event}

            @action("process")
            async def process(self, ctx):
                return {"processed_source": ctx.get("source")}

        assert len(TriggerRegistry.get_triggers("webhook")) == 1
        assert len(TriggerRegistry.get_triggers("cron")) == 1
        assert len(TriggerRegistry.get_triggers("broker")) == 1

    @pytest.mark.asyncio
    async def test_same_saga_triggered_from_different_sources(self, memory_storage):
        """Same saga logic runs regardless of trigger source."""
        results = []

        class UnifiedSaga(Saga):
            saga_name = "unified"

            @trigger(source="source_a")
            def on_a(self, event):
                return {"from": "a", **event}

            @trigger(source="source_b")
            def on_b(self, event):
                return {"from": "b", **event}

            @action("process")
            async def process(self, ctx):
                results.append(ctx.get("from"))
                return {}

        # Trigger from source A
        await fire_event("source_a", {"data": 1})
        await asyncio.sleep(0.1)

        # Trigger from source B
        await fire_event("source_b", {"data": 2})
        await asyncio.sleep(0.1)

        assert "a" in results
        assert "b" in results


# =============================================================================
# Cron Scheduler – Additional Coverage Tests
# =============================================================================


class TestCronSchedulerCoverage:
    """Targeted tests to cover remaining branches in cron.py."""

    def test_parse_cron_invalid_expression_raises(self):
        """Lines 42-43: _parse_cron raises ValueError for wrong number of fields."""
        from sagaz.core.triggers.sources.cron import _parse_cron

        with pytest.raises(ValueError, match="Invalid cron expression"):
            _parse_cron("* * * *")  # only 4 fields

    def test_matches_field_step(self):
        """Lines 60-61: */n step syntax matches when value is divisible."""
        from sagaz.core.triggers.sources.cron import _matches_field

        assert _matches_field("*/5", 0) is True
        assert _matches_field("*/5", 5) is True
        assert _matches_field("*/5", 3) is False

    def test_matches_field_comma_list(self):
        """Line 64: comma-separated values."""
        from sagaz.core.triggers.sources.cron import _matches_field

        assert _matches_field("1,2,3", 2) is True
        assert _matches_field("1,2,3", 4) is False

    def test_matches_field_range(self):
        """Lines 67-68: range syntax (start-end)."""
        from sagaz.core.triggers.sources.cron import _matches_field

        assert _matches_field("1-5", 3) is True
        assert _matches_field("1-5", 6) is False

    def test_matches_cron_exception_returns_false(self):
        """Lines 84-86: _matches_cron returns False when parsing fails."""
        from sagaz.core.triggers.sources.cron import _matches_cron

        # Expression that passes split but causes downstream error
        result = _matches_cron("abc def ghi jkl mno", datetime.now())
        assert result is False

    @pytest.mark.asyncio
    async def test_cron_scheduler_start_when_already_running(self, memory_storage):
        """Line 124: start() returns early when already running."""
        from sagaz.core.triggers.sources.cron import CronScheduler

        scheduler = CronScheduler()
        await scheduler.start()
        assert scheduler.is_running

        # Starting again should be a no-op
        await scheduler.start()
        assert scheduler.is_running

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_cron_scheduler_stop_cancels_task(self, memory_storage):
        """Lines 133-140: stop() cancels the running task when _task is not None."""
        from sagaz.core.triggers.sources.cron import CronScheduler

        scheduler = CronScheduler(tick_interval=60)
        await scheduler.start()

        assert scheduler._task is not None
        assert scheduler.is_running

        await scheduler.stop()

        assert scheduler._task is None
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_run_loop_executes_tick(self, memory_storage):
        """Lines 144-150: _run_loop executes _tick and then sleeps."""
        from sagaz.core.triggers.sources.cron import CronScheduler

        scheduler = CronScheduler(tick_interval=0)
        tick_count = 0

        async def mock_tick():
            nonlocal tick_count
            tick_count += 1
            scheduler._running = False  # stop after first tick
            return []

        scheduler._running = True
        with patch.object(scheduler, "_tick", mock_tick):
            await scheduler._run_loop()

        assert tick_count == 1

    @pytest.mark.asyncio
    async def test_run_loop_exception_in_tick_logged(self, memory_storage):
        """Lines 147-148: _run_loop catches and logs exceptions from _tick."""
        from sagaz.core.triggers.sources.cron import CronScheduler

        scheduler = CronScheduler(tick_interval=0)
        call_count = 0

        async def failing_tick():
            nonlocal call_count
            call_count += 1
            scheduler._running = False  # stop after this tick
            msg = "tick error"
            raise RuntimeError(msg)

        scheduler._running = True
        with patch.object(scheduler, "_tick", failing_tick):
            await scheduler._run_loop()  # should not raise

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_cron_scheduler_stop_no_task(self, memory_storage):
        """133→140: stop() skips cancel block when _task is None."""
        from sagaz.core.triggers.sources.cron import CronScheduler

        scheduler = CronScheduler()
        scheduler._running = True
        scheduler._task = None

        await scheduler.stop()

        assert not scheduler.is_running
        assert scheduler._task is None

    @pytest.mark.asyncio
    async def test_tick_skips_trigger_without_schedule(self, memory_storage):
        """Line 168: _tick skips triggers that have no schedule config."""
        from sagaz.core.triggers.sources.cron import CronScheduler

        class NoScheduleSaga(Saga):
            saga_name = "no_schedule"

            @trigger(source="cron")  # no schedule kwarg
            def on_tick(self, event):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        scheduler = CronScheduler()
        result = await scheduler._tick()
        # No schedule → skipped, nothing triggered
        assert result == []


# =============================================================================
# Broker Consumer – Additional Coverage Tests
# =============================================================================


class TestBrokerConsumerCoverage:
    """Targeted tests to cover remaining branches in broker.py."""

    @pytest.mark.asyncio
    async def test_is_running_property(self, memory_storage):
        """Line 65: is_running property reflects internal state."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        consumer = BrokerTriggerConsumer(broker=MagicMock())
        assert consumer.is_running is False

    @pytest.mark.asyncio
    async def test_start_when_already_running(self, memory_storage):
        """Lines 74-75: start() returns immediately if already running."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        consumer = BrokerTriggerConsumer(broker=MagicMock())
        consumer._running = True

        # Should return without side-effects
        await consumer.start()
        assert consumer.is_running

    @pytest.mark.asyncio
    async def test_start_with_no_registered_topics(self, memory_storage):
        """Lines 81-83: start() logs warning and returns when no topics discovered."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        # No triggers registered → no topics
        consumer = BrokerTriggerConsumer(broker=MagicMock())
        await consumer.start()
        # Still not running because no topics
        assert not consumer.is_running

    @pytest.mark.asyncio
    async def test_start_with_explicit_topics(self, memory_storage):
        """Lines 85-86: start() sets _running when topics are provided."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        consumer = BrokerTriggerConsumer(broker=MagicMock())
        await consumer.start(topics=["orders"])
        assert consumer.is_running

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, memory_storage):
        """Lines 93-101: stop() cancels and clears a running task."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        consumer = BrokerTriggerConsumer(broker=MagicMock())
        consumer._running = True

        # Plant a real task that blocks until cancelled
        async def _blocking():
            await asyncio.sleep(10)  # Long enough to not complete; will be cancelled

        consumer._task = asyncio.create_task(_blocking())

        await consumer.stop()

        assert not consumer.is_running
        assert consumer._task is None

    @pytest.mark.asyncio
    async def test_stop_no_task(self, memory_storage):
        """94→101: stop() skips cancel block when _task is None."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        consumer = BrokerTriggerConsumer(broker=MagicMock())
        consumer._running = True
        consumer._task = None

        await consumer.stop()

        assert not consumer.is_running

    def test_discover_topics_skips_trigger_without_topic(self, memory_storage):
        """109→107: _discover_topics skips broker triggers with no topic metadata."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        class NoTopicSaga(Saga):
            @trigger(source="broker")  # no topic kwarg
            def on_event(self, event):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        consumer = BrokerTriggerConsumer(broker=MagicMock())
        topics = consumer._discover_topics()
        assert topics == []

    def test_discover_topics_returns_registered_topics(self, memory_storage):
        """Lines 105-112: _discover_topics returns topics from registered broker triggers."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        class OrderSaga(Saga):
            @trigger(source="broker", topic="orders")
            def on_order(self, event):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        consumer = BrokerTriggerConsumer(broker=MagicMock())
        topics = consumer._discover_topics()
        assert "orders" in topics

    @pytest.mark.asyncio
    async def test_handle_message_async_transformer(self, memory_storage):
        """Line 150: handle_message awaits async transformer methods."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        results = []

        class AsyncSaga(Saga):
            saga_name = "async_saga"

            @trigger(source="broker", topic="async-topic")
            async def on_event(self, event):
                results.append(event)
                return {"processed": True}

            @action("step")
            async def step(self, ctx):
                return {}

        consumer = BrokerTriggerConsumer(broker=MagicMock())
        await consumer.handle_message("async-topic", {"id": "1"})

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_handle_message_transformer_returns_none(self, memory_storage):
        """Line 154-155: handle_message skips saga creation when transformer returns None."""
        from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

        class NoneTransformerSaga(Saga):
            saga_name = "none_transformer"

            @trigger(source="broker", topic="null-topic")
            def on_event(self, event):
                return None  # returning None should skip saga creation

            @action("step")
            async def step(self, ctx):
                return {}

        consumer = BrokerTriggerConsumer(broker=MagicMock())
        ids = await consumer.handle_message("null-topic", {"id": "1"})

        assert ids == []

    @pytest.mark.asyncio
    async def test_create_broker_consumer_factory(self, memory_storage):
        """Lines 189-194: create_broker_consumer factory creates and connects a consumer."""
        from sagaz.core.triggers.sources.broker import create_broker_consumer

        consumer = await create_broker_consumer("memory")
        assert consumer is not None
