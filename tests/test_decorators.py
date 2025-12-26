"""
Tests for the declarative saga decorators module.
"""

import asyncio

import pytest

from sagaz.compensation_graph import CompensationType
from sagaz.decorators import (
    Saga,
    SagaStepDefinition,
    compensate,
    step,
)


class TestStepDecorator:
    """Tests for the @step decorator."""

    def test_step_decorator_basic(self):
        """Test basic step decorator usage."""

        @step(name="my_step")
        async def my_action(ctx):
            return {"result": "done"}

        assert hasattr(my_action, "_saga_step_meta")
        meta = my_action._saga_step_meta
        assert meta.name == "my_step"
        assert meta.depends_on == []
        assert meta.timeout_seconds == 60.0
        assert meta.max_retries == 3

    def test_step_decorator_with_all_options(self):
        """Test step decorator with all options."""

        @step(
            name="payment",
            depends_on=["order", "inventory"],
            aggregate_type="payment",
            event_type="PaymentCharged",
            timeout_seconds=30.0,
            max_retries=5,
            description="Charge the customer",
        )
        async def charge_payment(ctx):
            return {"charge_id": "CHG-123"}

        meta = charge_payment._saga_step_meta
        assert meta.name == "payment"
        assert meta.depends_on == ["order", "inventory"]
        assert meta.aggregate_type == "payment"
        assert meta.event_type == "PaymentCharged"
        assert meta.timeout_seconds == 30.0
        assert meta.max_retries == 5
        assert meta.description == "Charge the customer"

    @pytest.mark.asyncio
    async def test_decorated_function_still_callable(self):
        """Test that decorated function can still be called."""

        @step(name="test_step")
        async def my_action(ctx):
            return {"result": ctx["input"] * 2}

        result = await my_action({"input": 5})
        assert result == {"result": 10}


class TestCompensateDecorator:
    """Tests for the @compensate decorator."""

    def test_compensate_decorator_basic(self):
        """Test basic compensate decorator usage."""

        @compensate("my_step")
        async def undo_step(ctx):
            pass

        assert hasattr(undo_step, "_saga_compensation_meta")
        meta = undo_step._saga_compensation_meta
        assert meta.for_step == "my_step"
        assert meta.depends_on == []
        assert meta.compensation_type == CompensationType.MECHANICAL
        assert meta.timeout_seconds == 30.0
        assert meta.max_retries == 3

    def test_compensate_decorator_with_all_options(self):
        """Test compensate decorator with all options."""

        @compensate(
            "payment",
            depends_on=["inventory"],
            compensation_type=CompensationType.SEMANTIC,
            timeout_seconds=45.0,
            max_retries=5,
            description="Refund customer payment",
        )
        async def refund(ctx):
            pass

        meta = refund._saga_compensation_meta
        assert meta.for_step == "payment"
        assert meta.depends_on == ["inventory"]
        assert meta.compensation_type == CompensationType.SEMANTIC
        assert meta.timeout_seconds == 45.0
        assert meta.max_retries == 5
        assert meta.description == "Refund customer payment"

    @pytest.mark.asyncio
    async def test_decorated_function_still_callable(self):
        """Test that decorated compensation function can still be called."""
        compensation_called = False

        @compensate("my_step")
        async def undo_step(ctx):
            nonlocal compensation_called
            compensation_called = True

        await undo_step({})
        assert compensation_called


class TestSagaStepDefinition:
    """Tests for SagaStepDefinition dataclass."""

    def test_create_basic_definition(self):
        """Test creating a basic step definition."""

        async def action(ctx):
            return {"done": True}

        step_def = SagaStepDefinition(step_id="my_step", forward_fn=action)

        assert step_def.step_id == "my_step"
        assert step_def.forward_fn == action
        assert step_def.compensation_fn is None
        assert step_def.depends_on == []
        assert step_def.compensation_depends_on == []
        assert step_def.compensation_type == CompensationType.MECHANICAL


