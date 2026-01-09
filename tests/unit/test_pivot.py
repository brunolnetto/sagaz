"""
Tests for Pivot/Irreversible Steps (ADR-023).

This module tests the pivot functionality including:
- Core types (RecoveryAction, StepZone, SagaZones)
- TaintPropagator algorithm
- pivot parameter in add_step() and @action decorator
- forward_recovery decorator
- Compensation behavior with pivots
"""

import pytest

from sagaz import (
    PivotInfo,
    RecoveryAction,
    SagaResult,
    SagaStatus,
    SagaStepStatus,
    SagaZones,
    StepZone,
    TaintPropagator,
)
from sagaz.core.saga import SagaStep
from sagaz.core.decorators import (
    ForwardRecoveryMetadata,
    SagaStepDefinition,
    StepMetadata,
)


class TestRecoveryAction:
    """Tests for RecoveryAction enum."""

    def test_all_values_exist(self):
        """Test that all expected recovery actions exist."""
        assert RecoveryAction.RETRY.value == "retry"
        assert RecoveryAction.RETRY_WITH_ALTERNATE.value == "retry_alt"
        assert RecoveryAction.SKIP.value == "skip"
        assert RecoveryAction.MANUAL_INTERVENTION.value == "manual"
        assert RecoveryAction.COMPENSATE_PIVOT.value == "compensate"

    def test_enum_count(self):
        """Test that we have exactly 5 recovery actions."""
        assert len(RecoveryAction) == 5


class TestStepZone:
    """Tests for StepZone enum."""

    def test_all_values_exist(self):
        """Test that all expected zones exist."""
        assert StepZone.REVERSIBLE.value == "reversible"
        assert StepZone.PIVOT.value == "pivot"
        assert StepZone.COMMITTED.value == "committed"
        assert StepZone.TAINTED.value == "tainted"

    def test_enum_count(self):
        """Test that we have exactly 4 zones."""
        assert len(StepZone) == 4


class TestSagaZones:
    """Tests for SagaZones dataclass."""

    def test_empty_zones(self):
        """Test that empty zones work correctly."""
        zones = SagaZones()
        assert zones.reversible == set()
        assert zones.pivots == set()
        assert zones.committed == set()
        assert zones.tainted == set()

    def test_get_zone_reversible(self):
        """Test getting zone for reversible step."""
        zones = SagaZones(reversible={"step1", "step2"})
        assert zones.get_zone("step1") == StepZone.REVERSIBLE
        assert zones.get_zone("step2") == StepZone.REVERSIBLE

    def test_get_zone_pivot(self):
        """Test getting zone for pivot step."""
        zones = SagaZones(pivots={"charge_payment"})
        assert zones.get_zone("charge_payment") == StepZone.PIVOT

    def test_get_zone_committed(self):
        """Test getting zone for committed step."""
        zones = SagaZones(committed={"ship_order", "notify"})
        assert zones.get_zone("ship_order") == StepZone.COMMITTED
        assert zones.get_zone("notify") == StepZone.COMMITTED

    def test_get_zone_tainted(self):
        """Test getting zone for tainted step."""
        zones = SagaZones(tainted={"reserve_funds"})
        assert zones.get_zone("reserve_funds") == StepZone.TAINTED

    def test_get_zone_unknown_returns_reversible(self):
        """Test that unknown steps default to reversible."""
        zones = SagaZones()
        assert zones.get_zone("unknown_step") == StepZone.REVERSIBLE

    def test_is_rollback_allowed(self):
        """Test rollback allowed logic."""
        zones = SagaZones(
            reversible={"step1"},
            pivots={"pivot_step"},
            committed={"step2"},
            tainted={"step3"},
        )
        assert zones.is_rollback_allowed("step1") is True
        assert zones.is_rollback_allowed("step2") is True  # Committed can compensate backward to pivot
        assert zones.is_rollback_allowed("pivot_step") is False
        assert zones.is_rollback_allowed("step3") is False

    def test_get_effective_pivot(self):
        """Test finding effective pivot for committed step."""
        zones = SagaZones(
            pivots={"pivot1"},
            committed={"step_after_pivot"}
        )
        # Should return pivot associated with committed step (simplified logic returns first pivot)
        assert zones.get_rollback_boundary("step_after_pivot") == "pivot1"
        assert zones.get_rollback_boundary("unknown") is None



