"""
Tests for saga state machine functionality

Tests the state machine logic that manages saga and step lifecycle transitions.
"""

import pytest
from statemachine import StateChart
from statemachine.exceptions import TransitionNotAllowed

from sagaz.core.execution.state_machine import (
    SagaStateMachine,
    SagaStepStateMachine,
    get_valid_next_states,
    validate_state_transition,
)
from sagaz.core.saga import Saga


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


class TestStateChartCompatibility:
    """Verify the StateChart migration preserves the legacy runtime contract."""

    @pytest.mark.parametrize(
        "machine_cls",
        [SagaStateMachine, SagaStepStateMachine],
    )
    def test_statechart_inheritance_and_legacy_flags(self, machine_cls):
        assert issubclass(machine_cls, StateChart)
        assert machine_cls.allow_event_without_transition is False
        assert machine_cls.enable_self_transition_entries is False
        assert machine_cls.atomic_configuration_update is True
        assert machine_cls.catch_errors_as_events is False

    @pytest.mark.asyncio
    async def test_saga_current_state_remains_a_state_object(self):
        sm = SagaStateMachine()
        await sm.activate_initial_state()

        assert sm.current_state == sm.pending
        assert sm.current_state.id == "pending"

    @pytest.mark.asyncio
    async def test_invalid_saga_transition_raises(self):
        sm = SagaStateMachine()
        await sm.activate_initial_state()

        with pytest.raises(TransitionNotAllowed):
            await sm.succeed()

    @pytest.mark.asyncio
    async def test_callback_exceptions_propagate(self):
        class FailingSaga:
            steps = [object()]
            completed_steps = []

            async def _on_enter_executing(self):
                msg = "callback failure"
                raise RuntimeError(msg)

        sm = SagaStateMachine(FailingSaga())
        await sm.activate_initial_state()

        with pytest.raises(RuntimeError, match="callback failure"):
            await sm.start()


    @pytest.mark.asyncio
    async def test_start_guard_rejects_saga_without_steps(self):
        class EmptySaga:
            steps = []
            completed_steps = []

        machine = SagaStateMachine(EmptySaga())
        await machine.activate_initial_state()
        initial_configuration = tuple(machine.configuration_values)

        with pytest.raises(TransitionNotAllowed):
            await machine.start()

        assert machine.current_state == machine.pending
        assert tuple(machine.configuration_values) == initial_configuration

    @pytest.mark.asyncio
    async def test_fail_guard_rejects_saga_without_completed_steps(self):
        class SagaWithoutCompletedSteps:
            steps = [object()]
            completed_steps = []

        machine = SagaStateMachine(SagaWithoutCompletedSteps())
        await machine.activate_initial_state()
        await machine.start()
        executing_configuration = tuple(machine.configuration_values)

        with pytest.raises(TransitionNotAllowed):
            await machine.fail()

        assert machine.current_state == machine.executing
        assert tuple(machine.configuration_values) == executing_configuration

    @pytest.mark.asyncio
    async def test_self_transition_skips_entry_and_exit_callbacks(self):
        class SelfTransitionSagaStateMachine(SagaStateMachine):
            repeat = SagaStateMachine.pending.to.itself()

            def __init__(self):
                self.lifecycle_callbacks = []
                super().__init__()

            async def on_enter_pending(self):
                self.lifecycle_callbacks.append("enter")

            async def on_exit_pending(self):
                self.lifecycle_callbacks.append("exit")

        machine = SelfTransitionSagaStateMachine()
        await machine.activate_initial_state()
        machine.lifecycle_callbacks.clear()

        await machine.repeat()

        assert machine.current_state == machine.pending
        assert machine.lifecycle_callbacks == []
        assert list(machine.configuration_values) == ["pending"]

    @pytest.mark.asyncio
    async def test_configuration_remains_atomic_during_transition_callback(self):
        class SagaWithSteps:
            steps = [object()]
            completed_steps = []

        class AtomicObservationSagaStateMachine(SagaStateMachine):
            async def on_start(self):
                self.configuration_during_start = tuple(
                    state.id for state in self.configuration
                )
                self.pending_active_during_start = self.pending.is_active
                self.executing_active_during_start = self.executing.is_active

        machine = AtomicObservationSagaStateMachine(SagaWithSteps())
        await machine.activate_initial_state()
        await machine.start()

        assert machine.configuration_during_start == ("pending",)
        assert machine.pending_active_during_start is True
        assert machine.executing_active_during_start is False
        assert list(machine.configuration_values) == ["executing"]


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


@pytest.mark.asyncio
async def test_saga_state_configuration_tracks_real_statechart_lifecycle():
    """Ensure snapshot configuration follows the real StateChart lifecycle."""
    from sagaz.core.execution.state_machine import SagaStateMachine
    from sagaz.core.saga._snapshot import _SagaSnapshotMixin
    from sagaz.core.types import SagaStatus

    class SagaStub:
        steps = [object()]

    class SnapshotView(_SagaSnapshotMixin):
        def __init__(self, state_machine):
            self._state_machine = state_machine
            self.status = SagaStatus.PENDING

    machine = SagaStateMachine(SagaStub())
    view = SnapshotView(machine)

    def assert_configuration_matches_active_states():
        active_states = list(machine.configuration)
        assert len(active_states) == 1

        values = [str(value) for value in machine.configuration_values]
        assert values
        assert view.state_configuration == values
        return values

    # StateChart requires explicit initial-state activation.
    await machine.activate_initial_state()
    pending_configuration = assert_configuration_matches_active_states()

    # Pending -> Executing (the SagaStub satisfies the has_steps guard).
    await machine.start()
    view.status = SagaStatus.EXECUTING
    executing_configuration = assert_configuration_matches_active_states()
    assert executing_configuration != pending_configuration

    # Executing -> Completed.
    await machine.succeed()
    view.status = SagaStatus.COMPLETED
    completed_configuration = assert_configuration_matches_active_states()
    assert completed_configuration != executing_configuration
    assert completed_configuration != pending_configuration
