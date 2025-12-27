"""
TDD Tests for SagaListener Pattern.

Tests the observer pattern for saga lifecycle events, enabling
automatic metrics, tracing, and outbox publishing.
"""

from typing import Any

import pytest


class TestSagaListenerBasic:
    """Test basic listener functionality."""

    @pytest.mark.asyncio
    async def test_listener_receives_saga_start_event(self):
        """Listener should receive event when saga starts."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import SagaListener

        received_events = []

        class TestListener(SagaListener):
            async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict):
                received_events.append(
                    {"event": "saga_start", "saga_name": saga_name, "saga_id": saga_id}
                )

        class TestSaga(Saga):
            saga_name = "test-saga"
            listeners = [TestListener()]

            @step("my_step")
            async def my_step(self, ctx):
                return {}

        saga = TestSaga()
        await saga.run({"saga_id": "saga-001"})

        assert len(received_events) == 1
        assert received_events[0]["event"] == "saga_start"
        assert received_events[0]["saga_name"] == "test-saga"
        assert received_events[0]["saga_id"] == "saga-001"

    @pytest.mark.asyncio
    async def test_listener_receives_step_enter_event(self):
        """Listener should receive event when step starts."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import SagaListener

        received_events = []

        class TestListener(SagaListener):
            async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict):
                received_events.append({"event": "step_enter", "step_name": step_name})

        class TestSaga(Saga):
            saga_name = "test-saga"
            listeners = [TestListener()]

            @step("step1")
            async def step1(self, ctx):
                return {}

            @step("step2", depends_on=["step1"])
            async def step2(self, ctx):
                return {}

        saga = TestSaga()
        await saga.run({})

        assert len(received_events) == 2
        assert received_events[0]["step_name"] == "step1"
        assert received_events[1]["step_name"] == "step2"

    @pytest.mark.asyncio
    async def test_listener_receives_step_success_event(self):
        """Listener should receive event when step succeeds."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import SagaListener

        received_events = []

        class TestListener(SagaListener):
            async def on_step_success(self, saga_name: str, step_name: str, ctx: dict, result: Any):
                received_events.append(
                    {"event": "step_success", "step_name": step_name, "result": result}
                )

        class TestSaga(Saga):
            saga_name = "test-saga"
            listeners = [TestListener()]

            @step("my_step")
            async def my_step(self, ctx):
                return {"order_id": "ORD-123"}

        saga = TestSaga()
        await saga.run({})

        assert len(received_events) == 1
        assert received_events[0]["step_name"] == "my_step"
        assert received_events[0]["result"]["order_id"] == "ORD-123"

    @pytest.mark.asyncio
    async def test_listener_receives_step_failure_event(self):
        """Listener should receive event when step fails."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import SagaListener

        received_events = []

        class TestListener(SagaListener):
            async def on_step_failure(
                self, saga_name: str, step_name: str, ctx: dict, error: Exception
            ):
                received_events.append(
                    {"event": "step_failure", "step_name": step_name, "error": str(error)}
                )

        class TestSaga(Saga):
            saga_name = "test-saga"
            listeners = [TestListener()]

            @step("failing_step")
            async def failing_step(self, ctx):
                msg = "Something broke"
                raise ValueError(msg)

        saga = TestSaga()

        with pytest.raises(ValueError):
            await saga.run({})

        assert len(received_events) == 1
        assert received_events[0]["step_name"] == "failing_step"
        assert "Something broke" in received_events[0]["error"]

    @pytest.mark.asyncio
    async def test_listener_receives_saga_complete_event(self):
        """Listener should receive event when saga completes."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import SagaListener

        received_events = []

        class TestListener(SagaListener):
            async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict):
                received_events.append(
                    {
                        "event": "saga_complete",
                        "saga_name": saga_name,
                        "order_id": ctx.get("order_id"),
                    }
                )

        class TestSaga(Saga):
            saga_name = "order-saga"
            listeners = [TestListener()]

            @step("create_order")
            async def create_order(self, ctx):
                return {"order_id": "ORD-456"}

        saga = TestSaga()
        await saga.run({"saga_id": "saga-002"})

        assert len(received_events) == 1
        assert received_events[0]["saga_name"] == "order-saga"
        assert received_events[0]["order_id"] == "ORD-456"

    @pytest.mark.asyncio
    async def test_listener_receives_saga_failed_event(self):
        """Listener should receive event when saga fails."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import SagaListener

        received_events = []

        class TestListener(SagaListener):
            async def on_saga_failed(
                self, saga_name: str, saga_id: str, ctx: dict, error: Exception
            ):
                received_events.append({"event": "saga_failed", "error": str(error)})

        class TestSaga(Saga):
            saga_name = "failing-saga"
            listeners = [TestListener()]

            @step("failing_step")
            async def failing_step(self, ctx):
                msg = "Saga failed!"
                raise RuntimeError(msg)

        saga = TestSaga()

        with pytest.raises(RuntimeError):
            await saga.run({"saga_id": "saga-003"})

        assert len(received_events) == 1
        assert "Saga failed!" in received_events[0]["error"]