class TestTaintPropagator:
    """Tests for TaintPropagator class."""

    def test_get_ancestors_simple(self):
        """Test getting ancestors of a step."""
        # step1 -> step2 -> step3
        dependencies = {
            "step1": set(),
            "step2": {"step1"},
            "step3": {"step2"},
        }
        propagator = TaintPropagator(
            step_names={"step1", "step2", "step3"},
            dependencies=dependencies,
            pivots=set(),
        )

        assert propagator.get_ancestors("step1") == set()
        assert propagator.get_ancestors("step2") == {"step1"}
        assert propagator.get_ancestors("step3") == {"step1", "step2"}

    def test_get_ancestors_diamond(self):
        """Test getting ancestors with diamond dependency."""
        #      step1
        #     /     \
        #  step2   step3
        #     \     /
        #      step4
        dependencies = {
            "step1": set(),
            "step2": {"step1"},
            "step3": {"step1"},
            "step4": {"step2", "step3"},
        }
        propagator = TaintPropagator(
            step_names={"step1", "step2", "step3", "step4"},
            dependencies=dependencies,
            pivots=set(),
        )

        assert propagator.get_ancestors("step4") == {"step1", "step2", "step3"}

    def test_get_descendants_simple(self):
        """Test getting descendants of a step."""
        dependencies = {
            "step1": set(),
            "step2": {"step1"},
            "step3": {"step2"},
        }
        propagator = TaintPropagator(
            step_names={"step1", "step2", "step3"},
            dependencies=dependencies,
            pivots=set(),
        )

        assert propagator.get_descendants("step3") == set()
        assert propagator.get_descendants("step2") == {"step3"}
        assert propagator.get_descendants("step1") == {"step2", "step3"}

    def test_propagate_taint(self):
        """Test taint propagation from completed pivot."""
        # reserve -> charge (PIVOT) -> ship
        dependencies = {
            "reserve": set(),
            "charge": {"reserve"},
            "ship": {"charge"},
        }
        propagator = TaintPropagator(
            step_names={"reserve", "charge", "ship"},
            dependencies=dependencies,
            pivots={"charge"},
        )

        # Before propagation
        assert not propagator.is_tainted("reserve")

        # Propagate taint from charge pivot
        newly_tainted = propagator.propagate_taint("charge")

        # After propagation
        assert newly_tainted == {"reserve"}
        assert propagator.is_tainted("reserve")
        assert not propagator.is_tainted("ship")

    def test_calculate_zones(self):
        """Test zone calculation."""
        # reserve -> charge (PIVOT) -> ship -> notify
        dependencies = {
            "reserve": set(),
            "charge": {"reserve"},
            "ship": {"charge"},
            "notify": {"ship"},
        }
        propagator = TaintPropagator(
            step_names={"reserve", "charge", "ship", "notify"},
            dependencies=dependencies,
            pivots={"charge"},
            completed_pivots={"charge"},  # Pivot completed
        )

        zones = propagator.calculate_zones()

        # Verify zones
        assert zones.pivots == {"charge"}
        assert zones.tainted == {"reserve"}
        assert "ship" in zones.committed
        assert "notify" in zones.committed

    def test_get_rollback_boundary(self):
        """Test getting rollback boundary for failed step."""
        dependencies = {
            "reserve": set(),
            "charge": {"reserve"},
            "ship": {"charge"},
        }
        propagator = TaintPropagator(
            step_names={"reserve", "charge", "ship"},
            dependencies=dependencies,
            pivots={"charge"},
            completed_pivots={"charge"},
        )

        # Step after pivot - boundary is the pivot
        assert propagator.get_rollback_boundary("ship") == "charge"

        # Step before pivot - no boundary (haven't committed anything)
        propagator2 = TaintPropagator(
            step_names={"reserve", "charge", "ship"},
            dependencies=dependencies,
            pivots={"charge"},
            completed_pivots=set(),  # Pivot NOT completed
        )
        assert propagator2.get_rollback_boundary("reserve") is None

    def test_can_compensate(self):
        """Test can_compensate checks."""
        dependencies = {
            "reserve": set(),
            "charge": {"reserve"},
            "ship": {"charge"},
        }
        propagator = TaintPropagator(
            step_names={"reserve", "charge", "ship"},
            dependencies=dependencies,
            pivots={"charge"},
            completed_pivots={"charge"},
        )

        # Propagate taint
        propagator.propagate_taint("charge")

        # Tainted step cannot be compensated
        assert not propagator.can_compensate("reserve")

        # Non-tainted steps can be compensated
        assert propagator.can_compensate("ship")

    def test_calculate_zones_with_reversible(self):
        """Test that steps before pivot are marked reversible."""
        dependencies = {"pre_step": set(), "pivot": {"pre_step"}}
        propagator = TaintPropagator(
            step_names={"pre_step", "pivot"},
            dependencies=dependencies,
            pivots={"pivot"},
            completed_pivots=set()
        )
        zones = propagator.calculate_zones()
        assert "pre_step" in zones.reversible
        assert "pivot" not in zones.reversible



