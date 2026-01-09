"""
Tests for the compensation graph module.
"""

import pytest

from sagaz.execution.graph import (
    CircularDependencyError,
    CompensationFailureStrategy,
    CompensationNode,
    CompensationResult,
    CompensationType,
    MissingDependencyError,
    SagaExecutionGraph,
)


class TestCompensationNode:
    """Tests for CompensationNode dataclass."""

    def test_create_basic_node(self):
        """Test creating a basic compensation node."""

        async def compensate(ctx):
            pass

        node = CompensationNode(step_id="my_step", compensation_fn=compensate)

        assert node.step_id == "my_step"
        assert node.compensation_fn == compensate
        assert node.depends_on == []
        assert node.compensation_type == CompensationType.MECHANICAL
        assert node.max_retries == 3
        assert node.timeout_seconds == 30.0

    def test_create_node_with_dependencies(self):
        """Test creating a node with dependencies."""

        async def compensate(ctx):
            pass

        node = CompensationNode(
            step_id="payment",
            compensation_fn=compensate,
            depends_on=["order", "inventory"],
            compensation_type=CompensationType.SEMANTIC,
            description="Refund payment",
            max_retries=5,
            timeout_seconds=60.0,
        )

        assert node.depends_on == ["order", "inventory"]
        assert node.compensation_type == CompensationType.SEMANTIC
        assert node.description == "Refund payment"
        assert node.max_retries == 5
        assert node.timeout_seconds == 60.0


class TestCompensationType:
    """Tests for CompensationType enum."""

    def test_compensation_types(self):
        """Test all compensation types exist."""
        assert CompensationType.MECHANICAL.value == "mechanical"
        assert CompensationType.SEMANTIC.value == "semantic"
        assert CompensationType.MANUAL.value == "manual"


