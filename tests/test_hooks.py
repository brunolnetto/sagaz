"""
TDD Tests for Step Lifecycle Hooks.

Tests the on_enter, on_success, on_failure, and on_compensate hooks
for saga steps.
"""

from typing import Any

import pytest

# We'll import from sagaz.decorators once implemented
# from sagaz.decorators import Saga, step, compensate, StepHook


class TestStepHooksBasic:
    """Test basic hook functionality."""

    @pytest.mark.asyncio
    async def test_on_enter_called_before_step_execution(self):
        """Hook on_enter should be called before the step executes."""
        from sagaz.decorators import Saga, step

        execution_order = []

        async def track_enter(ctx: dict[str, Any], step_name: str):
            execution_order.append(f"enter:{step_name}")

        class TestSaga(Saga):
            @step("test_step", on_enter=track_enter)
            async def test_step(self, ctx):
                execution_order.append("step:test_step")
                return {"result": "ok"}

        saga = TestSaga()
        await saga.run({"initial": "data"})

        assert execution_order == ["enter:test_step", "step:test_step"]

    @pytest.mark.asyncio
    async def test_on_success_called_after_successful_step(self):
        """Hook on_success should be called after step completes successfully."""
        from sagaz.decorators import Saga, step

        success_events = []

        async def track_success(ctx: dict[str, Any], step_name: str, result: Any):
            success_events.append(
                {"step": step_name, "result": result, "order_id": ctx.get("order_id")}
            )

        class TestSaga(Saga):
            @step("create_order", on_success=track_success)
            async def create_order(self, ctx):
                return {"order_id": "ORD-123"}

        saga = TestSaga()
        await saga.run({})

        assert len(success_events) == 1
        assert success_events[0]["step"] == "create_order"
        assert success_events[0]["order_id"] == "ORD-123"

    @pytest.mark.asyncio
    async def test_on_failure_called_when_step_fails(self):
        """Hook on_failure should be called when step raises an exception."""
        from sagaz.decorators import Saga, step

        failure_events = []

        async def track_failure(ctx: dict[str, Any], step_name: str, error: Exception):
            failure_events.append({"step": step_name, "error": str(error)})

        class TestSaga(Saga):
            @step("failing_step", on_failure=track_failure)
            async def failing_step(self, ctx):
                msg = "Something went wrong"
                raise ValueError(msg)

        saga = TestSaga()

        with pytest.raises(ValueError):
            await saga.run({})

        assert len(failure_events) == 1
        assert failure_events[0]["step"] == "failing_step"
        assert "Something went wrong" in failure_events[0]["error"]

    @pytest.mark.asyncio
    async def test_on_compensate_called_during_compensation(self):
        """Hook on_compensate should be called when compensation runs."""
        from sagaz.decorators import Saga, compensate, step

        compensate_events = []

        async def track_compensate(ctx: dict[str, Any], step_name: str):
            compensate_events.append({"step": step_name, "order_id": ctx.get("order_id")})

        class TestSaga(Saga):
            @step("create_order")
            async def create_order(self, ctx):
                return {"order_id": "ORD-123"}

            @compensate("create_order", on_compensate=track_compensate)
            async def cancel_order(self, ctx):
                pass  # Cancel logic

            @step("charge_payment", depends_on=["create_order"])
            async def charge_payment(self, ctx):
                msg = "Payment failed"
                raise ValueError(msg)  # Triggers compensation

        saga = TestSaga()

        with pytest.raises(ValueError):
            await saga.run({})

        assert len(compensate_events) == 1
        assert compensate_events[0]["step"] == "create_order"
        assert compensate_events[0]["order_id"] == "ORD-123"


class TestStepHooksWithOutbox:
    """Test hooks integrated with outbox for event publishing."""

    @pytest.mark.asyncio
    async def test_publish_event_on_success(self):
        """on_success hook can publish events to outbox."""
        from sagaz.decorators import Saga, step
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage
        from sagaz.outbox.types import OutboxEvent

        storage = InMemoryOutboxStorage()

        async def publish_order_created(ctx: dict[str, Any], step_name: str, result: Any):
            event = OutboxEvent(
                saga_id=ctx.get("saga_id", "test-saga"),
                event_type="order.created",
                payload={"order_id": result.get("order_id"), "amount": ctx.get("amount")},
            )
            await storage.insert(event)

        class OrderSaga(Saga):
            @step("create_order", on_success=publish_order_created)
            async def create_order(self, ctx):
                return {"order_id": "ORD-456"}

        saga = OrderSaga()
        await saga.run({"amount": 99.99, "saga_id": "saga-001"})

        # Verify event was published
        events = await storage.get_events_by_saga("saga-001")
        assert len(events) == 1
        assert events[0].event_type == "order.created"
        assert events[0].payload["order_id"] == "ORD-456"
        assert events[0].payload["amount"] == 99.99

    @pytest.mark.asyncio
    async def test_publish_event_on_failure(self):
        """on_failure hook can publish failure events."""
        from sagaz.decorators import Saga, step
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage
        from sagaz.outbox.types import OutboxEvent

        storage = InMemoryOutboxStorage()

        async def publish_order_failed(ctx: dict[str, Any], step_name: str, error: Exception):
            event = OutboxEvent(
                saga_id=ctx.get("saga_id", "test-saga"),
                event_type="order.failed",
                payload={"step": step_name, "error": str(error)},
            )
            await storage.insert(event)

        class OrderSaga(Saga):
            @step("create_order", on_failure=publish_order_failed)
            async def create_order(self, ctx):
                msg = "Validation failed"
                raise ValueError(msg)

        saga = OrderSaga()

        with pytest.raises(ValueError):
            await saga.run({"saga_id": "saga-002"})

        events = await storage.get_events_by_saga("saga-002")
        assert len(events) == 1
        assert events[0].event_type == "order.failed"
        assert events[0].payload["step"] == "create_order"