class TestSagaStepPivot:
    """Tests for SagaStep pivot support."""

    def test_pivot_default_false(self):
        """Test that pivot defaults to False."""
        step = SagaStep(name="test", action=lambda x: x)
        assert step.pivot is False
        assert step.tainted is False

    def test_pivot_can_be_set(self):
        """Test that pivot can be set to True."""
        step = SagaStep(name="charge", action=lambda x: x, pivot=True)
        assert step.pivot is True

    def test_can_compensate_not_tainted(self):
        """Test can_compensate when not tainted."""
        step = SagaStep(name="test", action=lambda x: x, compensation=lambda x: x)
        assert step.can_compensate() is True

    def test_can_compensate_tainted(self):
        """Test can_compensate when tainted."""
        step = SagaStep(name="test", action=lambda x: x, compensation=lambda x: x)
        step.mark_tainted()
        assert step.can_compensate() is False
        assert step.status == SagaStepStatus.TAINTED

    def test_can_compensate_no_compensation(self):
        """Test can_compensate without compensation function."""
        step = SagaStep(name="test", action=lambda x: x, compensation=None)
        assert step.can_compensate() is False


class TestStepMetadataPivot:
    """Tests for StepMetadata pivot support."""

    def test_pivot_default_false(self):
        """Test that pivot defaults to False."""
        meta = StepMetadata(name="test")
        assert meta.pivot is False

    def test_pivot_can_be_set(self):
        """Test that pivot can be set."""
        meta = StepMetadata(name="charge", pivot=True)
        assert meta.pivot is True


class TestSagaStepDefinitionPivot:
    """Tests for SagaStepDefinition pivot support."""

    def test_pivot_default_false(self):
        """Test that pivot defaults to False."""
        step_def = SagaStepDefinition(
            step_id="test",
            forward_fn=lambda x: x,
        )
        assert step_def.pivot is False

    def test_pivot_can_be_set(self):
        """Test that pivot can be set."""
        step_def = SagaStepDefinition(
            step_id="charge",
            forward_fn=lambda x: x,
            pivot=True,
        )
        assert step_def.pivot is True


class TestForwardRecoveryMetadata:
    """Tests for ForwardRecoveryMetadata."""

    def test_required_fields(self):
        """Test required fields."""
        meta = ForwardRecoveryMetadata(for_step="ship_order")
        assert meta.for_step == "ship_order"

    def test_default_values(self):
        """Test default values."""
        meta = ForwardRecoveryMetadata(for_step="ship_order")
        assert meta.max_retries == 3
        assert meta.timeout_seconds == 30.0

    def test_custom_values(self):
        """Test custom values."""
        meta = ForwardRecoveryMetadata(
            for_step="ship_order",
            max_retries=5,
            timeout_seconds=60.0,
        )
        assert meta.max_retries == 5
        assert meta.timeout_seconds == 60.0


