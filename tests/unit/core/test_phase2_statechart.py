"""
Unit tests for ADR-038 Phase 2: saga-level StateChart.

Covers:
- SagaStateChart — SCXML-compliant saga-level StateChart with compound compensating region
- create_step_state_machine / create_saga_state_machine factories
- SagaConfig.use_step_statechart flag
"""

import pytest

from sagaz.core.config import SagaConfig
from sagaz.core.execution.state_machine import (
    SagaStateChart,
    SagaStateMachine,
    SagaStepStateMachine,
    create_saga_state_machine,
    create_step_state_machine,
)

# ---------------------------------------------------------------------------
# SagaStateChart
# ---------------------------------------------------------------------------


class TestSagaStateChart:
    """Phase 2 saga-level SCXML StateChart with compound compensating region."""

    @pytest.mark.asyncio
    async def test_initial_configuration(self):
        sm = SagaStateChart()
        await sm.activate_initial_state()
        assert list(sm.configuration_values) == ["pending"]

    @pytest.mark.asyncio
    async def test_happy_path(self):
        sm = SagaStateChart()
        await sm.activate_initial_state()
        await sm.start()
        assert "executing" in sm.configuration_values
        await sm.succeed()
        assert list(sm.configuration_values) == ["completed"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_compensation_path(self):
        sm = SagaStateChart()
        await sm.activate_initial_state()
        await sm.start()
        await sm.fail()
        config = list(sm.configuration_values)
        assert "compensating" in config
        assert "active" in config  # HistoryState starts in initial substate
        await sm.advance()
        assert "done" in sm.configuration_values
        await sm.finish_compensation()
        assert list(sm.configuration_values) == ["rolled_back"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_unrecoverable_failure(self):
        sm = SagaStateChart()
        await sm.activate_initial_state()
        await sm.start()
        await sm.fail_unrecoverable()
        assert list(sm.configuration_values) == ["failed"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_compensation_failure(self):
        sm = SagaStateChart()
        await sm.activate_initial_state()
        await sm.start()
        await sm.fail()
        await sm.compensation_failed()
        assert list(sm.configuration_values) == ["failed"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_history_state_restores_substate(self):
        """Compensation advances through active -> done substates via HistoryState."""
        sm = SagaStateChart()
        await sm.activate_initial_state()
        await sm.start()
        await sm.fail()
        assert "active" in sm.configuration_values
        await sm.advance()
        assert "done" in sm.configuration_values
        await sm.finish_compensation()
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_invalid_transition_ignored_by_statechart(self):
        """StateChart silently ignores invalid transitions."""
        sm = SagaStateChart()
        await sm.activate_initial_state()
        await sm.succeed()  # invalid from pending - silently ignored
        assert list(sm.configuration_values) == ["pending"]

    @pytest.mark.asyncio
    async def test_saga_attached(self):
        """Attached saga can be read back from the machine."""

        class FakeSaga:
            steps = ["s1"]
            completed_steps = ["s1"]

        saga = FakeSaga()
        sm = SagaStateChart(saga=saga)
        await sm.activate_initial_state()
        assert sm.saga is saga

    @pytest.mark.asyncio
    async def test_configuration_values_is_scxml_compliant(self):
        """configuration_values reflects all currently active states (SCXML sec 5.1)."""
        sm = SagaStateChart()
        await sm.activate_initial_state()
        await sm.start()
        await sm.fail()
        # Compensating compound state + its initial substate are both active
        active = set(sm.configuration_values)
        assert "compensating" in active
        assert "active" in active


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


class TestCreateStepStateMachineFactory:
    def test_always_returns_step_state_machine(self):
        """Steps always use SagaStepStateMachine; Phase 2 topology is saga-level."""
        sm = create_step_state_machine("step1")
        assert isinstance(sm, SagaStepStateMachine)
        assert sm.step_name == "step1"

    def test_unknown_kwargs_ignored(self):
        """Deprecated use_step_statechart kwarg is accepted but ignored."""
        sm = create_step_state_machine("step1", use_step_statechart=True)
        assert isinstance(sm, SagaStepStateMachine)


class TestCreateSagaStateMachineFactory:
    def test_phase1_by_default(self):
        sm = create_saga_state_machine()
        assert isinstance(sm, SagaStateMachine)

    def test_phase2_when_flag_true(self):
        sm = create_saga_state_machine(use_step_statechart=True)
        assert isinstance(sm, SagaStateChart)

    def test_saga_attached_phase1(self):
        class FakeSaga:
            steps = []
            completed_steps = []

        saga = FakeSaga()
        sm = create_saga_state_machine(saga=saga)
        assert sm.saga is saga

    def test_saga_attached_phase2(self):
        class FakeSaga:
            steps = []
            completed_steps = []

        saga = FakeSaga()
        sm = create_saga_state_machine(saga=saga, use_step_statechart=True)
        assert sm.saga is saga
        assert isinstance(sm, SagaStateChart)

    def test_config_flag_drives_selection(self):
        config_p1 = SagaConfig(use_step_statechart=False)
        config_p2 = SagaConfig(use_step_statechart=True)
        sm_p1 = create_saga_state_machine(use_step_statechart=config_p1.use_step_statechart)
        sm_p2 = create_saga_state_machine(use_step_statechart=config_p2.use_step_statechart)
        assert isinstance(sm_p1, SagaStateMachine)
        assert isinstance(sm_p2, SagaStateChart)


# ---------------------------------------------------------------------------
# SagaConfig.use_step_statechart
# ---------------------------------------------------------------------------


class TestSagaConfigUseStepStatechart:
    def test_default_is_false(self):
        config = SagaConfig()
        assert config.use_step_statechart is False

    def test_can_enable(self):
        config = SagaConfig(use_step_statechart=True)
        assert config.use_step_statechart is True