class TestStepHooksMultiple:
    """Test multiple hooks on the same step."""

    @pytest.mark.asyncio
    async def test_all_hooks_on_successful_step(self):
        """All applicable hooks should be called in order."""
        from sagaz.decorators import Saga, step

        events = []

        async def on_enter(ctx, step_name):
            events.append(f"enter:{step_name}")

        async def on_success(ctx, step_name, result):
            events.append(f"success:{step_name}")

        class TestSaga(Saga):
            @step("my_step", on_enter=on_enter, on_success=on_success)
            async def my_step(self, ctx):
                events.append("execute:my_step")
                return {}

        saga = TestSaga()
        await saga.run({})

        assert events == ["enter:my_step", "execute:my_step", "success:my_step"]

    @pytest.mark.asyncio
    async def test_all_hooks_on_failed_step(self):
        """on_enter and on_failure should be called for failed step."""
        from sagaz.decorators import Saga, step

        events = []

        async def on_enter(ctx, step_name):
            events.append(f"enter:{step_name}")

        async def on_success(ctx, step_name, result):
            events.append(f"success:{step_name}")  # Should NOT be called

        async def on_failure(ctx, step_name, error):
            events.append(f"failure:{step_name}")

        class TestSaga(Saga):
            @step("my_step", on_enter=on_enter, on_success=on_success, on_failure=on_failure)
            async def my_step(self, ctx):
                events.append("execute:my_step")
                msg = "Boom!"
                raise RuntimeError(msg)

        saga = TestSaga()

        with pytest.raises(RuntimeError):
            await saga.run({})

        assert events == [
            "enter:my_step",
            "execute:my_step",
            "failure:my_step",  # on_success NOT called
        ]


class TestStepHooksSyncSupport:
    """Test that sync hooks are also supported."""

    @pytest.mark.asyncio
    async def test_sync_hook_is_supported(self):
        """Sync functions should work as hooks."""
        from sagaz.decorators import Saga, step

        events = []

        def sync_on_enter(ctx, step_name):
            events.append(f"sync_enter:{step_name}")

        def sync_on_success(ctx, step_name, result):
            events.append(f"sync_success:{step_name}")

        class TestSaga(Saga):
            @step("my_step", on_enter=sync_on_enter, on_success=sync_on_success)
            async def my_step(self, ctx):
                return {"done": True}

        saga = TestSaga()
        await saga.run({})

        assert "sync_enter:my_step" in events
        assert "sync_success:my_step" in events


class TestStepHooksErrorHandling:
    """Test error handling in hooks."""

    @pytest.mark.asyncio
    async def test_hook_error_does_not_break_saga(self):
        """Errors in hooks should be logged but not break the saga."""
        from sagaz.decorators import Saga, step

        step_executed = False

        async def failing_hook(ctx, step_name):
            msg = "Hook failed!"
            raise RuntimeError(msg)

        class TestSaga(Saga):
            @step("my_step", on_enter=failing_hook)
            async def my_step(self, ctx):
                nonlocal step_executed
                step_executed = True
                return {}

        saga = TestSaga()

        # Saga should still complete even if hook fails
        # (depending on design decision - we'll make hooks non-fatal by default)
        await saga.run({})

        assert step_executed is True

    @pytest.mark.asyncio
    async def test_on_success_error_does_not_hide_result(self):
        """Error in on_success hook should not hide the step result."""
        from sagaz.decorators import Saga, step

        async def failing_success_hook(ctx, step_name, result):
            msg = "Success hook failed!"
            raise RuntimeError(msg)

        class TestSaga(Saga):
            @step("my_step", on_success=failing_success_hook)
            async def my_step(self, ctx):
                return {"order_id": "ORD-789"}

        saga = TestSaga()
        result = await saga.run({})

        # Result should still be in context
        assert result.get("order_id") == "ORD-789"


class TestHookHelperDecorators:
    """Test convenience decorators for common hook patterns."""

    @pytest.mark.asyncio
    async def test_on_step_enter_decorator(self):
        """@on_step_enter decorator should work standalone."""
        from sagaz.decorators import Saga, step
        from sagaz.hooks import on_step_enter

        entered_steps = []

        @on_step_enter
        async def track_enter(ctx, step_name):
            entered_steps.append(step_name)

        class TestSaga(Saga):
            @step("step1", on_enter=track_enter)
            async def step1(self, ctx):
                return {}

            @step("step2", depends_on=["step1"], on_enter=track_enter)
            async def step2(self, ctx):
                return {}

        saga = TestSaga()
        await saga.run({})

        assert entered_steps == ["step1", "step2"]

    @pytest.mark.asyncio
    async def test_publish_on_success_helper(self):
        """publish_on_success helper creates a hook that publishes events."""
        from sagaz.decorators import Saga, step
        from sagaz.hooks import publish_on_success
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage

        storage = InMemoryOutboxStorage()

        class OrderSaga(Saga):
            @step(
                "create_order",
                on_success=publish_on_success(
                    storage=storage,
                    event_type="order.created",
                    payload_builder=lambda ctx, result: {"order_id": result["order_id"]},
                ),
            )
            async def create_order(self, ctx):
                return {"order_id": "ORD-999"}

        saga = OrderSaga()
        await saga.run({"saga_id": "test-saga"})

        events = await storage.get_events_by_saga("test-saga")
        assert len(events) == 1
        assert events[0].event_type == "order.created"
