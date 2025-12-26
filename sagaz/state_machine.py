"""
Saga State Machine - Handles saga lifecycle state transitions

This module contains the state machine logic for saga execution,
providing robust state management with proper async support using python-statemachine.

State Diagram:
    PENDING → EXECUTING → COMPLETED
                     ↘ COMPENSATING → ROLLED_BACK
                     ↘ FAILED (unrecoverable)

Step State Diagram:
    PENDING → EXECUTING → COMPLETED
                     ↘ COMPENSATING → COMPENSATED
                     ↘ FAILED (unrecoverable)

Usage:
    >>> from sagaz.state_machine import SagaStateMachine
    >>>
    >>> class OrderSaga:
    ...     steps = [step1, step2]
    ...     completed_steps = []
    >>>
    >>> saga = OrderSaga()
    >>> sm = SagaStateMachine(saga)
    >>> await sm.activate_initial_state()
    >>> await sm.start()  # Transitions pending -> executing
"""

from typing import TYPE_CHECKING, Optional

from statemachine import State, StateMachine
from statemachine.exceptions import TransitionNotAllowed

if TYPE_CHECKING:
    from sagaz.core import Saga


class SagaStateMachine(StateMachine):
    """
    State machine for managing saga lifecycle transitions.

    Provides state management with guards and hooks for saga execution.
    Supports async callbacks via python-statemachine's native async support.

    States:
        pending: Initial state, saga not yet started
        executing: Saga is running steps
        completed: All steps completed successfully (final)
        compensating: Running compensation for failed steps
        rolled_back: All compensations completed (final)
        failed: Unrecoverable failure (final)

    Events:
        start: Begin saga execution (pending -> executing)
        succeed: Saga completed successfully (executing -> completed)
        fail: Saga failed, begin compensation (executing -> compensating)
        fail_unrecoverable: Unrecoverable failure (executing -> failed)
        finish_compensation: Compensation completed (compensating -> rolled_back)
        compensation_failed: Compensation failed (compensating -> failed)

    Usage:
        >>> sm = SagaStateMachine(saga_instance)
        >>> await sm.activate_initial_state()
        >>>
        >>> # Start execution
        >>> await sm.start()
        >>>
        >>> # On success
        >>> await sm.succeed()
        >>>
        >>> # On failure with compensation
        >>> await sm.fail()
        >>> await sm.finish_compensation()
    """

    # Define saga states
    pending = State("Pending", initial=True)
    executing = State("Executing")
    completed = State("Completed", final=True)
    compensating = State("Compensating")
    rolled_back = State("RolledBack", final=True)
    failed = State("Failed", final=True)

    # Define state transitions with conditions
    # Note: cond is a string method name that returns bool
    start = pending.to(executing, cond="has_steps")
    succeed = executing.to(completed)
    fail = executing.to(compensating, cond="has_completed_steps")
    fail_unrecoverable = executing.to(failed)
    finish_compensation = compensating.to(rolled_back)
    compensation_failed = compensating.to(failed)

    def __init__(self, saga: Optional["Saga"] = None, **kwargs):
        """
        Initialize the saga state machine.

        Args:
            saga: The saga instance to manage state for
            **kwargs: Additional kwargs passed to StateMachine
        """
        self.saga = saga
        super().__init__(**kwargs)

    # Guard conditions - these are sync methods that return bool
    def has_steps(self) -> bool:
        """Guard: can only start if we have steps defined."""
        if self.saga is None:
            return True
        return len(getattr(self.saga, "steps", [])) > 0

    def has_completed_steps(self) -> bool:
        """Guard: can only compensate if we have completed steps to undo."""
        if self.saga is None:
            return True
        return len(getattr(self.saga, "completed_steps", [])) > 0

    # State entry callbacks - using naming convention on_enter_<state_id>
    # These can be async when the SM is used in async context

    async def on_enter_executing(self) -> None:
        """Called when entering EXECUTING state - start saga execution."""
        if self.saga and hasattr(self.saga, "_on_enter_executing"):
            await self.saga._on_enter_executing()

    async def on_enter_compensating(self) -> None:
        """Called when entering COMPENSATING state - start compensation."""
        if self.saga and hasattr(self.saga, "_on_enter_compensating"):
            await self.saga._on_enter_compensating()

    async def on_enter_completed(self) -> None:
        """Called when entering COMPLETED state - saga succeeded."""
        if self.saga and hasattr(self.saga, "_on_enter_completed"):
            await self.saga._on_enter_completed()

    async def on_enter_rolled_back(self) -> None:
        """Called when entering ROLLED_BACK state - saga compensated successfully."""
        if self.saga and hasattr(self.saga, "_on_enter_rolled_back"):
            await self.saga._on_enter_rolled_back()

    async def on_enter_failed(self) -> None:
        """Called when entering FAILED state - unrecoverable failure."""
        if self.saga and hasattr(self.saga, "_on_enter_failed"):
            await self.saga._on_enter_failed()

    # State exit callbacks
    async def on_exit_pending(self) -> None:
        """Called when leaving PENDING state."""
        if self.saga and hasattr(self.saga, "_on_exit_pending"):
            await self.saga._on_exit_pending()

    async def on_exit_executing(self) -> None:
        """Called when leaving EXECUTING state."""
        if self.saga and hasattr(self.saga, "_on_exit_executing"):
            await self.saga._on_exit_executing()

    # Transition callbacks - using naming convention on_<event>
    async def on_start(self) -> None:
        """Called when start transition is triggered."""
        # Override in subclass if needed

    async def on_succeed(self) -> None:
        """Called when succeed transition is triggered."""
        # Override in subclass if needed

    async def on_fail(self) -> None:
        """Called when fail transition is triggered."""
        # Override in subclass if needed


