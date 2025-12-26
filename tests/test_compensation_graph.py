"""
Tests for the compensation graph module.
"""

import pytest

from sagaz.compensation_graph import (
    CircularDependencyError,
    CompensationNode,
    CompensationType,
    MissingDependencyError,
    SagaCompensationGraph,
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


class TestSagaCompensationGraph:
    """Tests for SagaCompensationGraph."""

    def test_register_compensation(self):
        """Test registering a compensation."""
        graph = SagaCompensationGraph()

        async def undo_step1(ctx):
            pass

        graph.register_compensation("step1", undo_step1)

        assert "step1" in graph.nodes
        assert graph.nodes["step1"].step_id == "step1"
        assert graph.nodes["step1"].compensation_fn == undo_step1

    def test_register_compensation_with_options(self):
        """Test registering with all options."""
        graph = SagaCompensationGraph()

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
        graph = SagaCompensationGraph()

        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")

        assert graph.executed_steps == ["step1", "step2"]

    def test_mark_step_executed_idempotent(self):
        """Test that marking the same step twice doesn't duplicate."""
        graph = SagaCompensationGraph()

        graph.mark_step_executed("step1")
        graph.mark_step_executed("step1")

        assert graph.executed_steps == ["step1"]

    def test_unmark_step_executed(self):
        """Test unmarking executed steps."""
        graph = SagaCompensationGraph()

        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")
        graph.unmark_step_executed("step1")

        assert graph.executed_steps == ["step2"]

    def test_get_executed_steps(self):
        """Test getting executed steps returns a copy."""
        graph = SagaCompensationGraph()

        graph.mark_step_executed("step1")
        executed = graph.get_executed_steps()

        # Modifying returned list shouldn't affect original
        executed.append("step2")

        assert graph.executed_steps == ["step1"]

    def test_compensation_order_simple(self):
        """Test simple compensation order (reverse of execution)."""
        graph = SagaCompensationGraph()

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
        graph = SagaCompensationGraph()

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
        graph = SagaCompensationGraph()

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
        graph = SagaCompensationGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)

        levels = graph.get_compensation_order()

        assert levels == []

    def test_compensation_order_complex_dag(self):
        """Test complex DAG compensation order."""
        graph = SagaCompensationGraph()

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
        graph = SagaCompensationGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)
        graph.register_compensation("step2", undo, depends_on=["step1"])

        # Should not raise
        graph.validate()

    def test_validate_missing_dependency(self):
        """Test validation fails for missing dependency."""
        graph = SagaCompensationGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step2", undo, depends_on=["nonexistent"])

        with pytest.raises(MissingDependencyError) as exc_info:
            graph.validate()

        assert exc_info.value.step_id == "step2"
        assert exc_info.value.missing_dep == "nonexistent"

    def test_validate_circular_dependency(self):
        """Test validation fails for circular dependency."""
        graph = SagaCompensationGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo, depends_on=["step2"])
        graph.register_compensation("step2", undo, depends_on=["step1"])

        with pytest.raises(CircularDependencyError):
            graph.validate()

    def test_get_compensation_info(self):
        """Test getting compensation info by step ID."""
        graph = SagaCompensationGraph()

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
        graph = SagaCompensationGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)
        graph.mark_step_executed("step1")

        graph.clear()

        assert len(graph.nodes) == 0
        assert len(graph.executed_steps) == 0

    def test_reset_execution(self):
        """Test resetting execution state."""
        graph = SagaCompensationGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)
        graph.mark_step_executed("step1")

        graph.reset_execution()

        assert len(graph.nodes) == 1  # Registration preserved
        assert len(graph.executed_steps) == 0  # Execution cleared

    def test_repr(self):
        """Test string representation."""
        graph = SagaCompensationGraph()

        async def undo(ctx):
            pass

        graph.register_compensation("step1", undo)
        graph.mark_step_executed("step1")

        repr_str = repr(graph)

        assert "SagaCompensationGraph" in repr_str
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
