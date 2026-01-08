"""
Tests for saga state machine functionality

Tests the state machine logic that manages saga and step lifecycle transitions.
"""

import pytest
from statemachine.exceptions import TransitionNotAllowed

from sagaz.core import Saga
from sagaz.state_machine import (
    SagaStepStateMachine,
    get_valid_next_states,
    validate_state_transition,
)


class TestSagaStateMachine:
    """Tests for SagaStateMachine - tested through Saga integration"""

    @pytest.mark.asyncio
    async def test_state_machine_through_saga_execution(self):
        """Test state machine transitions during saga execution"""
        saga = Saga("StateMachineTest")

        # Initial state - status is an Enum with lowercase values
        assert saga.status.value == "pending"

        # Add step
        async def step_action(ctx):
            return "success"

        await saga.add_step("step1", step_action)

        # Execute saga
        await saga.execute()

        # Final state
        assert saga.status.value == "completed"

    @pytest.mark.asyncio
    async def test_state_machine_compensation_flow(self):
        """Test state machine during compensation"""
        saga = Saga("CompensationTest")

        async def step1(ctx):
            return "step1_result"

        async def comp1(result, ctx):
            pass

        async def step2(ctx):
            msg = "Step 2 failed"
            raise ValueError(msg)

        async def comp2(result, ctx):
            pass

        await saga.add_step("step1", step1, comp1)
        await saga.add_step("step2", step2, comp2)

        # Execute - should compensate
        result = await saga.execute()

        # Should be rolled back - status is an Enum with lowercase values
        assert saga.status.value == "rolled_back"
        assert not result.success


class TestSagaStepStateMachine:
    """Tests for SagaStepStateMachine"""

    @pytest.mark.asyncio
    async def test_initial_state(self):
        """Test step state machine starts in pending state"""
        sm = SagaStepStateMachine("test_step")
        await sm.activate_initial_state()

        assert sm.current_state == sm.pending
        assert sm.current_state.id == "pending"
        assert sm.step_name == "test_step"

    @pytest.mark.asyncio
    async def test_start_transition(self):
        """Test transition from pending to executing"""
        sm = SagaStepStateMachine("test_step")
        await sm.activate_initial_state()

        await sm.start()
        assert sm.current_state == sm.executing

    @pytest.mark.asyncio
    async def test_succeed_transition(self):
        """Test transition from executing to completed"""
        sm = SagaStepStateMachine("test_step")
        await sm.activate_initial_state()

        await sm.start()
        await sm.succeed()
        assert sm.current_state == sm.completed

    @pytest.mark.asyncio
    async def test_fail_transition(self):
        """Test transition from executing to failed"""
        sm = SagaStepStateMachine("test_step")
        await sm.activate_initial_state()

        await sm.start()
        await sm.fail()
        assert sm.current_state == sm.failed
        assert sm.current_state.final

    @pytest.mark.asyncio
    async def test_compensate_transition(self):
        """Test transition from completed to compensating"""
        sm = SagaStepStateMachine("test_step")
        await sm.activate_initial_state()

        await sm.start()
        await sm.succeed()
        await sm.compensate()
        assert sm.current_state == sm.compensating

    @pytest.mark.asyncio
    async def test_compensation_success_transition(self):
        """Test transition from compensating to compensated"""
        sm = SagaStepStateMachine("test_step")
        await sm.activate_initial_state()

        await sm.start()
        await sm.succeed()
        await sm.compensate()
        await sm.compensation_success()
        assert sm.current_state == sm.compensated
        assert sm.current_state.final

    @pytest.mark.asyncio
    async def test_compensation_failure_transition(self):
        """Test transition from compensating to failed"""
        sm = SagaStepStateMachine("test_step")
        await sm.activate_initial_state()

        await sm.start()
        await sm.succeed()
        await sm.compensate()
        await sm.compensation_failure()
        assert sm.current_state == sm.failed
        assert sm.current_state.final

    @pytest.mark.asyncio
    async def test_invalid_transition(self):
        """Test invalid state transition raises error"""
        sm = SagaStepStateMachine("test_step")
        await sm.activate_initial_state()

        # Cannot go from pending to compensating
        with pytest.raises(TransitionNotAllowed):
            await sm.compensate()


class TestStateValidation:
    """Tests for state validation functions"""

    def test_validate_state_transition_valid(self):
        """Test validating valid state transitions"""
        assert validate_state_transition("Pending", "Executing") is True
        assert validate_state_transition("Executing", "Completed") is True
        assert validate_state_transition("Executing", "Compensating") is True
        assert validate_state_transition("Executing", "Failed") is True
        assert validate_state_transition("Compensating", "RolledBack") is True
        assert validate_state_transition("Compensating", "Failed") is True

    def test_validate_state_transition_invalid(self):
        """Test validating invalid state transitions"""
        assert validate_state_transition("Pending", "Completed") is False
        assert validate_state_transition("Pending", "Failed") is False
        assert validate_state_transition("Completed", "Executing") is False
        assert validate_state_transition("Failed", "Executing") is False
        assert validate_state_transition("RolledBack", "Executing") is False

    def test_validate_state_transition_final_states(self):
        """Test final states have no valid transitions"""
        assert validate_state_transition("Completed", "Pending") is False
        assert validate_state_transition("Failed", "Pending") is False
        assert validate_state_transition("RolledBack", "Pending") is False

    def test_validate_state_transition_unknown_state(self):
        """Test validation with unknown state returns False"""
        assert validate_state_transition("UnknownState", "Executing") is False

    def test_get_valid_next_states(self):
        """Test getting valid next states"""
        assert get_valid_next_states("Pending") == ["Executing"]
        assert set(get_valid_next_states("Executing")) == {"Completed", "Compensating", "Failed"}
        assert set(get_valid_next_states("Compensating")) == {"RolledBack", "Failed"}
        assert get_valid_next_states("Completed") == []
        assert get_valid_next_states("Failed") == []
        assert get_valid_next_states("RolledBack") == []

    def test_get_valid_next_states_unknown(self):
        """Test getting valid states for unknown state"""
        assert get_valid_next_states("UnknownState") == []