class TestSagaExecutionGraph:
    """Tests for SagaExecutionGraph."""

    def test_register_compensation(self):
        """Test registering a compensation."""
        graph = SagaExecutionGraph()

        async def undo_step1(ctx):
            pass

        graph.register_compensation("step1", undo_step1)

        assert "step1" in graph.nodes
        assert graph.nodes["step1"].step_id == "step1"
        assert graph.nodes["step1"].compensation_fn == undo_step1

    def test_register_compensation_with_options(self):
        """Test registering with all options."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation(
            "payment",
            undo,
            depends_on=["order"],
            compensation_type=CompensationType.SEMANTIC,
            description="Refund payment",
            max_retries=5,
            timeout_seconds=45.0,
        )

        node = graph.nodes["payment"]
        assert node.depends_on == ["order"]
        assert node.compensation_type == CompensationType.SEMANTIC
        assert node.description == "Refund payment"
        assert node.max_retries == 5
        assert node.timeout_seconds == 45.0

    def test_mark_step_executed(self):
        """Test marking steps as executed."""
        graph = SagaExecutionGraph()

        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")

        assert graph.executed_steps == ["step1", "step2"]

    def test_mark_step_executed_idempotent(self):
        """Test that marking the same step twice doesn't duplicate."""
        graph = SagaExecutionGraph()

        graph.mark_step_executed("step1")
        graph.mark_step_executed("step1")

        assert graph.executed_steps == ["step1"]

    def test_unmark_step_executed(self):
        """Test unmarking executed steps."""
        graph = SagaExecutionGraph()

        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")
        graph.unmark_step_executed("step1")

        assert graph.executed_steps == ["step2"]

    def test_get_executed_steps(self):
        """Test getting executed steps returns a copy."""
        graph = SagaExecutionGraph()

        graph.mark_step_executed("step1")
        executed = graph.get_executed_steps()

        # Modifying returned list shouldn't affect original
        executed.append("step2")

        assert graph.executed_steps == ["step1"]

    def test_compensation_order_simple(self):
        """Test simple compensation order (reverse of execution)."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        # step1 runs first, step2 depends on step1
        graph.register_compensation("step1", undo)
        graph.register_compensation("step2", undo, depends_on=["step1"])

        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")

        # Compensation order: step2 first (no deps waiting), then step1
        levels = graph.get_compensation_order()

        assert len(levels) == 2
        assert levels[0] == ["step2"]  # step2 compensates first
        assert levels[1] == ["step1"]  # step1 compensates after

    def test_compensation_order_parallel(self):
        """Test that independent steps can compensate in parallel."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        # step2 and step3 both depend on step1, but not on each other
        graph.register_compensation("step1", undo)
        graph.register_compensation("step2", undo, depends_on=["step1"])
        graph.register_compensation("step3", undo, depends_on=["step1"])

        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")
        graph.mark_step_executed("step3")

        levels = graph.get_compensation_order()

        assert len(levels) == 2
        # step2 and step3 can compensate in parallel
        assert set(levels[0]) == {"step2", "step3"}
        # step1 compensates last
        assert levels[1] == ["step1"]

    def test_compensation_order_only_executed_steps(self):
        """Test that only executed steps are compensated."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)
        graph.register_compensation("step2", undo, depends_on=["step1"])
        graph.register_compensation("step3", undo, depends_on=["step2"])

        # Only step1 executed
        graph.mark_step_executed("step1")

        levels = graph.get_compensation_order()

        assert levels == [["step1"]]

    def test_compensation_order_empty(self):
        """Test compensation order with no executed steps."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)

        levels = graph.get_compensation_order()

        assert levels == []

    def test_compensation_order_complex_dag(self):
        """Test complex DAG compensation order."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        # Complex diamond dependency:
        #     step1
        #    /     \
        # step2   step3
        #    \     /
        #     step4

        graph.register_compensation("step1", undo)
        graph.register_compensation("step2", undo, depends_on=["step1"])
        graph.register_compensation("step3", undo, depends_on=["step1"])
        graph.register_compensation("step4", undo, depends_on=["step2", "step3"])

        for step in ["step1", "step2", "step3", "step4"]:
            graph.mark_step_executed(step)

        levels = graph.get_compensation_order()

        # Compensation order (reverse of dependencies)
        assert len(levels) == 3
        assert levels[0] == ["step4"]  # step4 first (depends on both 2 and 3)
        assert set(levels[1]) == {"step2", "step3"}  # parallel
        assert levels[2] == ["step1"]  # step1 last

    def test_validate_success(self):
        """Test validation passes for valid graph."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)
        graph.register_compensation("step2", undo, depends_on=["step1"])

        # Should not raise
        graph.validate()

    def test_validate_missing_dependency(self):
        """Test validation fails for missing dependency."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step2", undo, depends_on=["nonexistent"])

        with pytest.raises(MissingDependencyError) as exc_info:
            graph.validate()

        assert exc_info.value.step_id == "step2"
        assert exc_info.value.missing_dep == "nonexistent"

    def test_validate_circular_dependency(self):
        """Test validation fails for circular dependency."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo, depends_on=["step2"])
        graph.register_compensation("step2", undo, depends_on=["step1"])

        with pytest.raises(CircularDependencyError):
            graph.validate()

    def test_get_compensation_info(self):
        """Test getting compensation info by step ID."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo, description="Undo step 1")

        info = graph.get_compensation_info("step1")
        assert info is not None
        assert info.description == "Undo step 1"

        info = graph.get_compensation_info("nonexistent")
        assert info is None

    def test_clear(self):
        """Test clearing the graph."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)
        graph.mark_step_executed("step1")

        graph.clear()

        assert len(graph.nodes) == 0
        assert len(graph.executed_steps) == 0

    def test_reset_execution(self):
        """Test resetting execution state."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)
        graph.mark_step_executed("step1")

        graph.reset_execution()

        assert len(graph.nodes) == 1  # Registration preserved
        assert len(graph.executed_steps) == 0  # Execution cleared

    def test_repr(self):
        """Test string representation."""
        graph = SagaExecutionGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)
        graph.mark_step_executed("step1")

        repr_str = repr(graph)

        # SagaExecutionGraph is now an alias for SagaExecutionGraph
        assert "SagaExecutionGraph" in repr_str
        assert "nodes=1" in repr_str
        assert "executed=1" in repr_str


class TestCircularDependencyError:
    """Tests for CircularDependencyError."""

    def test_error_message(self):
        """Test error message contains cycle information."""
        error = CircularDependencyError(["step1", "step2", "step1"])

        assert "step1" in str(error)
        assert "step2" in str(error)
        assert "Circular dependency" in str(error)
        assert error.cycle == ["step1", "step2", "step1"]


class TestMissingDependencyError:
    """Tests for MissingDependencyError."""

    def test_error_message(self):
        """Test error message contains dependency information."""
        error = MissingDependencyError("my_step", "missing_step")

        assert "my_step" in str(error)
        assert "missing_step" in str(error)
        assert error.step_id == "my_step"
        assert error.missing_dep == "missing_step"


class TestCompensationResult:
    """Tests for CompensationResult dataclass."""

    def test_create_success_result(self):
        """Test creating a successful compensation result."""
        result = CompensationResult(
            success=True,
            executed=["step1", "step2"],
            failed=[],
            skipped=[],
            results={"step1": {"id": 1}, "step2": {"id": 2}},
            errors={},
            execution_time_ms=123.45,
        )

        assert result.success is True
        assert result.executed == ["step1", "step2"]
        assert len(result.failed) == 0
        assert len(result.skipped) == 0
        assert result.results["step1"]["id"] == 1
        assert result.execution_time_ms == 123.45

    def test_create_failure_result(self):
        """Test creating a failed compensation result."""
        error = Exception("Test error")
        result = CompensationResult(
            success=False,
            executed=["step1"],
            failed=["step2"],
            skipped=["step3"],
            results={"step1": {"id": 1}},
            errors={"step2": error},
            execution_time_ms=200.0,
        )

        assert result.success is False
        assert result.failed == ["step2"]
        assert result.skipped == ["step3"]
        assert result.errors["step2"] == error


class TestCompensationFailureStrategy:
    """Tests for CompensationFailureStrategy enum."""

    def test_all_strategies_exist(self):
        """Test all failure strategies are defined."""
        assert CompensationFailureStrategy.FAIL_FAST.value == "fail_fast"
        assert CompensationFailureStrategy.CONTINUE_ON_ERROR.value == "continue_on_error"
        assert CompensationFailureStrategy.RETRY_THEN_CONTINUE.value == "retry_then_continue"
        assert CompensationFailureStrategy.SKIP_DEPENDENTS.value == "skip_dependents"


class TestCompensationResultPassing:
    """Tests for compensation result passing feature."""

    @pytest.mark.asyncio
    async def test_compensation_with_return_value(self):
        """Test compensation can return a value."""
        graph = SagaExecutionGraph()

        async def cancel_order(ctx, comp_results=None):
            return {"cancellation_id": "cancel-123", "cancelled_at": "2024-01-01"}

        graph.register_compensation("cancel_order", cancel_order)
        graph.mark_step_executed("cancel_order")

        result = await graph.execute_compensations({"order_id": "123"})

        assert result.success is True
        assert "cancel_order" in result.executed
        assert result.results["cancel_order"]["cancellation_id"] == "cancel-123"

    @pytest.mark.asyncio
    async def test_compensation_result_passing_between_steps(self):
        """Test results are passed from one compensation to another."""
        graph = SagaExecutionGraph()

        results_tracker = {}

        async def refund_payment(ctx, comp_results=None):
            results_tracker["refund_payment_received"] = comp_results
            return {"refund_id": "refund-456"}

        async def cancel_order(ctx, comp_results=None):
            results_tracker["cancel_order_received"] = comp_results
            # Access result from refund_payment (which compensates first)
            refund_id = comp_results.get("refund_payment", {}).get("refund_id")
            return {"cancellation_id": "cancel-123", "referenced_refund": refund_id}

        # Forward execution: refund_payment depends on cancel_order
        # Compensation order: refund_payment first (level 0), cancel_order second (level 1)
        graph.register_compensation("cancel_order", cancel_order)
        graph.register_compensation("refund_payment", refund_payment, depends_on=["cancel_order"])
        graph.mark_step_executed("cancel_order")
        graph.mark_step_executed("refund_payment")

        result = await graph.execute_compensations({"order_id": "123"})

        assert result.success is True
        assert "refund_payment" in result.executed
        assert "cancel_order" in result.executed

        # Verify cancel_order received refund_payment's result
        assert results_tracker["cancel_order_received"]["refund_payment"]["refund_id"] == "refund-456"
        assert result.results["cancel_order"]["referenced_refund"] == "refund-456"

    @pytest.mark.asyncio
    async def test_backward_compatibility_old_signature(self):
        """Test old compensation signature (ctx only) still works."""
        graph = SagaExecutionGraph()

        async def old_style_compensation(ctx):
            # Old signature: only accepts ctx
            return None

        graph.register_compensation("old_step", old_style_compensation)
        graph.mark_step_executed("old_step")

        result = await graph.execute_compensations({"data": "test"})

        assert result.success is True
        assert "old_step" in result.executed

    @pytest.mark.asyncio
    async def test_mixed_old_and_new_signatures(self):
        """Test mixing old and new compensation signatures."""
        graph = SagaExecutionGraph()

        async def old_comp(ctx):
            pass

        async def new_comp(ctx, comp_results=None):
            return {"new_result": "value"}

        graph.register_compensation("old_step", old_comp)
        graph.register_compensation("new_step", new_comp)
        graph.mark_step_executed("old_step")
        graph.mark_step_executed("new_step")

        result = await graph.execute_compensations({})

        assert result.success is True
        assert "old_step" in result.executed
        assert "new_step" in result.executed
        assert result.results.get("new_step", {}).get("new_result") == "value"


class TestFailureStrategies:
    """Tests for compensation failure strategies."""

    @pytest.mark.asyncio
    async def test_fail_fast_strategy(self):
        """Test FAIL_FAST stops on first failure."""
        graph = SagaExecutionGraph()

        async def failing_comp(ctx, comp_results=None):
            msg = "Intentional failure"
            raise Exception(msg)

        async def should_not_run(ctx, comp_results=None):
            return {"executed": True}

        # step2 depends on step1, so step1 compensates after step2
        graph.register_compensation("step1", should_not_run)
        graph.register_compensation("step2", failing_comp, depends_on=["step1"])
        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")

        result = await graph.execute_compensations(
            {},
            failure_strategy=CompensationFailureStrategy.FAIL_FAST
        )

        assert result.success is False
        assert "step2" in result.failed
        assert "step1" in result.skipped  # Should be skipped after step2 fails

    @pytest.mark.asyncio
    async def test_continue_on_error_strategy(self):
        """Test CONTINUE_ON_ERROR executes all compensations despite failures."""
        graph = SagaExecutionGraph()

        async def failing_comp(ctx, comp_results=None):
            msg = "Intentional failure"
            raise Exception(msg)

        async def succeeding_comp(ctx, comp_results=None):
            return {"success": True}

        graph.register_compensation("step1", succeeding_comp)
        graph.register_compensation("step2", failing_comp, depends_on=["step1"])
        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")

        result = await graph.execute_compensations(
            {},
            failure_strategy=CompensationFailureStrategy.CONTINUE_ON_ERROR
        )

        assert result.success is False
        assert "step2" in result.failed
        assert "step1" in result.executed  # Should still execute
        assert result.results["step1"]["success"] is True

    @pytest.mark.asyncio
    async def test_retry_then_continue_strategy(self):
        """Test RETRY_THEN_CONTINUE retries failed compensations."""
        graph = SagaExecutionGraph()

        attempt_counts = {"step1": 0}

        async def flaky_comp(ctx, comp_results=None):
            attempt_counts["step1"] += 1
            if attempt_counts["step1"] < 2:
                msg = "Temporary failure"
                raise Exception(msg)
            return {"attempt": attempt_counts["step1"]}

        graph.register_compensation("step1", flaky_comp, max_retries=3)
        graph.mark_step_executed("step1")

        result = await graph.execute_compensations(
            {},
            failure_strategy=CompensationFailureStrategy.RETRY_THEN_CONTINUE
        )

        assert result.success is True
        assert "step1" in result.executed
        assert attempt_counts["step1"] == 2  # Failed once, succeeded on retry

    @pytest.mark.asyncio
    async def test_skip_dependents_strategy(self):
        """Test SKIP_DEPENDENTS skips steps whose compensation depends on failed ones."""
        graph = SagaExecutionGraph()

        async def step1_comp(ctx, comp_results=None):
            return {"step1": "done"}

        async def failing_comp(ctx, comp_results=None):
            msg = "Intentional failure"
            raise Exception(msg)

        async def dependent_comp(ctx, comp_results=None):
            return {"should_not_execute": True}

        # Setup compensation dependencies:
        # Forward: step3 → step2 → step1 (step2 depends on step3, step1 depends on step2)
        # Compensation order: step1 → step2 → step3 (reverse of forward)
        #
        # When we execute compensations:
        # - Level 0: step1 runs (no one depends on it in compensation)
        # - Level 1: step2 runs (depends on step1's compensation) - FAILS
        # - Level 2: step3 should be SKIPPED (depends on step2's compensation, which failed)

        graph.register_compensation("step1", step1_comp, depends_on=["step2"])
        graph.register_compensation("step2", failing_comp, depends_on=["step3"])
        graph.register_compensation("step3", dependent_comp)

        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")
        graph.mark_step_executed("step3")

        result = await graph.execute_compensations(
            {},
            failure_strategy=CompensationFailureStrategy.SKIP_DEPENDENTS
        )

        assert result.success is False
        assert "step1" in result.executed  # step1 executed (compensates first)
        assert "step2" in result.failed  # step2 failed (compensates second)
        assert "step3" in result.skipped  # step3 skipped (depends on step2, which failed)


class TestExecuteCompensationsEdgeCases:
    """Tests for edge cases in execute_compensations."""

    @pytest.mark.asyncio
    async def test_empty_graph(self):
        """Test executing compensations on empty graph."""
        graph = SagaExecutionGraph()

        result = await graph.execute_compensations({})

        assert result.success is True
        assert len(result.executed) == 0
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_no_executed_steps(self):
        """Test when compensations are registered but no steps executed."""
        graph = SagaExecutionGraph()

        async def comp(ctx, comp_results=None):
            pass

        graph.register_compensation("step1", comp)
        # Don't mark as executed

        result = await graph.execute_compensations({})

        assert result.success is True
        assert len(result.executed) == 0

    @pytest.mark.asyncio
    async def test_circular_dependency_returns_error(self):
        """Test circular dependency is caught during execution."""
        graph = SagaExecutionGraph()

        async def comp(ctx, comp_results=None):
            pass

        # Create circular dependency
        graph.register_compensation("step1", comp, depends_on=["step2"])
        graph.register_compensation("step2", comp, depends_on=["step1"])
        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")

        result = await graph.execute_compensations({})

        assert result.success is False
        assert "_graph" in result.errors

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test compensation timeout is respected."""
        graph = SagaExecutionGraph()

        async def slow_comp(ctx, comp_results=None):
            import asyncio
            await asyncio.sleep(10)  # Will timeout

        graph.register_compensation("step1", slow_comp, timeout_seconds=0.1)
        graph.mark_step_executed("step1")

        result = await graph.execute_compensations({})

        assert result.success is False
        assert "step1" in result.failed
        assert isinstance(result.errors["step1"], Exception)


    @pytest.mark.asyncio
    async def test_parallel_execution_in_level(self):
        """Test multiple independent compensations execute in parallel."""
        graph = SagaExecutionGraph()

        import asyncio
        # Barrier(2) ensures both tasks must be active simultaneously to proceed.
        # If execution was sequential, the first task would wait correctly indefinitely
        # (or timeout), preventing the second task from ever starting.
        barrier = asyncio.Barrier(2)

        async def comp1(ctx, comp_results=None):
            await asyncio.wait_for(barrier.wait(), timeout=1.0)
            return {"comp1": "done"}

        async def comp2(ctx, comp_results=None):
            await asyncio.wait_for(barrier.wait(), timeout=1.0)
            return {"comp2": "done"}

        # Both independent, should run in parallel
        graph.register_compensation("step1", comp1)
        graph.register_compensation("step2", comp2)
        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")

        # If parallel: both hit barrier, barrier trips, both finish successfully.
        # If sequential: comp1 waits, times out (after 1s). comp2 runs, times out.
        # So we expect success and fast execution.

        # We wrap in wait_for to fail fast if it hangs (though barrier timeout handles it too)
        result = await asyncio.wait_for(graph.execute_compensations({}), timeout=2.0)

        assert result.success is True
        assert "step1" in result.executed
        assert "step2" in result.executed

    @pytest.mark.asyncio
    async def test_execution_time_tracking(self):
        """Test execution time is tracked correctly."""
        graph = SagaExecutionGraph()

        async def comp(ctx, comp_results=None):
            import asyncio
            await asyncio.sleep(0.05)

        graph.register_compensation("step1", comp)
        graph.mark_step_executed("step1")

        result = await graph.execute_compensations({})

        assert result.success is True
        assert result.execution_time_ms > 0
        assert result.execution_time_ms >= 50  # At least 50ms
