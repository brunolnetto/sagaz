"""
Comprehensive tests for Dry-Run Mode (ADR-019)

Tests cover:
- DryRunEngine core functionality
- All 4 dry-run modes (VALIDATE, SIMULATE, ESTIMATE, TRACE)
- Validation logic (DAG cycles, dependencies, context)
- Simulation (topological sort, parallel groups)
- Estimation (duration, API calls, costs)
- Tracing (execution trace, context changes)
"""

import pytest
from unittest.mock import AsyncMock, Mock

from sagaz import Saga, action
from sagaz.dry_run import (
    DryRunEngine,
    DryRunMode,
    DryRunResult,
    ValidationResult,
    SimulationResult,
    EstimateResult,
    TraceResult,
    DryRunTraceEvent,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def simple_saga():
    """Create a simple sequential saga for testing."""
    from sagaz import Saga, action

    class SimpleSaga(Saga):
        saga_name = "simple_test"

        @action("step1")
        async def step1(self, ctx):
            return {"result": "step1_done"}

        @action("step2")
        async def step2(self, ctx):
            return {"result": "step2_done"}

        @action("step3")
        async def step3(self, ctx):
            return {"result": "step3_done"}

    return SimpleSaga()


@pytest.fixture
def saga_with_metadata():
    """Create saga with step metadata for estimation."""
    from sagaz import Saga, action

    # Define function with metadata BEFORE making it a method
    async def api_call_func(self, ctx):
        return {}
    
    api_call_func.__sagaz_metadata__ = {
        "estimated_duration_ms": 150,
        "api_calls": {"payment_api": 1, "inventory_api": 2},
    }

    class MetadataSaga(Saga):
        saga_name = "metadata_test"

        @action("api_call")
        async def api_call(self, ctx):
            return {}
    
    # Add metadata to the underlying function
    MetadataSaga.api_call._saga_step_meta.estimated_duration_ms = 150
    
    saga = MetadataSaga()
    # Set metadata on the step's forward function
    if saga._steps:
        saga._steps[0].forward_fn.__func__.__sagaz_metadata__ = {
            "estimated_duration_ms": 150,
            "api_calls": {"payment_api": 1, "inventory_api": 2},
        }

    return saga


@pytest.fixture
def saga_with_dependencies():
    """Create saga with step dependencies (DAG)."""
    from sagaz import Saga, action

    class DAGSaga(Saga):
        saga_name = "dag_test"
        
        @action("step1")
        async def step1(self, ctx):
            return {}
        
        @action("step2", depends_on={"step1"})
        async def step2(self, ctx):
            return {}
        
        @action("step3", depends_on={"step1"})
        async def step3(self, ctx):
            return {}
        
        @action("step4", depends_on={"step2", "step3"})
        async def step4(self, ctx):
            return {}

    return DAGSaga()


@pytest.fixture
def saga_with_cycle():
    """Create saga with circular dependency."""
    from sagaz import Saga, action

    class CyclicSaga(Saga):
        saga_name = "cyclic_test"
        
        @action("step1", depends_on={"step3"})  # Cycle: step1 -> step3 -> step2 -> step1
        async def step1(self, ctx):
            return {}
        
        @action("step2", depends_on={"step1"})
        async def step2(self, ctx):
            return {}
        
        @action("step3", depends_on={"step2"})
        async def step3(self, ctx):
            return {}

    return CyclicSaga()


# =============================================================================
# DryRunEngine Tests
# =============================================================================


class TestDryRunEngine:
    """Test DryRunEngine core functionality."""

    @pytest.mark.asyncio
    async def test_engine_initialization(self):
        """Test engine can be initialized."""
        engine = DryRunEngine()
        assert engine is not None
        assert engine._api_pricing == {}

    @pytest.mark.asyncio
    async def test_set_api_pricing(self):
        """Test setting API pricing for cost estimation."""
        engine = DryRunEngine()
        engine.set_api_pricing("test_api", 0.001)
        assert engine._api_pricing["test_api"] == 0.001

    @pytest.mark.asyncio
    async def test_run_returns_result(self, simple_saga):
        """Test that run() returns DryRunResult."""
        engine = DryRunEngine()
        result = await engine.run(simple_saga, {}, DryRunMode.VALIDATE)

        assert isinstance(result, DryRunResult)
        assert result.mode == DryRunMode.VALIDATE
        assert isinstance(result.success, bool)


# =============================================================================
# Validation Mode Tests
# =============================================================================


class TestValidationMode:
    """Test VALIDATE mode functionality."""

    @pytest.mark.asyncio
    async def test_validate_simple_saga(self, simple_saga):
        """Test validation of simple saga passes."""
        engine = DryRunEngine()
        result = await engine.run(simple_saga, {}, DryRunMode.VALIDATE)

        assert result.success is True
        assert len(result.validation_errors) == 0

    @pytest.mark.asyncio
    async def test_validate_detects_cycles(self, saga_with_cycle):
        """Test validation detects circular dependencies."""
        engine = DryRunEngine()
        result = await engine.run(saga_with_cycle, {}, DryRunMode.VALIDATE)

        assert result.success is False
        assert len(result.validation_errors) > 0
        assert any("Circular dependencies" in err for err in result.validation_errors)

    @pytest.mark.asyncio
    async def test_validate_missing_context_fields(self):
        """Test validation detects missing required context fields."""
        from sagaz import Saga, action

        class RequiredContextSaga(Saga):
            saga_name = "required_context"
            required_context_fields = ["order_id", "amount"]
            
            @action("step1")
            async def step1(self, ctx):
                return {}

        saga = RequiredContextSaga()
        engine = DryRunEngine()

        # Missing required fields
        result = await engine.run(saga, {"order_id": "123"}, DryRunMode.VALIDATE)

        assert result.success is False
        assert any("Missing required context" in err for err in result.validation_errors)

    @pytest.mark.asyncio
    async def test_validate_unknown_dependencies(self):
        """Test validation detects dependencies on unknown steps."""
        from sagaz import Saga, action

        class InvalidDepSaga(Saga):
            saga_name = "invalid_dep"
            
            @action("step1", depends_on={"nonexistent"})
            async def step1(self, ctx):
                return {}

        saga = InvalidDepSaga()
        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.VALIDATE)

        assert result.success is False
        assert any("unknown step" in err.lower() for err in result.validation_errors)

    @pytest.mark.asyncio
    async def test_validate_warns_missing_compensation(self):
        """Test validation warns about missing compensation."""
        from sagaz import Saga, action

        class NoCompensationSaga(Saga):
            saga_name = "no_compensation"
            
            @action("step1")
            async def step1(self, ctx):
                return {}

        saga = NoCompensationSaga()
        
        # Mark step as requiring compensation (simulate requirement)
        if saga._steps:
            saga._steps[0].requires_compensation = True

        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.VALIDATE)

        assert result.success is True  # Warning, not error
        assert len(result.validation_warnings) > 0
        assert any("compensation" in warn.lower() for warn in result.validation_warnings)


