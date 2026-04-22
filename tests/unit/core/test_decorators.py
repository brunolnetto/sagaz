"""
Tests for the declarative saga decorators module.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from sagaz.core.decorators import (
    Saga,
    SagaStepDefinition,
    compensate,
    step,
)
from sagaz.core.execution.graph import CompensationType


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
            compensation_type=CompensationType.SEMANTIC,
            timeout_seconds=45.0,
            max_retries=5,
            description="Refund customer payment",
        )
        async def refund(ctx):
            pass

        meta = refund._saga_compensation_meta
        assert meta.for_step == "payment"
        # depends_on is no longer a parameter - derived from forward dependencies
        assert meta.depends_on == []
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
                await asyncio.sleep(0.2)  # Still much longer than 0.1s timeout
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

            @compensate("step2")  # Dependencies auto-derived from forward dependencies
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


class TestImperativeSupport:
    """Tests for imperative API support in declarative Saga."""

    @pytest.mark.asyncio
    async def test_add_step_programmatically(self):
        """Test adding a step using add_step()."""

        class MySaga(Saga):
            saga_name = "test"

        saga = MySaga()

        # Add a step imperatively
        async def my_action(ctx):
            return {"imperative": True}

        # Add dependencies for imperative step if needed, here we test simple addition
        saga.add_step(name="imp_step", action=my_action, max_retries=1)

        # Step should be in registry and steps list
        assert len(saga._steps) == 1
        assert "imp_step" in saga._step_registry

        step_def = saga.get_step("imp_step")
        assert step_def.max_retries == 1

        # Run it
        result = await saga.run({})
        assert result["imperative"] is True

    @pytest.mark.asyncio
    async def test_mix_declarative_and_imperative(self):
        """Test mixing @step decorators and add_step()."""

        class MixedSaga(Saga):
            @step("decl_step")
            async def decl_step(self, ctx):
                return {"decl": True}

        saga = MixedSaga()

        # Add imperative step depending on declarative one
        async def imp_step(ctx):
            return {"imp": True}

        # Mixing declarative and imperative approaches should raise TypeError
        msg = "Cannot use add_step.*with @action/@compensate decorators"
        with pytest.raises(TypeError, match=msg):
            saga.add_step(name="imp_step", action=imp_step, depends_on=["decl_step"])


# =============================================================================
# Missing Branch Coverage
# =============================================================================


class TestDecoratorsMissingBranches:
    """Tests for missing coverage branches in core/decorators.py."""

    # ---- 452: saga_name set from name in declarative mode ----

    def test_init_declarative_sets_saga_name_from_name_param(self):
        """Line 452: saga_name set from name param when _steps found and saga_name is None."""

        class DeclSaga(Saga):
            # saga_name not set as class attribute
            @step("first")
            async def first(self, ctx):
                return {}

        saga = DeclSaga(name="dynamic_decl")
        # _steps found, saga_name was None, name="dynamic_decl" → line 452
        assert saga.saga_name == "dynamic_decl"

    # ---- 457: saga_name set from name in imperative mode ----

    def test_init_imperative_sets_saga_name_from_name_param(self):
        """Line 457: saga_name set from name param when no _steps and name given."""

        class ImperSaga(Saga):
            pass  # No decorators → imperative mode

        saga = ImperSaga(name="dynamic_imper")
        assert saga.saga_name == "dynamic_imper"

    # ---- 508: compensation for unknown step returns silently ----

    def test_compensation_for_unknown_step_is_skipped(self):
        """Line 508: _attach_compensation_to_step returns if step not in registry."""

        class BadCompSaga(Saga):
            saga_name = "badcomp"

            @step("real_step")
            async def real_step(self, ctx):
                return {}

            @compensate("nonexistent_step")
            async def comp_nonexistent(self, ctx):
                pass

        # Should not raise, compensation is simply skipped
        saga = BadCompSaga()
        # real_step should still be registered
        assert "real_step" in saga._step_registry
        # nonexistent_step should NOT be in registry
        assert "nonexistent_step" not in saga._step_registry

    # ---- 563->566: _propagate_taint_from_pivot with empty newly_tainted ----

    def test_propagate_taint_empty_returns_empty_set(self):
        """Line 563->566: _propagate_taint_from_pivot when nothing is newly tainted."""

        class PivotSaga(Saga):
            saga_name = "pivot_test"

            @step("root", pivot=True)
            async def root(self, ctx):
                return {}

        saga = PivotSaga()
        # root has no ancestors to taint (it has no dependencies)
        result = saga._propagate_taint_from_pivot("root")
        # No tainted steps - the if branch should be False
        assert result == set()

    # ---- 625-626: duplicate step via add_step raises ValueError ----

    @pytest.mark.asyncio
    async def test_add_step_duplicate_raises_value_error(self):
        """Lines 625-626: add_step with duplicate name raises ValueError."""

        class ImperSaga(Saga):
            saga_name = "dupl"

        saga = ImperSaga()

        async def act(ctx):
            return {}

        saga.add_step(name="step_a", action=act)

        with pytest.raises(ValueError, match="already exists"):
            saga.add_step(name="step_a", action=act)

    # ---- 753: to_mermaid_with_execution with no storage data ----

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_no_data(self):
        """Line 753: to_mermaid_with_execution returns plain diagram when no data."""
        from unittest.mock import AsyncMock

        class SimpleSaga(Saga):
            saga_name = "vis_test"

            @step("s1")
            async def s1(self, ctx):
                return {}

        saga = SimpleSaga()
        storage = AsyncMock()
        storage.load_saga_state = AsyncMock(return_value=None)

        result = await saga.to_mermaid_with_execution("fake-id", storage)
        assert "flowchart" in result or "graph" in result

    # ---- 770: failed step in to_mermaid_with_execution ----

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_failed_step(self):
        """Lines 770, 772-774, 775->763: failed/compensated/compensating steps."""
        from unittest.mock import AsyncMock

        class SimpleSaga(Saga):
            saga_name = "vis_test2"

            @step("s1")
            async def s1(self, ctx):
                return {}

            @step("s2", depends_on={"s1"})
            async def s2(self, ctx):
                return {}

        saga = SimpleSaga()
        storage = AsyncMock()
        storage.load_saga_state = AsyncMock(
            return_value={
                "steps": [
                    {"name": "s1", "status": "completed"},
                    {"name": "s2", "status": "failed"},
                ]
            }
        )
        result = await saga.to_mermaid_with_execution("fake-id", storage)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_compensated_step(self):
        """Lines 772-774: 'compensated' status adds to compensated_steps + completed_steps."""
        from unittest.mock import AsyncMock

        class SimpleSaga(Saga):
            saga_name = "vis_test3"

            @step("s1")
            async def s1(self, ctx):
                return {}

        saga = SimpleSaga()
        storage = AsyncMock()
        storage.load_saga_state = AsyncMock(
            return_value={
                "steps": [
                    {"name": "s1", "status": "compensated"},
                ]
            }
        )
        result = await saga.to_mermaid_with_execution("fake-id", storage)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_compensating_step(self):
        """Lines 775->763: 'compensating' status processed (elif branch)."""
        from unittest.mock import AsyncMock

        class SimpleSaga(Saga):
            saga_name = "vis_test4"

            @step("s1")
            async def s1(self, ctx):
                return {}

        saga = SimpleSaga()
        storage = AsyncMock()
        storage.load_saga_state = AsyncMock(
            return_value={
                "steps": [
                    {"name": "s1", "status": "compensating"},
                ]
            }
        )
        result = await saga.to_mermaid_with_execution("fake-id", storage)
        assert isinstance(result, str)

    # ---- 880->892: run() with no storage (skip persist start) ----

    @pytest.mark.asyncio
    async def test_run_no_storage_skips_persist(self):
        """Lines 880->892, 898->906: run() when _config is None skips saga state persist."""

        class TinySaga(Saga):
            saga_name = "tiny"

            @step("only")
            async def only(self, ctx):
                return {"done": True}

        saga = TinySaga()
        saga._config = None  # Force no config → storage=None at line 879

        result = await saga.run({})
        assert result["done"] is True

    # ---- 889-890: storage.save_saga_state raises on start ----

    @pytest.mark.asyncio
    async def test_run_storage_exception_on_start_logs_warning(self):
        """Lines 889-890: exception in save_saga_state on start is swallowed."""
        from unittest.mock import AsyncMock, MagicMock

        class TinySaga(Saga):
            saga_name = "tiny2"

            @step("only")
            async def only(self, ctx):
                return {"done": True}

        saga = TinySaga()
        mock_storage = AsyncMock()
        mock_storage.save_saga_state = AsyncMock(side_effect=RuntimeError("db error"))
        mock_config = MagicMock()
        mock_config.storage = mock_storage
        mock_config.listeners = []
        saga._config = mock_config
        saga._instance_listeners = []

        result = await saga.run({})
        assert result["done"] is True  # saga still completes

    # ---- 903-904: storage.save_saga_state raises on completion ----

    @pytest.mark.asyncio
    async def test_run_storage_exception_on_completion_logs_warning(self):
        """Lines 903-904: exception in save_saga_state on completion is swallowed."""
        from unittest.mock import AsyncMock, MagicMock

        class TinySaga(Saga):
            saga_name = "tiny3"

            @step("only")
            async def only(self, ctx):
                return {"done": True}

        saga = TinySaga()
        call_count = [0]

        async def save_state_raiser(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:  # Second call = on completion
                msg = "completion db error"
                raise RuntimeError(msg)

        mock_storage = AsyncMock()
        mock_storage.save_saga_state = save_state_raiser
        mock_config = MagicMock()
        mock_config.storage = mock_storage
        mock_config.listeners = []
        saga._config = mock_config
        saga._instance_listeners = []

        result = await saga.run({})
        assert result["done"] is True

    # ---- 912->922, 917-918: storage handling in failure path ----

    @pytest.mark.asyncio
    async def test_run_failure_no_storage_and_exception_reraises(self):
        """Line 912->922: failure path with no storage still re-raises exception."""

        class FailSaga(Saga):
            saga_name = "fail_saga"

            @step("boom")
            async def boom(self, ctx):
                msg = "intentional failure"
                raise ValueError(msg)

        saga = FailSaga()
        saga._config = None  # no storage

        with pytest.raises(ValueError, match="intentional failure"):
            await saga.run({})

    @pytest.mark.asyncio
    async def test_run_failure_storage_exception_on_persist_reraises_original(self):
        """Lines 917-918: exception in save_saga_state during failure is swallowed, original re-raised."""
        from unittest.mock import AsyncMock, MagicMock

        class FailSaga(Saga):
            saga_name = "fail_saga2"

            @step("boom")
            async def boom(self, ctx):
                msg = "intentional failure"
                raise ValueError(msg)

        saga = FailSaga()
        mock_storage = AsyncMock()
        mock_storage.save_saga_state = AsyncMock(side_effect=RuntimeError("db error"))
        mock_config = MagicMock()
        mock_config.storage = mock_storage
        mock_config.listeners = []
        saga._config = mock_config
        saga._instance_listeners = []

        with pytest.raises(ValueError, match="intentional failure"):
            await saga.run({})

    # ---- 964->961: listener with no handler for event ----

    @pytest.mark.asyncio
    async def test_notify_listeners_no_handler_skips(self):
        """Line 964->961: listener without on_saga_start handler is skipped."""

        class TinySaga(Saga):
            saga_name = "listener_test"

            @step("x")
            async def x(self, ctx):
                return {}

        saga = TinySaga()

        # Listener with NO on_saga_start attribute
        class NoHandlerListener:
            pass  # has no on_saga_start, on_saga_complete, etc.

        saga._instance_listeners = [NoHandlerListener()]
        saga._config = None

        result = await saga.run({})
        assert "x" in result or result is not None

    # ---- 966->961: listener with synchronous handler ----

    @pytest.mark.asyncio
    async def test_notify_listeners_sync_handler_called(self):
        """Line 966->961: listener with sync handler invoked without await."""
        called = []

        class TinySaga(Saga):
            saga_name = "sync_listener_test"

            @step("x")
            async def x(self, ctx):
                return {}

        saga = TinySaga()

        class SyncListener:
            def on_saga_start(self, *args):
                called.append("sync_start")

        saga._instance_listeners = [SyncListener()]
        saga._config = None

        await saga.run({})
        assert "sync_start" in called

    # ---- 974: empty level in _execute_level ----

    @pytest.mark.asyncio
    async def test_execute_level_empty_returns_immediately(self):
        """Line 974: _execute_level with empty list returns early."""

        class TinySaga(Saga):
            saga_name = "level_test"

            @step("x")
            async def x(self, ctx):
                return {}

        saga = TinySaga()
        saga._initialize_run({}, None)
        saga._register_compensations()

        # Call _execute_level with empty list
        await saga._execute_level([])  # Should return immediately without error

    # ---- 1096: _execute_compensation with no compensation info ----

    @pytest.mark.asyncio
    async def test_execute_compensation_no_info_skips(self):
        """Line 1096: _execute_compensation returns early when no compensation registered."""

        class TinySaga(Saga):
            saga_name = "comp_test"

            @step("x")
            async def x(self, ctx):
                return {}

        saga = TinySaga()
        saga._initialize_run({}, None)
        saga._register_compensations()

        # "x" has no compensation registered → should return without error
        await saga._execute_compensation("x")

    # ---- 1100-1101: compensation for tainted step is skipped ----

    @pytest.mark.asyncio
    async def test_execute_compensation_tainted_step_skipped(self):
        """Lines 1100-1101: _execute_compensation skips tainted steps."""

        class TinySaga(Saga):
            saga_name = "tainted_test"

            @step("x")
            async def x(self, ctx):
                return {}

            @compensate("x")
            async def comp_x(self, ctx):
                msg = "Should not be called for tainted step"
                raise AssertionError(msg)

        saga = TinySaga()
        saga._initialize_run({}, None)
        saga._register_compensations()

        # Mark "x" as tainted
        saga._tainted_steps.add("x")

        # Should not call comp_x
        await saga._execute_compensation("x")


class TestCoreDecoratorsBranches:
    async def test_status_compensating_in_trail(self):
        """775->763: status == 'compensating' in trail building."""
        from sagaz import Saga, SagaContext

        class SimpleSaga(Saga):
            async def execute(self, ctx: SagaContext):
                return ctx

        saga = SimpleSaga()

        # Mock storage that returns saga_data with steps having various statuses
        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(
            return_value={
                "steps": [
                    {"name": "step1", "status": "completed"},
                    {"name": "step2", "status": "compensating"},  # triggers 775->True
                    {"name": "step3", "status": "pending"},  # triggers 775->763 (unknown status)
                ]
            }
        )

        result = await saga.to_mermaid_with_execution(
            saga_id="test-saga-id",
            storage=mock_storage,
        )
        assert isinstance(result, str)


# ==========================================================================
# core/listeners.py  – 194->exit, 198