class SagaStepStateMachine(StateMachine):
    """
    State machine for individual saga step execution.

    Manages the lifecycle of a single step within a saga.

    States:
        pending: Step not yet started
        executing: Step is running
        completed: Step finished successfully (can still compensate)
        compensating: Running compensation for this step
        compensated: Compensation completed (final)
        failed: Step failed (final)

    Events:
        start: Begin step execution
        succeed: Step completed successfully
        fail: Step failed
        compensate: Begin compensation
        compensation_success: Compensation succeeded
        compensation_failure: Compensation failed
    """

    # Define step states
    pending = State("Pending", initial=True)
    executing = State("Executing")
    completed = State("Completed")  # NOT final - can transition to compensating
    compensating = State("Compensating")
    compensated = State("Compensated", final=True)
    failed = State("Failed", final=True)

    # Define transitions
    start = pending.to(executing)
    succeed = executing.to(completed)
    fail = executing.to(failed)
    compensate = completed.to(compensating)
    compensation_success = compensating.to(compensated)
    compensation_failure = compensating.to(failed)

    def __init__(self, step_name: str = "", **kwargs):
        """
        Initialize the step state machine.

        Args:
            step_name: Name of the step for logging
            **kwargs: Additional kwargs passed to StateMachine
        """
        self.step_name = step_name
        super().__init__(**kwargs)

    # State entry callbacks
    async def on_enter_executing(self) -> None:
        """Called when step starts executing."""
        # Override in saga implementation if needed

    async def on_enter_completed(self) -> None:
        """Called when step completes successfully."""
        # Override in saga implementation if needed

    async def on_enter_compensating(self) -> None:
        """Called when step starts compensation."""
        # Override in saga implementation if needed

    async def on_enter_compensated(self) -> None:
        """Called when step compensation completes."""
        # Override in saga implementation if needed

    async def on_enter_failed(self) -> None:
        """Called when step fails."""
        # Override in saga implementation if needed


def validate_state_transition(current_state: str, target_state: str) -> bool:
    """
    Validate if a state transition is allowed.

    Args:
        current_state: Current state name
        target_state: Target state name

    Returns:
        True if transition is valid, False otherwise
    """
    valid_transitions = {
        "Pending": ["Executing"],
        "Executing": ["Completed", "Compensating", "Failed"],
        "Compensating": ["RolledBack", "Failed"],
        "Completed": [],  # Final state
        "RolledBack": [],  # Final state
        "Failed": [],  # Final state
    }

    return target_state in valid_transitions.get(current_state, [])


def get_valid_next_states(current_state: str) -> list[str]:
    """
    Get list of valid next states from current state.

    Args:
        current_state: Current state name

    Returns:
        List of valid next state names
    """
    valid_transitions = {
        "Pending": ["Executing"],
        "Executing": ["Completed", "Compensating", "Failed"],
        "Compensating": ["RolledBack", "Failed"],
        "Completed": [],
        "RolledBack": [],
        "Failed": [],
    }

    return valid_transitions.get(current_state, [])


# Re-export TransitionNotAllowed for convenience
__all__ = [
    "SagaStateMachine",
    "SagaStepStateMachine",
    "TransitionNotAllowed",
    "get_valid_next_states",
    "validate_state_transition",
]