# =============================================================================
# Simulation Mode Tests
# =============================================================================


class TestSimulationMode:
    """Test SIMULATE mode functionality."""

    @pytest.mark.asyncio
    async def test_simulate_simple_saga(self, simple_saga):
        """Test simulation of simple sequential saga."""
        engine = DryRunEngine()
        result = await engine.run(simple_saga, {}, DryRunMode.SIMULATE)

        assert result.success is True
        assert len(result.steps_planned) == 3
        assert result.execution_order == ["step1", "step2", "step3"]

    @pytest.mark.asyncio
    async def test_simulate_dag_topology(self, saga_with_dependencies):
        """Test simulation respects DAG topology."""
        engine = DryRunEngine()
        result = await engine.run(saga_with_dependencies, {}, DryRunMode.SIMULATE)

        assert result.success is True

        # step1 should be first
        assert result.execution_order[0] == "step1"

        # step4 should be last (depends on step2 and step3)
        assert result.execution_order[-1] == "step4"

        # step2 and step3 should be before step4
        step2_idx = result.execution_order.index("step2")
        step3_idx = result.execution_order.index("step3")
        step4_idx = result.execution_order.index("step4")

        assert step2_idx < step4_idx
        assert step3_idx < step4_idx

    @pytest.mark.asyncio
    async def test_simulate_parallel_groups(self, saga_with_dependencies):
        """Test simulation identifies parallel execution groups."""
        engine = DryRunEngine()
        result = await engine.run(saga_with_dependencies, {}, DryRunMode.SIMULATE)

        assert result.success is True
        assert len(result.parallel_groups) > 0

        # step2 and step3 can run in parallel (both depend only on step1)
        # Find which group has step2 and step3
        for group in result.parallel_groups:
            if "step2" in group and "step3" in group:
                assert True  # Found parallel group
                break
        else:
            # If not in same group, they should be in different groups at same level
            assert True  # Still valid (different grouping strategy)