class TestSaga:
    """Tests for Saga base class."""

    def test_collect_steps(self):
        """Test that steps are collected from decorated methods."""

        class TestSaga(Saga):
            @step(name="step1")
            async def step_one(self, ctx):
                return {}

            @step(name="step2", depends_on=["step1"])
            async def step_two(self, ctx):
                return {}

        saga = TestSaga()

        assert len(saga._steps) == 2
        assert "step1" in saga._step_registry
        assert "step2" in saga._step_registry
        assert saga._step_registry["step2"].depends_on == ["step1"]

    def test_collect_compensations(self):
        """Test that compensations are attached to steps."""

        class TestSaga(Saga):
            @step(name="create")
            async def create(self, ctx):
                return {"id": "123"}

            @compensate("create")
            async def undo_create(self, ctx):
                pass

        saga = TestSaga()

        step_def = saga._step_registry["create"]
        assert step_def.compensation_fn is not None

    def test_get_steps(self):
        """Test get_steps returns a copy."""

        class TestSaga(Saga):
            @step(name="step1")
            async def step_one(self, ctx):
                return {}

        saga = TestSaga()
        steps = saga.get_steps()

        # Modifying returned list shouldn't affect original
        steps.clear()

        assert len(saga._steps) == 1

    def test_get_step(self):
        """Test get_step by name."""

        class TestSaga(Saga):
            @step(name="my_step", description="Test step")
            async def my_step(self, ctx):
                return {}

        saga = TestSaga()

        step_def = saga.get_step("my_step")
        assert step_def is not None
        assert step_def.description == "Test step"

        step_def = saga.get_step("nonexistent")
        assert step_def is None

    def test_get_execution_order_simple(self):
        """Test execution order with linear dependencies."""

        class TestSaga(Saga):
            @step(name="step1")
            async def step_one(self, ctx):
                return {}

            @step(name="step2", depends_on=["step1"])
            async def step_two(self, ctx):
                return {}

            @step(name="step3", depends_on=["step2"])
            async def step_three(self, ctx):
                return {}

        saga = TestSaga()
        levels = saga.get_execution_order()

        assert len(levels) == 3
        assert levels[0][0].step_id == "step1"
        assert levels[1][0].step_id == "step2"
        assert levels[2][0].step_id == "step3"

    def test_get_execution_order_parallel(self):
        """Test execution order with parallel steps."""

        class TestSaga(Saga):
            @step(name="setup")
            async def setup(self, ctx):
                return {}

            @step(name="parallel_a", depends_on=["setup"])
            async def parallel_a(self, ctx):
                return {}

            @step(name="parallel_b", depends_on=["setup"])
            async def parallel_b(self, ctx):
                return {}

        saga = TestSaga()
        levels = saga.get_execution_order()

        assert len(levels) == 2
        assert levels[0][0].step_id == "setup"

        # parallel_a and parallel_b should be in same level
        parallel_level = {s.step_id for s in levels[1]}
        assert parallel_level == {"parallel_a", "parallel_b"}

    def test_get_execution_order_empty(self):
        """Test execution order with no steps."""

        class EmptySaga(Saga):
            pass

        saga = EmptySaga()
        levels = saga.get_execution_order()

        assert levels == []

    @pytest.mark.asyncio
    async def test_run_success(self):
        """Test successful saga run."""

        class TestSaga(Saga):
            @step(name="step1")
            async def step_one(self, ctx):
                return {"step1_done": True}

            @step(name="step2", depends_on=["step1"])
            async def step_two(self, ctx):
                return {"step2_done": True}

        saga = TestSaga()
        result = await saga.run({"initial": "data"})

        assert result["initial"] == "data"
        assert result["step1_done"] is True
        assert result["step2_done"] is True
        assert result["__step1_completed"] is True
        assert result["__step2_completed"] is True

    @pytest.mark.asyncio
    async def test_run_with_compensation_on_failure(self):
        """Test that compensations run when saga fails."""
        compensations_called = []

        class TestSaga(Saga):
            @step(name="step1")
            async def step_one(self, ctx):
                return {"step1_done": True}

            @compensate("step1")
            async def undo_step1(self, ctx):
                compensations_called.append("step1")

            @step(name="step2", depends_on=["step1"])
            async def step_two(self, ctx):
                msg = "Step 2 failed!"
                raise ValueError(msg)

            @compensate("step2")
            async def undo_step2(self, ctx):
                compensations_called.append("step2")

        saga = TestSaga()

        with pytest.raises(ValueError, match="Step 2 failed"):
            await saga.run({"initial": "data"})

        # Only step1 was completed, so only step1 should be compensated
        assert "step1" in compensations_called
        # step2 never completed, so shouldn't be in compensation list

    @pytest.mark.asyncio
    async def test_run_with_timeout(self):
        """Test step timeout handling."""

        class TestSaga(Saga):
            @step(name="slow_step", timeout_seconds=0.1)
            async def slow_step(self, ctx):
                await asyncio.sleep(0.5)  # Will timeout (longer than 0.1s timeout)
                return {}

        saga = TestSaga()

        with pytest.raises(TimeoutError, match="slow_step.*timed out"):
            await saga.run({})

    @pytest.mark.asyncio
    async def test_run_parallel_execution(self):
        """Test that parallel steps actually run in parallel."""
        execution_times = {}

        class TestSaga(Saga):
            @step(name="setup")
            async def setup(self, ctx):
                return {}

            @step(name="parallel_a", depends_on=["setup"])
            async def parallel_a(self, ctx):
                execution_times["a_start"] = asyncio.get_event_loop().time()
                await asyncio.sleep(0.1)
                execution_times["a_end"] = asyncio.get_event_loop().time()
                return {"a": True}

            @step(name="parallel_b", depends_on=["setup"])
            async def parallel_b(self, ctx):
                execution_times["b_start"] = asyncio.get_event_loop().time()
                await asyncio.sleep(0.1)
                execution_times["b_end"] = asyncio.get_event_loop().time()
                return {"b": True}

        saga = TestSaga()
        result = await saga.run({})

        # Both should complete
        assert result["a"] is True
        assert result["b"] is True

        # They should have started at roughly the same time (parallel)
        # If sequential, b_start would be after a_end
        time_diff = abs(execution_times["a_start"] - execution_times["b_start"])
        assert time_diff < 0.05  # Started within 50ms of each other

    def test_repr(self):
        """Test string representation."""

        class TestSaga(Saga):
            @step(name="step1")
            async def step_one(self, ctx):
                return {}

            @step(name="step2")
            async def step_two(self, ctx):
                return {}

        saga = TestSaga()
        repr_str = repr(saga)

        assert "TestSaga" in repr_str
        assert "steps=2" in repr_str