class TestSagaResultPivot:
    """Tests for SagaResult pivot fields."""

    def test_default_values(self):
        """Test that pivot fields default correctly."""
        result = SagaResult(
            success=True,
            saga_name="test",
            status=SagaStatus.COMPLETED,
            completed_steps=3,
            total_steps=3,
        )
        assert result.pivot_reached is False
        assert result.committed_step_names == []
        assert result.tainted_step_names == []
        assert result.forward_recovery_needed is False
        assert result.rollback_boundary is None

    def test_pivot_fields_can_be_set(self):
        """Test that pivot fields can be set."""
        result = SagaResult(
            success=False,
            saga_name="test",
            status=SagaStatus.PARTIALLY_COMMITTED,
            completed_steps=2,
            total_steps=3,
            pivot_reached=True,
            committed_step_names=["charge_payment"],
            tainted_step_names=["reserve_funds"],
            forward_recovery_needed=True,
            rollback_boundary="charge_payment",
        )
        assert result.pivot_reached is True
        assert result.committed_step_names == ["charge_payment"]
        assert result.tainted_step_names == ["reserve_funds"]
        assert result.forward_recovery_needed is True
        assert result.rollback_boundary == "charge_payment"

    def test_is_partially_committed(self):
        """Test is_partially_committed property."""
        result = SagaResult(
            success=False,
            saga_name="test",
            status=SagaStatus.PARTIALLY_COMMITTED,
            completed_steps=2,
            total_steps=3,
        )
        assert result.is_partially_committed is True

    def test_needs_intervention(self):
        """Test needs_intervention property."""
        result1 = SagaResult(
            success=False,
            saga_name="test",
            status=SagaStatus.FORWARD_RECOVERY,
            completed_steps=2,
            total_steps=3,
        )
        assert result1.needs_intervention is True

        result2 = SagaResult(
            success=False,
            saga_name="test",
            status=SagaStatus.FAILED,
            completed_steps=2,
            total_steps=3,
            forward_recovery_needed=True,
        )
        assert result2.needs_intervention is True


class TestNewSagaStatuses:
    """Tests for new SagaStatus values."""

    def test_partially_committed_exists(self):
        """Test PARTIALLY_COMMITTED status exists."""
        assert SagaStatus.PARTIALLY_COMMITTED.value == "partially_committed"

    def test_forward_recovery_exists(self):
        """Test FORWARD_RECOVERY status exists."""
        assert SagaStatus.FORWARD_RECOVERY.value == "forward_recovery"


class TestNewSagaStepStatuses:
    """Tests for new SagaStepStatus values."""

    def test_tainted_exists(self):
        """Test TAINTED status exists."""
        assert SagaStepStatus.TAINTED.value == "tainted"

    def test_skipped_exists(self):
        """Test SKIPPED status exists."""
        assert SagaStepStatus.SKIPPED.value == "skipped"


# =============================================================================
# Integration Tests - Full Saga Execution with Pivots
# =============================================================================

