"""
Unit tests for ADR-038 Phase 2: compound/parallel step statechart.

Covers:
- SagaStepStatechart — StateChart-based per-step machine (opt-in Phase 2)
- CompensatingSagaStateMachine — saga-level machine with HistoryState in compensating
- create_step_state_machine / create_saga_state_machine factories
- SagaConfig.use_step_statechart flag
"""

import pytest
from statemachine.exceptions import TransitionNotAllowed

from sagaz.core.config import SagaConfig
from sagaz.core.execution.state_machine import (
    CompensatingSagaStateMachine,
    SagaStateMachine,
    SagaStepStatechart,
    SagaStepStateMachine,
    create_saga_state_machine,
    create_step_state_machine,
)

# ---------------------------------------------------------------------------
# SagaStepStatechart
# ---------------------------------------------------------------------------


class TestSagaStepStatechart:
    """Phase 2 per-step StateChart."""

    @pytest.mark.asyncio
    async def test_initial_configuration(self):
        sm = SagaStepStatechart(step_name="reserve_inventory")
        await sm.activate_initial_state()
        assert sm.step_name == "reserve_inventory"
        assert list(sm.configuration_values) == ["pending"]

    @pytest.mark.asyncio
    async def test_happy_path(self):
        sm = SagaStepStatechart()
        await sm.activate_initial_state()
        await sm.start()
        assert list(sm.configuration_values) == ["running"]
        await sm.succeed()
        assert list(sm.configuration_values) == ["completed"]
        assert not sm.is_terminated

    @pytest.mark.asyncio
    async def test_compensation_path(self):
        sm = SagaStepStatechart()
        await sm.activate_initial_state()
        await sm.start()
        await sm.succeed()
        await sm.compensate()
        assert list(sm.configuration_values) == ["compensating"]
        await sm.compensation_success()
        assert list(sm.configuration_values) == ["compensated"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_failure_path(self):
        sm = SagaStepStatechart()
        await sm.activate_initial_state()
        await sm.start()
        await sm.fail()
        assert list(sm.configuration_values) == ["failed"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_compensation_failure(self):
        sm = SagaStepStatechart()
        await sm.activate_initial_state()
        await sm.start()
        await sm.succeed()
        await sm.compensate()
        await sm.compensation_failure()
        assert list(sm.configuration_values) == ["failed"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_invalid_transition_ignored_by_statechart(self):
        """StateChart catches_errors_as_events — invalid transitions stay in same state."""
        sm = SagaStepStatechart()
        await sm.activate_initial_state()
        # succeed from pending is invalid; StateChart silently ignores it
        await sm.succeed()
        assert list(sm.configuration_values) == ["pending"]

    @pytest.mark.asyncio
    async def test_invalid_transition_from_completed_stays_in_completed(self):
        sm = SagaStepStatechart()
        await sm.activate_initial_state()
        await sm.start()
        await sm.succeed()
        await sm.fail()  # invalid from completed
        assert list(sm.configuration_values) == ["completed"]


# ---------------------------------------------------------------------------
# CompensatingSagaStateMachine
# ---------------------------------------------------------------------------


class TestCompensatingSagaStateMachine:
    """Phase 2 saga-level machine with HistoryState in compensating region."""

    @pytest.mark.asyncio
    async def test_initial_configuration(self):
        sm = CompensatingSagaStateMachine()
        await sm.activate_initial_state()
        assert list(sm.configuration_values) == ["pending"]

    @pytest.mark.asyncio
    async def test_happy_path(self):
        sm = CompensatingSagaStateMachine()
        await sm.activate_initial_state()
        await sm.start()
        assert "executing" in sm.configuration_values
        await sm.succeed()
        assert list(sm.configuration_values) == ["completed"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_compensation_path(self):
        sm = CompensatingSagaStateMachine()
        await sm.activate_initial_state()
        await sm.start()
        await sm.fail()
        config = list(sm.configuration_values)
        assert "compensating" in config
        assert "active" in config   # HistoryState starts in initial substate
        await sm.advance()
        assert "done" in sm.configuration_values
        await sm.finish_compensation()
        assert list(sm.configuration_values) == ["rolled_back"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_unrecoverable_failure(self):
        sm = CompensatingSagaStateMachine()
        await sm.activate_initial_state()
        await sm.start()
        await sm.fail_unrecoverable()
        assert list(sm.configuration_values) == ["failed"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_compensation_failure(self):
        sm = CompensatingSagaStateMachine()
        await sm.activate_initial_state()
        await sm.start()
        await sm.fail()
        await sm.compensation_failed()
        assert list(sm.configuration_values) == ["failed"]
        assert sm.is_terminated

    @pytest.mark.asyncio
    async def test_history_state_restores_substate(self):
        """Entering compensating advances through active → done substates."""
        sm = CompensatingSagaStateMachine()
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
        sm = CompensatingSagaStateMachine()
        await sm.activate_initial_state()
        await sm.succeed()  # invalid from pending
        assert list(sm.configuration_values) == ["pending"]


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


class TestCreateStepStateMachineFactory:
    def test_phase1_by_default(self):
        sm = create_step_state_machine("step1")
        assert isinstance(sm, SagaStepStateMachine)
        assert sm.step_name == "step1"

    def test_phase2_when_flag_true(self):
        sm = create_step_state_machine("step1", use_step_statechart=True)
        assert isinstance(sm, SagaStepStatechart)
        assert sm.step_name == "step1"

    def test_phase1_explicit_false(self):
        sm = create_step_state_machine("step1", use_step_statechart=False)
        assert isinstance(sm, SagaStepStateMachine)


class TestCreateSagaStateMachineFactory:
    def test_phase1_by_default(self):
        sm = create_saga_state_machine()
        assert isinstance(sm, SagaStateMachine)

    def test_phase2_when_flag_true(self):
        sm = create_saga_state_machine(use_step_statechart=True)
        assert isinstance(sm, CompensatingSagaStateMachine)

    def test_saga_attached(self):
        class FakeSaga:
            steps = []
            completed_steps = []

        saga = FakeSaga()
        sm = create_saga_state_machine(saga=saga, use_step_statechart=True)
        assert sm.saga is saga


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

    def test_factory_respects_config(self):
        config_p1 = SagaConfig(use_step_statechart=False)
        config_p2 = SagaConfig(use_step_statechart=True)
        sm_p1 = create_step_state_machine("s", use_step_statechart=config_p1.use_step_statechart)
        sm_p2 = create_step_state_machine("s", use_step_statechart=config_p2.use_step_statechart)
        assert isinstance(sm_p1, SagaStepStateMachine)
        assert isinstance(sm_p2, SagaStepStatechart)
