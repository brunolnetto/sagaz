"""
Metadata dataclasses and decorator functions for saga step definitions.

This module contains the internal building blocks used by the decorator API:
- :class:`StepMetadata` — attached to ``@step``/``@action`` decorated methods
- :class:`CompensationMetadata` — attached to ``@compensate`` decorated methods
- :class:`ForwardRecoveryMetadata` — attached to ``@forward_recovery`` decorated methods
- :func:`step` / ``action`` — decorator to mark a method as a saga step
- :func:`compensate` — decorator to mark a method as a compensation
- :func:`forward_recovery` — decorator to mark a method as a forward-recovery handler
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from sagaz.execution.graph import CompensationType

# Type for saga step functions
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

# Hook type definitions
OnEnterHook = Callable[[dict[str, Any], str], Awaitable[None] | None]
OnSuccessHook = Callable[[dict[str, Any], str, Any], Awaitable[None] | None]
OnFailureHook = Callable[[dict[str, Any], str, Exception], Awaitable[None] | None]
OnCompensateHook = Callable[[dict[str, Any], str], Awaitable[None] | None]


@dataclass
class StepMetadata:
    """Metadata attached to step functions via decorator."""

    name: str
    depends_on: list[str] = field(default_factory=list)
    aggregate_type: str | None = None
    event_type: str | None = None
    timeout_seconds: float = 60.0
    max_retries: int = 3
    description: str | None = None
    # Lifecycle hooks
    on_enter: OnEnterHook | None = None
    on_success: OnSuccessHook | None = None
    on_failure: OnFailureHook | None = None
    # v1.3.0: Pivot support
    pivot: bool = False
    """If True, marks this step as a point of no return (irreversible)."""


@dataclass
class CompensationMetadata:
    """Metadata attached to compensation functions via decorator."""

    for_step: str
    depends_on: list[str] = field(default_factory=list)
    compensation_type: CompensationType = CompensationType.MECHANICAL
    timeout_seconds: float = 30.0
    max_retries: int = 3
    description: str | None = None
    # Lifecycle hook for compensation
    on_compensate: OnCompensateHook | None = None


def step(
    name: str,
    depends_on: list[str] | None = None,
    aggregate_type: str | None = None,
    event_type: str | None = None,
    timeout_seconds: float = 60.0,
    max_retries: int = 3,
    description: str | None = None,
    on_enter: OnEnterHook | None = None,
    on_success: OnSuccessHook | None = None,
    on_failure: OnFailureHook | None = None,
    pivot: bool = False,
) -> Callable[[F], F]:
    """
    Decorator to mark a method as a saga step.

    Args:
        name: Unique identifier for this step
        depends_on: List of step names that must complete before this step
        aggregate_type: Event aggregate type (for outbox pattern)
        event_type: Event type (for outbox pattern)
        timeout_seconds: Step execution timeout (default: 60s)
        max_retries: Maximum retry attempts (default: 3)
        description: Human-readable description
        on_enter: Hook called before step execution (ctx, step_name) -> None
        on_success: Hook called after success (ctx, step_name, result) -> None
        on_failure: Hook called on failure (ctx, step_name, error) -> None
        pivot: If True, marks this step as a point of no return (v1.3.0).
               Once completed, ancestor steps become tainted and cannot be
               rolled back. Use for irreversible actions like payment charges.

    Example:
        >>> class OrderSaga(Saga):
        ...     @step(name="reserve_inventory")
        ...     async def reserve(self, ctx):
        ...         return {"reservation_id": "RES-123"}
        ...
        ...     @step(name="charge_payment", depends_on=["reserve_inventory"], pivot=True)
        ...     async def charge(self, ctx):
        ...         # PIVOT: Once this completes, reserve_inventory cannot be rolled back
        ...         return {"charge_id": "CHG-456"}
    """

    def decorator(func: F) -> F:
        # Store metadata on the function
        func._saga_step_meta = StepMetadata(  # type: ignore[attr-defined]
            name=name,
            depends_on=depends_on or [],
            aggregate_type=aggregate_type,
            event_type=event_type,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            description=description or f"Execute {name}",
            on_enter=on_enter,
            on_success=on_success,
            on_failure=on_failure,
            pivot=pivot,
        )
        return func

    return decorator


def compensate(
    for_step: str,
    compensation_type: CompensationType = CompensationType.MECHANICAL,
    timeout_seconds: float = 30.0,
    max_retries: int = 3,
    description: str | None = None,
    on_compensate: OnCompensateHook | None = None,
) -> Callable[[F], F]:
    """
    Decorator to mark a method as compensation for a step.

    Compensation functions are called when a saga fails and needs to
    undo previously completed steps.

    Compensation dependencies are automatically derived from the forward
    action dependencies and reversed by the compensation graph.

    Args:
        for_step: Name of the step this compensates
        compensation_type: Type of compensation (MECHANICAL, SEMANTIC, MANUAL)
        timeout_seconds: Compensation timeout (default: 30s)
        max_retries: Maximum retry attempts (default: 3)
        description: Human-readable description
        on_compensate: Hook called when compensation runs (ctx, step_name) -> None

    Example:
        >>> @compensate("charge_payment", on_compensate=publish_refund_event)
        ... async def refund(self, ctx):
        ...     await PaymentService.refund(ctx["charge_id"])
    """

    def decorator(func: F) -> F:
        func._saga_compensation_meta = CompensationMetadata(  # type: ignore[attr-defined]
            for_step=for_step,
            depends_on=[],  # No longer used - dependencies derived from forward actions
            compensation_type=compensation_type,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            description=description or f"Compensate {for_step}",
            on_compensate=on_compensate,
        )
        return func

    return decorator


# =============================================================================
# v1.3.0: Forward Recovery Decorator
# =============================================================================


@dataclass
class ForwardRecoveryMetadata:
    """
    Metadata attached to forward recovery handler functions via decorator.

    Forward recovery handlers are invoked when a step fails after a pivot
    has completed. Instead of rolling back, they decide how to proceed forward.
    """

    for_step: str
    """Name of the step this handles recovery for."""

    max_retries: int = 3
    """Maximum retry attempts if RETRY action returned."""

    timeout_seconds: float = 30.0
    """Handler timeout in seconds."""


def forward_recovery(
    for_step: str,
    max_retries: int = 3,
    timeout_seconds: float = 30.0,
) -> Callable[[F], F]:
    """
    Decorator to mark a method as forward recovery handler for a step.

    Forward recovery is invoked when a step fails AFTER a pivot has completed.
    Instead of traditional compensation (rollback), the handler decides how
    to proceed forward.

    The handler must return a RecoveryAction enum value:
    - RETRY: Retry the failed step
    - RETRY_WITH_ALTERNATE: Retry with modified parameters
    - SKIP: Skip this step and continue forward
    - MANUAL_INTERVENTION: Escalate to human/manual handling
    - COMPENSATE_PIVOT: Trigger semantic compensation of pivot (rare)

    Args:
        for_step: Name of the step this handles recovery for
        max_retries: Maximum retry attempts if RETRY action returned (default: 3)
        timeout_seconds: Handler timeout (default: 30s)

    See Also:
        - RecoveryAction: Enum of possible actions to return
        - ADR-023: Pivot/Irreversible Steps documentation
    """

    def decorator(func: F) -> F:
        func._saga_forward_recovery_meta = ForwardRecoveryMetadata(  # type: ignore[attr-defined]
            for_step=for_step,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        return func

    return decorator


# Public alias matching original API
action = step