class TestSagaAdvanced:
    """Advanced tests for Saga."""

    @pytest.mark.asyncio
    async def test_compensation_order_respected(self):
        """Test that compensation order respects dependencies."""
        compensation_order = []

        class TestSaga(Saga):
            @step(name="step1")
            async def step1(self, ctx):
                return {"s1": True}

            @compensate("step1")
            async def undo_step1(self, ctx):
                compensation_order.append("step1")

            @step(name="step2", depends_on=["step1"])
            async def step2(self, ctx):
                return {"s2": True}

            @compensate("step2", depends_on=["step1"])
            async def undo_step2(self, ctx):
                compensation_order.append("step2")

            @step(name="step3", depends_on=["step2"])
            async def step3(self, ctx):
                msg = "Fail!"
                raise ValueError(msg)

        saga = TestSaga()

        with pytest.raises(ValueError):
            await saga.run({})

        # step2 should compensate before step1 (reverse order)
        assert compensation_order.index("step2") < compensation_order.index("step1")

    @pytest.mark.asyncio
    async def test_compensation_continues_on_error(self):
        """Test that compensation continues even if one fails."""
        compensations_attempted = []

        class TestSaga(Saga):
            @step(name="step1")
            async def step1(self, ctx):
                return {}

            @compensate("step1")
            async def undo_step1(self, ctx):
                compensations_attempted.append("step1_attempted")
                msg = "Compensation failed!"
                raise Exception(msg)

            @step(name="step2")
            async def step2(self, ctx):
                return {}

            @compensate("step2")
            async def undo_step2(self, ctx):
                compensations_attempted.append("step2_attempted")

            @step(name="step3", depends_on=["step1", "step2"])
            async def step3(self, ctx):
                msg = "Fail!"
                raise ValueError(msg)

        saga = TestSaga()

        with pytest.raises(ValueError):
            await saga.run({})

        # Both compensations should be attempted even though one failed
        assert "step1_attempted" in compensations_attempted
        assert "step2_attempted" in compensations_attempted

    @pytest.mark.asyncio
    async def test_saga_with_custom_id(self):
        """Test running saga with custom ID."""

        class TestSaga(Saga):
            @step(name="step1")
            async def step1(self, ctx):
                return {}

        saga = TestSaga()
        result = await saga.run({}, saga_id="custom-saga-123")

        # Should complete without error
        assert result["__step1_completed"] is True
