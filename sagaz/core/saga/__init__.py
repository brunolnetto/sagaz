"""
Saga Pattern - Distributed Transactions with Compensation (Production-Ready)

Enables multi-step business processes with automatic rollback capability.
Unlike traditional ACID transactions, Sagas use compensating transactions to undo failed steps.

Uses python-statemachine for robust state management with full async support.

Features:
- ✅ Full async/await support with proper state machine integration
- ✅ Idempotent operations with deduplication keys
- ✅ Retry logic with exponential backoff
- ✅ Timeout protection per step
- ✅ Comprehensive error handling with partial compensation recovery
- ✅ Context passing between steps
- ✅ Guard conditions for state transitions
- ✅ Detailed observability and logging
- ✅ Thread-safe execution with locks
- ✅ Saga versioning and migration support

Example - Trade Execution Saga:
    Step 1: Reserve funds         → Compensation: Unreserve funds
    Step 2: Send order to Binance → Compensation: Cancel order
    Step 3: Update position       → Compensation: Revert position
    Step 4: Log trade             → Compensation: Delete trade log

If any step fails, all previous steps are compensated (undone) in reverse order.

State Machine:
    PENDING → EXECUTING → COMPLETED
                     ↘ COMPENSATING → ROLLED_BACK
                     ↘ FAILED (unrecoverable compensation failure)

    Step states:
    PENDING → EXECUTING → COMPLETED
                     ↘ COMPENSATING → COMPENSATED
                     ↘ FAILED (unrecoverable)

Usage:
    saga = TradeSaga()
    await saga.add_step(
        name="reserve_funds",
        action=reserve_funds_action,
        compensation=unreserve_funds_compensation,
        timeout=10.0,
        retry_attempts=3
    )
    result = await saga.execute()  # Returns SagaResult with full details
"""

from statemachine.exceptions import TransitionNotAllowed

from sagaz.core.context import SagaContext
from sagaz.core.exceptions import (
    SagaCompensationError,
    SagaExecutionError,
    SagaStepError,
    SagaTimeoutError,
)
from sagaz.core.execution.state_machine import SagaStateMachine
from sagaz.core.saga._compensation import _SagaCompensationMixin
from sagaz.core.saga._dag import DAGExecutor
from sagaz.core.saga._dag_delegation import _SagaDAGDelegationMixin
from sagaz.core.saga._execution import _SagaExecutionMixin
from sagaz.core.saga._executor import _StepExecutor
from sagaz.core.saga._lifecycle import _SagaLifecycleMixin
from sagaz.core.saga._saga import Saga, logger
from sagaz.core.saga._snapshot import _SagaSnapshotMixin
from sagaz.core.saga._step import SagaStep
from sagaz.core.saga._step_execution import StepExecutor
from sagaz.core.saga._visualization import _SagaVisualizationMixin
from sagaz.core.types import ParallelFailureStrategy, SagaResult, SagaStatus, SagaStepStatus

__all__ = ["Saga", "SagaStep"]