class TestPivotSagaIntegration:
    """Integration tests for pivot behavior in declarative sagas."""

    @pytest.mark.asyncio
    async def test_pivot_step_taints_ancestors(self):
        """Test that pivot step completion taints ancestors."""
        from sagaz import Saga, action, compensate

        compensation_calls = []

        class PaymentSaga(Saga):
            saga_name = "payment"

            @action("reserve_funds")
            async def reserve(self, ctx):
                return {"reservation_id": "RES-123"}

            @compensate("reserve_funds")
            async def unreserve(self, ctx):
                compensation_calls.append("reserve_funds")

            @action("charge_payment", depends_on=["reserve_funds"], pivot=True)
            async def charge(self, ctx):
                return {"charge_id": "CHG-456"}

            @compensate("charge_payment")
            async def refund(self, ctx):
                compensation_calls.append("charge_payment")

            @action("ship_order", depends_on=["charge_payment"])
            async def ship(self, ctx):
                # This will fail
                msg = "Shipping failed!"
                raise ValueError(msg)

            @compensate("ship_order")
            async def cancel_ship(self, ctx):
                compensation_calls.append("ship_order")

        saga = PaymentSaga()

        # Verify pivot step is detected
        assert saga.get_pivot_steps() == ["charge_payment"]

        # Run the saga (it will fail at ship_order)
        with pytest.raises(ValueError, match="Shipping failed!"):
            await saga.run({"amount": 100})

        # Verify pivot was reached
        assert saga._pivot_reached is True

        # Verify ancestors were tainted
        assert "reserve_funds" in saga._tainted_steps

        # Verify compensation behavior:
        # - ship_order: never completed, so nothing to compensate
        # - charge_payment: pivot step, compensation skipped
        # - reserve_funds: tainted ancestor, compensation skipped
        # With pivots, compensation stops at the pivot boundary!
        assert "ship_order" not in compensation_calls  # Never completed
        assert "charge_payment" not in compensation_calls  # Pivot step - skipped
        assert "reserve_funds" not in compensation_calls  # Tainted - skipped


    @pytest.mark.asyncio
    async def test_forward_recovery_handler_collection(self):
        """Test that forward recovery handlers are collected."""
        from sagaz import Saga, action, forward_recovery
        from sagaz.execution.pivot import RecoveryAction

        class PaymentSaga(Saga):
            saga_name = "payment"

            @action("charge_payment", pivot=True)
            async def charge(self, ctx):
                return {"charge_id": "CHG-456"}

            @action("ship_order", depends_on=["charge_payment"])
            async def ship(self, ctx):
                return {"shipment_id": "SHP-789"}

            @forward_recovery("ship_order")
            async def handle_ship_failure(self, ctx, error):
                return RecoveryAction.RETRY

        saga = PaymentSaga()

        # Verify forward recovery handler was collected
        assert "ship_order" in saga._forward_recovery_handlers
        assert saga._forward_recovery_handlers["ship_order"] == saga.handle_ship_failure

    @pytest.mark.asyncio
    async def test_saga_without_pivot_full_rollback(self):
        """Test that saga without pivots performs full rollback."""
        from sagaz import Saga, action, compensate

        compensation_calls = []

        class SimpleSaga(Saga):
            saga_name = "simple"

            @action("step1")
            async def step1(self, ctx):
                return {"value": 1}

            @compensate("step1")
            async def comp1(self, ctx):
                compensation_calls.append("step1")

            @action("step2", depends_on=["step1"])
            async def step2(self, ctx):
                return {"value": 2}

            @compensate("step2")
            async def comp2(self, ctx):
                compensation_calls.append("step2")

            @action("step3", depends_on=["step2"])
            async def step3(self, ctx):
                msg = "Step 3 failed!"
                raise ValueError(msg)

        saga = SimpleSaga()

        # No pivots
        assert saga.get_pivot_steps() == []

        with pytest.raises(ValueError):
            await saga.run({})

        # All completed steps should be compensated (full rollback)
        assert "step2" in compensation_calls
        assert "step1" in compensation_calls

    @pytest.mark.asyncio
    async def test_pivot_success_no_compensation(self):
        """Test that successful saga with pivots doesn't compensate."""
        from sagaz import Saga, action, compensate

        compensation_calls = []

        class SuccessSaga(Saga):
            saga_name = "success"

            @action("reserve")
            async def reserve(self, ctx):
                return {"reserved": True}

            @compensate("reserve")
            async def unreserve(self, ctx):
                compensation_calls.append("reserve")

            @action("charge", depends_on=["reserve"], pivot=True)
            async def charge(self, ctx):
                return {"charged": True}

            @compensate("charge")
            async def refund(self, ctx):
                compensation_calls.append("charge")

            @action("complete", depends_on=["charge"])
            async def complete(self, ctx):
                return {"completed": True}

        saga = SuccessSaga()
        result = await saga.run({})

        # Saga succeeded
        assert result["completed"] is True

        # No compensations should have been called
        assert compensation_calls == []

        # Pivot was still marked as reached
        assert saga._pivot_reached is True
        assert "reserve" in saga._tainted_steps