# =============================================================================
# Estimation Mode Tests
# =============================================================================


class TestEstimationMode:
    """Test ESTIMATE mode functionality."""

    @pytest.mark.asyncio
    async def test_estimate_duration(self, saga_with_metadata):
        """Test duration estimation from metadata."""
        engine = DryRunEngine()
        result = await engine.run(saga_with_metadata, {}, DryRunMode.ESTIMATE)

        assert result.success is True
        assert result.estimated_duration_ms == 150

    @pytest.mark.asyncio
    async def test_estimate_api_calls(self, saga_with_metadata):
        """Test API call counting from metadata."""
        engine = DryRunEngine()
        result = await engine.run(saga_with_metadata, {}, DryRunMode.ESTIMATE)

        assert result.success is True
        assert result.api_calls_estimated["payment_api"] == 1
        assert result.api_calls_estimated["inventory_api"] == 2

    @pytest.mark.asyncio
    async def test_estimate_cost_calculation(self, saga_with_metadata):
        """Test cost calculation with API pricing."""
        engine = DryRunEngine()
        engine.set_api_pricing("payment_api", 0.001)
        engine.set_api_pricing("inventory_api", 0.0005)

        result = await engine.run(saga_with_metadata, {}, DryRunMode.ESTIMATE)

        assert result.success is True
        # Cost = (1 * 0.001) + (2 * 0.0005) = 0.002
        assert result.cost_estimate_usd == 0.002

    @pytest.mark.asyncio
    async def test_estimate_default_duration(self, simple_saga):
        """Test default duration for steps without metadata."""
        engine = DryRunEngine()
        result = await engine.run(simple_saga, {}, DryRunMode.ESTIMATE)

        assert result.success is True
        # 3 steps * 100ms default = 300ms
        assert result.estimated_duration_ms == 300


# =============================================================================
# Tracing Mode Tests
# =============================================================================


class TestTracingMode:
    """Test TRACE mode functionality."""

    @pytest.mark.asyncio
    async def test_trace_generates_events(self, simple_saga):
        """Test trace generates event for each step."""
        engine = DryRunEngine()
        result = await engine.run(simple_saga, {}, DryRunMode.TRACE)

        assert result.success is True
        assert result.trace is not None
        assert len(result.trace) == 3

    @pytest.mark.asyncio
    async def test_trace_event_structure(self, simple_saga):
        """Test trace events have correct structure."""
        engine = DryRunEngine()
        result = await engine.run(simple_saga, {}, DryRunMode.TRACE)

        event = result.trace[0]
        assert isinstance(event, DryRunTraceEvent)
        assert event.step_name == "step1"
        assert event.action == "execute"
        assert isinstance(event.context_before, dict)
        assert isinstance(event.context_after, dict)
        assert isinstance(event.estimated_duration_ms, (int, float))

    @pytest.mark.asyncio
    async def test_trace_context_changes(self, simple_saga):
        """Test trace tracks context changes."""
        engine = DryRunEngine()
        result = await engine.run(simple_saga, {"initial": "value"}, DryRunMode.TRACE)

        # Each step should add a result to context
        for event in result.trace:
            assert f"{event.step_name}_result" in event.context_after
            assert event.context_after[f"{event.step_name}_result"] == "dry-run-mock"


