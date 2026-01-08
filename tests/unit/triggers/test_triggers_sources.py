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
from sagaz.config import configure, get_config
from sagaz.triggers import fire_event, trigger
from sagaz.triggers.registry import TriggerRegistry

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
    from sagaz.storage import InMemorySagaStorage
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
        from sagaz.triggers.sources.cron import CronScheduler

        scheduler = CronScheduler()
        assert not scheduler.is_running

        await scheduler.start()
        assert scheduler.is_running

        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_cron_scheduler_fires_events(self, memory_storage):
        """Cron scheduler fires events on schedule."""
        from sagaz.triggers.sources.cron import CronScheduler

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
        from sagaz.triggers.sources.cron import CronScheduler

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
        from sagaz.triggers.sources.broker import BrokerTriggerConsumer

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
        from sagaz.triggers.sources.broker import BrokerTriggerConsumer

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
        from sagaz.outbox.brokers.memory import InMemoryBroker
        from sagaz.triggers.sources.broker import BrokerTriggerConsumer

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