class TestImperativeSagaPivot:
    """Tests for pivot support in imperative saga API."""

    @pytest.mark.asyncio
    async def test_add_step_with_pivot(self):
        """Test adding step with pivot=True in imperative API."""
        from sagaz.core.saga import Saga as ImperativeSaga
        from sagaz.core.saga import SagaContext

        async def charge_action(ctx):
            ctx.set("charged", True)
            return {"charge_id": "CHG-123"}

        async def refund_comp(result, ctx):
            pass

        saga = ImperativeSaga(name="test")
        await saga.add_step("charge", charge_action, refund_comp, pivot=True)

        # Verify step was added with pivot flag
        step = saga.steps[0]
        assert step.pivot is True
        assert step.name == "charge"


# =============================================================================
# Mermaid Visualization Tests
# =============================================================================

class TestMermaidPivotVisualization:
    """Tests for Mermaid diagram generation with pivot zones."""

    def test_step_info_pivot_fields(self):
        """Test that StepInfo has pivot and tainted fields."""
        from sagaz.visualization.mermaid import StepInfo

        # Default values
        step = StepInfo(name="test", has_compensation=True)
        assert step.pivot is False
        assert step.tainted is False

        # Custom values
        pivot_step = StepInfo(name="charge", has_compensation=True, pivot=True)
        assert pivot_step.pivot is True

        tainted_step = StepInfo(name="reserve", has_compensation=True, tainted=True)
        assert tainted_step.tainted is True

    def test_mermaid_generator_with_pivot_zones(self):
        """Test that MermaidGenerator applies zone styles when pivots exist."""
        from sagaz.visualization.mermaid import MermaidGenerator, StepInfo

        steps = [
            StepInfo(name="reserve", has_compensation=True),
            StepInfo(name="charge", has_compensation=True, pivot=True, depends_on={"reserve"}),
            StepInfo(name="ship", has_compensation=False, depends_on={"charge"}),
        ]

        generator = MermaidGenerator(steps, show_pivot_zones=True)
        diagram = generator.generate()

        # Should contain pivot zone class definitions
        assert "classDef reversible" in diagram
        assert "classDef pivot" in diagram
        assert "classDef committed" in diagram
        assert "classDef tainted" in diagram

        # Reserve should be reversible (before pivot)
        assert "class reserve reversible" in diagram
        # Charge should be pivot
        assert "class charge pivot" in diagram
        # Ship should be committed (after pivot)
        assert "class ship committed" in diagram

    def test_mermaid_generator_with_tainted_steps(self):
        """Test that tainted steps get the tainted style."""
        from sagaz.visualization.mermaid import MermaidGenerator, StepInfo

        steps = [
            StepInfo(name="reserve", has_compensation=True, tainted=True),
            StepInfo(name="charge", has_compensation=True, pivot=True, depends_on={"reserve"}),
            StepInfo(name="ship", has_compensation=False, depends_on={"charge"}),
        ]

        generator = MermaidGenerator(steps, show_pivot_zones=True)
        diagram = generator.generate()

        # Reserve should be tainted (ancestor of completed pivot)
        assert "class reserve tainted" in diagram

    def test_mermaid_generator_without_pivot_zones(self):
        """Test that zone styles are not applied when show_pivot_zones=False."""
        from sagaz.visualization.mermaid import MermaidGenerator, StepInfo

        steps = [
            StepInfo(name="reserve", has_compensation=True),
            StepInfo(name="charge", has_compensation=True, pivot=True, depends_on={"reserve"}),
        ]

        generator = MermaidGenerator(steps, show_pivot_zones=False)
        diagram = generator.generate()

        # Should NOT contain pivot zone class definitions
        assert "classDef reversible" not in diagram
        assert "classDef pivot" not in diagram

        # Should use default success style
        assert "class reserve,charge success" in diagram

    def test_mermaid_generator_no_pivots(self):
        """Test that zone styles are not applied when no pivots exist."""
        from sagaz.visualization.mermaid import MermaidGenerator, StepInfo

        steps = [
            StepInfo(name="step1", has_compensation=True),
            StepInfo(name="step2", has_compensation=True, depends_on={"step1"}),
        ]

        generator = MermaidGenerator(steps, show_pivot_zones=True)
        diagram = generator.generate()

        # Should NOT contain pivot zone styles (no pivots)
        assert "classDef reversible" not in diagram

        # Should use default success style
        assert "class step1,step2 success" in diagram