class TestSagaListenerCompensation:
    """Test listener events during compensation."""

    @pytest.mark.asyncio
    async def test_listener_receives_compensation_events(self):
        """Listener should receive events during compensation."""
        from sagaz.decorators import Saga, compensate, step
        from sagaz.listeners import SagaListener

        received_events = []

        class TestListener(SagaListener):
            async def on_compensation_start(self, saga_name: str, step_name: str, ctx: dict):
                received_events.append({"event": "compensation_start", "step_name": step_name})

            async def on_compensation_complete(self, saga_name: str, step_name: str, ctx: dict):
                received_events.append({"event": "compensation_complete", "step_name": step_name})

        class TestSaga(Saga):
            saga_name = "compensating-saga"
            listeners = [TestListener()]

            @step("create_order")
            async def create_order(self, ctx):
                return {"order_id": "ORD-789"}

            @compensate("create_order")
            async def cancel_order(self, ctx):
                pass

            @step("charge_payment", depends_on=["create_order"])
            async def charge_payment(self, ctx):
                msg = "Payment failed"
                raise ValueError(msg)

        saga = TestSaga()

        with pytest.raises(ValueError):
            await saga.run({})

        # Should have compensation events for create_order
        comp_start = [e for e in received_events if e["event"] == "compensation_start"]
        comp_complete = [e for e in received_events if e["event"] == "compensation_complete"]

        assert len(comp_start) == 1
        assert comp_start[0]["step_name"] == "create_order"
        assert len(comp_complete) == 1


class TestMultipleListeners:
    """Test multiple listeners on the same saga."""

    @pytest.mark.asyncio
    async def test_multiple_listeners_all_receive_events(self):
        """All listeners should receive events."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import SagaListener

        listener1_events = []
        listener2_events = []

        class Listener1(SagaListener):
            async def on_step_success(self, saga_name, step_name, ctx, result):
                listener1_events.append(step_name)

        class Listener2(SagaListener):
            async def on_step_success(self, saga_name, step_name, ctx, result):
                listener2_events.append(step_name)

        class TestSaga(Saga):
            saga_name = "multi-listener-saga"
            listeners = [Listener1(), Listener2()]

            @step("my_step")
            async def my_step(self, ctx):
                return {}

        saga = TestSaga()
        await saga.run({})

        assert "my_step" in listener1_events
        assert "my_step" in listener2_events


class TestBuiltInListeners:
    """Test built-in listener implementations."""

    @pytest.mark.asyncio
    async def test_metrics_listener_records_execution(self):
        """MetricsSagaListener should record saga metrics."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import MetricsSagaListener
        from sagaz.monitoring.metrics import SagaMetrics

        metrics = SagaMetrics()
        listener = MetricsSagaListener(metrics=metrics)

        class TestSaga(Saga):
            saga_name = "metrics-test-saga"
            listeners = [listener]

            @step("my_step")
            async def my_step(self, ctx):
                return {}

        saga = TestSaga()
        await saga.run({})

        result = metrics.get_metrics()
        assert result["total_executed"] >= 1
        assert result["total_successful"] >= 1

    @pytest.mark.asyncio
    async def test_outbox_listener_publishes_events(self):
        """OutboxSagaListener should publish events to storage."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import OutboxSagaListener
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage

        storage = InMemoryOutboxStorage()
        listener = OutboxSagaListener(storage=storage)

        class TestSaga(Saga):
            saga_name = "outbox-test-saga"
            listeners = [listener]

            @step("create_order")
            async def create_order(self, ctx):
                return {"order_id": "ORD-999"}

        saga = TestSaga()
        await saga.run({"saga_id": "saga-outbox-001"})

        # Check events were published
        events = await storage.get_events_by_saga("saga-outbox-001")
        assert len(events) >= 1

        # Should have saga complete event
        event_types = [e.event_type for e in events]
        assert any("complete" in et or "success" in et for et in event_types)


class TestListenerErrorHandling:
    """Test that listener errors don't break saga execution."""

    @pytest.mark.asyncio
    async def test_listener_error_does_not_break_saga(self):
        """Errors in listeners should be logged but not break execution."""
        from sagaz.decorators import Saga, step
        from sagaz.listeners import SagaListener

        step_executed = False

        class FailingListener(SagaListener):
            async def on_step_enter(self, saga_name, step_name, ctx):
                msg = "Listener exploded!"
                raise RuntimeError(msg)

        class TestSaga(Saga):
            saga_name = "error-handling-saga"
            listeners = [FailingListener()]

            @step("my_step")
            async def my_step(self, ctx):
                nonlocal step_executed
                step_executed = True
                return {}

        saga = TestSaga()
        await saga.run({})  # Should not raise

        assert step_executed is True