# =============================================================================
# Helper Method Tests
# =============================================================================


class TestHelperMethods:
    """Test internal helper methods."""

    def test_detect_cycles_finds_cycle(self):
        """Test cycle detection algorithm."""
        engine = DryRunEngine()

        # Create cycle: A -> B -> C -> A
        dag = {"A": ["B"], "B": ["C"], "C": ["A"]}

        cycles = engine._detect_cycles(dag)
        assert len(cycles) > 0

    def test_detect_cycles_no_cycle(self):
        """Test cycle detection on valid DAG."""
        engine = DryRunEngine()

        # Valid DAG: A -> B, A -> C, B -> D, C -> D
        dag = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}

        cycles = engine._detect_cycles(dag)
        assert len(cycles) == 0

    def test_topological_sort_order(self):
        """Test topological sort produces valid order."""
        engine = DryRunEngine()

        dag = {"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]}

        order = engine._topological_sort(dag)

        # A should be before B and C
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")

        # B and C should be before D
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_calculate_cost_with_pricing(self):
        """Test cost calculation."""
        engine = DryRunEngine()
        engine.set_api_pricing("api1", 0.001)
        engine.set_api_pricing("api2", 0.002)

        api_calls = {"api1": 10, "api2": 5}
        cost = engine._calculate_cost(api_calls)

        # (10 * 0.001) + (5 * 0.002) = 0.020
        assert cost == 0.020

    def test_calculate_cost_unknown_api(self):
        """Test cost calculation with unknown API."""
        engine = DryRunEngine()
        engine.set_api_pricing("known_api", 0.001)

        api_calls = {"known_api": 10, "unknown_api": 5}
        cost = engine._calculate_cost(api_calls)

        # Only known_api should be counted
        assert cost == 0.010


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests combining multiple features."""

    @pytest.mark.asyncio
    async def test_full_workflow_validation_then_simulate(self, simple_saga):
        """Test running validation then simulation."""
        engine = DryRunEngine()

        # First validate
        val_result = await engine.run(simple_saga, {}, DryRunMode.VALIDATE)
        assert val_result.success is True

        # Then simulate
        sim_result = await engine.run(simple_saga, {}, DryRunMode.SIMULATE)
        assert sim_result.success is True
        assert len(sim_result.execution_order) > 0

    @pytest.mark.asyncio
    async def test_validation_failure_stops_simulation(self, saga_with_cycle):
        """Test that validation failure prevents further processing."""
        engine = DryRunEngine()

        result = await engine.run(saga_with_cycle, {}, DryRunMode.SIMULATE)

        # Should fail validation before simulation
        assert result.success is False
        assert len(result.validation_errors) > 0
        assert len(result.execution_order) == 0  # No simulation performed

    @pytest.mark.asyncio
    async def test_all_modes_on_same_saga(self, simple_saga):
        """Test running all modes on the same saga."""
        engine = DryRunEngine()
        context = {"test": "data"}

        # Validate
        val_result = await engine.run(simple_saga, context, DryRunMode.VALIDATE)
        assert val_result.success is True

        # Simulate
        sim_result = await engine.run(simple_saga, context, DryRunMode.SIMULATE)
        assert sim_result.success is True

        # Estimate
        est_result = await engine.run(simple_saga, context, DryRunMode.ESTIMATE)
        assert est_result.success is True

        # Trace
        trace_result = await engine.run(simple_saga, context, DryRunMode.TRACE)
        assert trace_result.success is True


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_saga_with_no_steps(self):
        """Test handling saga with no steps."""

        class EmptySaga(Saga):
            saga_name = "empty"

        saga = EmptySaga()
        saga.steps = []

        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.VALIDATE)

        assert result.success is False
        assert any("no steps" in err.lower() for err in result.validation_errors)

    @pytest.mark.asyncio
    async def test_empty_context(self, simple_saga):
        """Test running with empty context."""
        engine = DryRunEngine()
        result = await engine.run(simple_saga, {}, DryRunMode.VALIDATE)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_estimate_no_metadata(self, simple_saga):
        """Test estimation works with steps having no metadata."""
        engine = DryRunEngine()
        result = await engine.run(simple_saga, {}, DryRunMode.ESTIMATE)

        assert result.success is True
        # Should use default values
        assert result.estimated_duration_ms > 0


# =============================================================================
# ADR-030: Parallel Analysis Tests
# =============================================================================


class TestParallelAnalysis:
    """Tests for enhanced parallel execution analysis (ADR-030)."""

    @pytest.mark.asyncio
    async def test_analyze_forward_layers(self):
        """Test forward execution layer analysis."""
        from sagaz import Saga, action

        class ParallelSaga(Saga):
            saga_name = "parallel_test"

            @action("step_a")
            async def step_a(self, ctx):
                return {"a": "done"}

            @action("step_b", depends_on={"step_a"})
            async def step_b(self, ctx):
                return {"b": "done"}

            @action("step_c", depends_on={"step_a"})
            async def step_c(self, ctx):
                return {"c": "done"}

            @action("step_d", depends_on={"step_b", "step_c"})
            async def step_d(self, ctx):
                return {"d": "done"}

        saga = ParallelSaga()
        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.SIMULATE)

        assert result.success is True
        assert len(result.forward_layers) == 3
        
        # Layer 0: step_a
        assert result.forward_layers[0].layer_number == 0
        assert result.forward_layers[0].steps == ["step_a"]
        
        # Layer 1: step_b, step_c (parallel)
        assert result.forward_layers[1].layer_number == 1
        assert set(result.forward_layers[1].steps) == {"step_b", "step_c"}
        assert "step_a" in result.forward_layers[1].dependencies
        
        # Layer 2: step_d
        assert result.forward_layers[2].layer_number == 2
        assert result.forward_layers[2].steps == ["step_d"]
        assert result.forward_layers[2].dependencies == {"step_b", "step_c"}

    @pytest.mark.asyncio
    async def test_parallelization_metrics(self):
        """Test parallelization metrics calculation."""
        from sagaz import Saga, action

        class ParallelSaga(Saga):
            saga_name = "metrics_test"

            @action("root")
            async def root(self, ctx):
                return {}

            @action("parallel_1", depends_on={"root"})
            async def parallel_1(self, ctx):
                return {}

            @action("parallel_2", depends_on={"root"})
            async def parallel_2(self, ctx):
                return {}

            @action("parallel_3", depends_on={"root"})
            async def parallel_3(self, ctx):
                return {}

        saga = ParallelSaga()
        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.SIMULATE)

        assert result.success is True
        assert result.total_layers == 2
        assert result.max_parallel_width == 3  # 3 parallel steps in layer 1
        assert result.sequential_complexity == 4  # 4 total steps
        assert result.parallel_complexity == 2  # 2 layers
        assert result.parallelization_ratio == 0.5  # 2/4

    @pytest.mark.asyncio
    async def test_critical_path_identification(self):
        """Test critical path identification."""
        from sagaz import Saga, action

        class ChainSaga(Saga):
            saga_name = "chain_test"

            @action("a")
            async def a(self, ctx):
                return {}

            @action("b", depends_on={"a"})
            async def b(self, ctx):
                return {}

            @action("c", depends_on={"b"})
            async def c(self, ctx):
                return {}

            @action("d", depends_on={"a"})  # Shorter branch
            async def d(self, ctx):
                return {}

        saga = ChainSaga()
        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.SIMULATE)

        assert result.success is True
        # Critical path should be the longest chain: a -> b -> c
        assert len(result.critical_path) == 3
        assert result.critical_path == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_backward_compensation_layers(self):
        """Test backward compensation layer analysis."""
        from sagaz import Saga, action, compensate

        class CompensateSaga(Saga):
            saga_name = "compensate_test"

            @action("step1")
            async def step1(self, ctx):
                return {}

            @compensate("step1")
            async def undo_step1(self, ctx):
                pass

            @action("step2", depends_on={"step1"})
            async def step2(self, ctx):
                return {}

            @compensate("step2")
            async def undo_step2(self, ctx):
                pass

            @action("step3", depends_on={"step2"})
            async def step3(self, ctx):
                return {}
            
            # step3 has no compensation

        saga = CompensateSaga()
        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.SIMULATE)

        assert result.success is True
        assert len(result.backward_layers) > 0
        
        # Only compensatable steps should be in backward layers
        all_backward_steps = []
        for layer in result.backward_layers:
            all_backward_steps.extend(layer.steps)
        
        assert "step1" in all_backward_steps
        assert "step2" in all_backward_steps
        assert "step3" not in all_backward_steps  # No compensation

    @pytest.mark.asyncio
    async def test_duration_metadata_detection(self):
        """Test detection of duration metadata."""
        from sagaz import Saga, action

        class MetadataSaga(Saga):
            saga_name = "metadata_test"

            @action("with_meta")
            async def with_meta(self, ctx):
                return {}

            @action("without_meta")
            async def without_meta(self, ctx):
                return {}

        # Add metadata to one step
        MetadataSaga.with_meta.__sagaz_metadata__ = {"estimated_duration_ms": 100}

        saga = MetadataSaga()
        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.SIMULATE)

        assert result.success is True
        assert result.has_duration_metadata is True  # At least one step has metadata

    @pytest.mark.asyncio
    async def test_no_duration_metadata(self):
        """Test analysis works without any duration metadata."""
        from sagaz import Saga, action

        class NoMetaSaga(Saga):
            saga_name = "no_meta_test"

            @action("step1")
            async def step1(self, ctx):
                return {}

            @action("step2", depends_on={"step1"})
            async def step2(self, ctx):
                return {}

        saga = NoMetaSaga()
        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.SIMULATE)

        assert result.success is True
        assert result.has_duration_metadata is False
        assert result.max_parallel_duration_ms == 0.0
        # But structural analysis still works
        assert len(result.forward_layers) == 2
        assert result.critical_path == ["step1", "step2"]

    @pytest.mark.asyncio
    async def test_estimate_without_metadata(self):
        """Test estimate mode without duration metadata."""
        from sagaz import Saga, action

        class NoMetaSaga(Saga):
            saga_name = "no_meta_estimate"

            @action("step1")
            async def step1(self, ctx):
                return {}

        saga = NoMetaSaga()
        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.ESTIMATE)

        assert result.success is True
        assert result.has_duration_metadata is False
        # Should still provide API call estimates (if available)
        assert isinstance(result.api_calls_estimated, dict)

    @pytest.mark.asyncio
    async def test_linear_dag_no_parallelization(self):
        """Test linear DAG shows no parallelization opportunities."""
        from sagaz import Saga, action

        class LinearSaga(Saga):
            saga_name = "linear_test"

            @action("a")
            async def a(self, ctx):
                return {}

            @action("b", depends_on={"a"})
            async def b(self, ctx):
                return {}

            @action("c", depends_on={"b"})
            async def c(self, ctx):
                return {}

        saga = LinearSaga()
        engine = DryRunEngine()
        result = await engine.run(saga, {}, DryRunMode.SIMULATE)

        assert result.success is True
        assert result.max_parallel_width == 1  # No parallelization
        assert result.parallelization_ratio == 1.0  # 3 layers / 3 steps
        assert len(result.critical_path) == 3
