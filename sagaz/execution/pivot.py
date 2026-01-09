"""
Pivot/Irreversible Steps Support.

Provides types and utilities for marking saga steps as "points of no return"
with automatic taint propagation and forward recovery strategies.

A pivot step represents a commitment point in a saga where traditional
rollback is no longer possible or desirable. Examples include:
- Payment charges (can only refund, not undo)
- External API calls with side effects
- Physical actions (drone takeoff, manufacturing start)
- Compliance events (audit trail creation)

Usage:
    >>> from sagaz import Saga, action, compensate, forward_recovery
    >>> from sagaz.execution.pivot import RecoveryAction
    >>>
    >>> class PaymentSaga(Saga):
    ...     saga_name = "payment"
    ...
    ...     @action("reserve_funds")
    ...     async def reserve(self, ctx):
    ...         return {"reservation_id": "RES-123"}
    ...
    ...     @action("charge_payment", depends_on=["reserve_funds"], pivot=True)
    ...     async def charge(self, ctx):
    ...         # PIVOT: Once charged, ancestors are tainted
    ...         return {"charge_id": "CHG-456"}
    ...
    ...     @action("ship_order", depends_on=["charge_payment"])
    ...     async def ship(self, ctx):
    ...         return {"shipment_id": "SHP-789"}
    ...
    ...     @forward_recovery("ship_order")
    ...     async def handle_shipping_failure(self, ctx, error):
    ...         if ctx.get("retry_count", 0) < 3:
    ...             return RecoveryAction.RETRY
    ...         return RecoveryAction.MANUAL_INTERVENTION

See Also:
    - ADR-023: Pivot/Irreversible Steps documentation
    - SagaResult.pivot_reached for checking if pivot was crossed
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    pass


class RecoveryAction(Enum):
    """
    Actions that forward recovery handlers can return.

    When a step fails after a pivot has completed, the saga cannot
    perform traditional rollback. Instead, a forward recovery handler
    must decide how to proceed.

    Attributes:
        RETRY: Retry the failed step with the same parameters
        RETRY_WITH_ALTERNATE: Retry with modified parameters/alternate logic
        SKIP: Skip this step and continue with the saga
        MANUAL_INTERVENTION: Escalate to human/manual handling
        COMPENSATE_PIVOT: Trigger semantic compensation of the pivot (rare)

    Example:
        @forward_recovery("ship_order")
        async def handle_shipping_failure(self, ctx, error):
            retry_count = ctx.get("_ship_order_retries", 0)

            if retry_count < 3:
                ctx["_ship_order_retries"] = retry_count + 1
                return RecoveryAction.RETRY

            if has_alternate_carrier():
                ctx["use_alternate_carrier"] = True
                return RecoveryAction.RETRY_WITH_ALTERNATE

            return RecoveryAction.MANUAL_INTERVENTION
    """

    RETRY = "retry"
    """Retry the failed step with the same parameters."""

    RETRY_WITH_ALTERNATE = "retry_alt"
    """Retry with modified parameters or alternate logic."""

    SKIP = "skip"
    """Skip this step and continue forward with the saga."""

    MANUAL_INTERVENTION = "manual"
    """Escalate to human/manual handling. Saga enters NEEDS_FORWARD_RECOVERY state."""

    COMPENSATE_PIVOT = "compensate"
    """Trigger semantic compensation of the pivot (rare, use with caution)."""


class StepZone(Enum):
    """
    Zone classification for saga steps relative to pivots.

    Zones are automatically calculated based on pivot positions and
    provide visibility into which steps can be rolled back vs which
    are committed.

    Attributes:
        REVERSIBLE: Step is before any pivot - full rollback available
        PIVOT: The pivot step itself - the commitment point
        COMMITTED: Step is after a pivot - forward recovery only
        TAINTED: Step is an ancestor of a completed pivot - locked from rollback

    Visual representation:
        ┌─────────────────────────────────────────────────────────────┐
        │                        SAGA ZONES                            │
        ├─────────────────────────────────────────────────────────────┤
        │  REVERSIBLE ZONE                                             │
        │  ┌──────────┐      ┌──────────┐                             │
        │  │ validate │  ──→ │ reserve  │                             │
        │  └──────────┘      └──────────┘                             │
        │  Can fully rollback ↑                                        │
        ├─────────────────────────────────────────────────────────────┤
        │                    ↓ PIVOT BOUNDARY ↓                        │
        ├─────────────────────────────────────────────────────────────┤
        │  COMMITTED ZONE                                              │
        │  ┌──────────┐      ┌──────────┐      ┌──────────┐           │
        │  │ charge   │  ──→ │ ship     │  ──→ │ notify   │           │
        │  │ (PIVOT)  │      │          │      │          │           │
        │  └──────────┘      └──────────┘      └──────────┘           │
        │  Forward-only recovery →                                     │
        └─────────────────────────────────────────────────────────────┘
    """

    REVERSIBLE = "reversible"
    """Step is before any pivot - full rollback available."""

    PIVOT = "pivot"
    """The pivot step itself - marks the commitment point."""

    COMMITTED = "committed"
    """Step is after a pivot - can only use forward recovery."""

    TAINTED = "tainted"
    """Step is an ancestor of a completed pivot - locked from rollback."""


@dataclass
class PivotInfo:
    """
    Information about a pivot step and its taint boundary.

    Tracks which steps are locked from rollback when this pivot completes.

    Attributes:
        step_name: Name of the pivot step
        completed: Whether the pivot has successfully executed
        tainted_ancestors: Set of ancestor step names that are now locked
    """

    step_name: str
    """Name of the pivot step."""

    completed: bool = False
    """Whether the pivot has successfully executed."""

    tainted_ancestors: set[str] = field(default_factory=set)
    """Set of ancestor step names that are locked from rollback."""


@dataclass
class SagaZones:
    """
    Zone analysis result for a saga.

    Contains sets of step names classified by their zone relative to
    pivot steps. Used for visualization, validation, and rollback decisions.

    Attributes:
        reversible: Steps before any pivot - can be fully rolled back
        pivots: The pivot steps themselves
        committed: Steps after pivots - forward recovery only
        tainted: Ancestors of completed pivots - locked from rollback
    """

    reversible: set[str] = field(default_factory=set)
    """Steps that can be fully rolled back (before any pivot)."""

    pivots: set[str] = field(default_factory=set)
    """The pivot steps themselves (commitment points)."""

    committed: set[str] = field(default_factory=set)
    """Steps after pivots (forward recovery only)."""

    tainted: set[str] = field(default_factory=set)
    """Ancestors of completed pivots (locked from rollback)."""

    def get_zone(self, step_name: str) -> StepZone:
        """
        Get the zone for a specific step.

        Args:
            step_name: Name of the step to classify

        Returns:
            StepZone enum value for the step
        """
        if step_name in self.tainted:
            return StepZone.TAINTED
        if step_name in self.pivots:
            return StepZone.PIVOT
        if step_name in self.committed:
            return StepZone.COMMITTED
        return StepZone.REVERSIBLE

    def is_rollback_allowed(self, step_name: str) -> bool:
        """
        Check if rollback is allowed for a step.

        Args:
            step_name: Name of the step to check

        Returns:
            True if rollback is allowed, False if tainted or is pivot
        """
        zone = self.get_zone(step_name)
        return zone in (StepZone.REVERSIBLE, StepZone.COMMITTED)

    def get_rollback_boundary(self, step_name: str) -> str | None:
        """
        Get the rollback boundary for a step.

        If the step is in the committed zone, returns the pivot step name.
        Otherwise returns None (full rollback available).

        Args:
            step_name: Name of the step

        Returns:
            Pivot step name if rollback is bounded, None otherwise
        """
        if step_name in self.committed:
            # Find the nearest pivot ancestor
            # This is a simplified version - full implementation
            # would trace back through dependencies
            return next(iter(self.pivots)) if self.pivots else None  # pragma: no cover
        return None


# Type aliases for forward recovery handlers
ForwardRecoveryHandler = Callable[[dict[str, Any], Exception], Awaitable[RecoveryAction]]
"""
Type alias for forward recovery handler functions.

A forward recovery handler takes the saga context and the exception
that caused the failure, and returns a RecoveryAction indicating
how to proceed.
"""


class TaintPropagator:
    """
    Calculates taint propagation when pivots complete.

    When a pivot step completes successfully:
    1. All ancestor steps become "tainted" (locked from rollback)
    2. The pivot itself acts as a one-way boundary
    3. Descendant steps remain in "committed" zone (can compensate backward to pivot)

    This ensures that once a commitment is made (e.g., payment charged),
    we don't accidentally undo prerequisite steps that enabled it.

    Example:
        propagator = TaintPropagator(steps, dependencies)

        # When pivot completes
        tainted = propagator.propagate_taint("charge_payment")
        # Returns: {"validate_order", "reserve_funds"}

        # Get zones for visualization
        zones = propagator.calculate_zones()
    """

    def __init__(
        self,
        step_names: set[str],
        dependencies: dict[str, set[str]],
        pivots: set[str],
        completed_pivots: set[str] | None = None,
    ):
        """
        Initialize the taint propagator.

        Args:
            step_names: Set of all step names in the saga
            dependencies: Map of step name -> set of dependency step names
            pivots: Set of step names marked as pivots
            completed_pivots: Set of pivot step names that have completed
        """
        self.step_names = step_names
        self.dependencies = dependencies
        self.pivots = pivots
        self.completed_pivots = completed_pivots or set()
        self._tainted: set[str] = set()

    def get_ancestors(self, step_name: str) -> set[str]:
        """
        Get all ancestors of a step (transitive dependencies).

        Args:
            step_name: Name of the step

        Returns:
            Set of all ancestor step names
        """
        ancestors: set[str] = set()
        to_visit = list(self.dependencies.get(step_name, set()))

        while to_visit:
            current = to_visit.pop()
            if current not in ancestors and current in self.step_names:
                ancestors.add(current)
                to_visit.extend(self.dependencies.get(current, set()))

        return ancestors

    def get_descendants(self, step_name: str) -> set[str]:
        """
        Get all descendants of a step (steps that depend on it).

        Args:
            step_name: Name of the step

        Returns:
            Set of all descendant step names
        """
        descendants: set[str] = set()

        for name, deps in self.dependencies.items():
            if step_name in deps:
                descendants.add(name)
                descendants.update(self.get_descendants(name))

        return descendants

    def propagate_taint(self, completed_pivot: str) -> set[str]:
        """
        Propagate taint from a completed pivot.

        Called when a pivot step completes successfully. All ancestor
        steps become tainted and are locked from rollback.

        Args:
            completed_pivot: Name of the pivot step that just completed

        Returns:
            Set of step names that were newly tainted
        """
        if completed_pivot not in self.pivots:
            return set()  # pragma: no cover - defensive check

        self.completed_pivots.add(completed_pivot)
        ancestors = self.get_ancestors(completed_pivot)
        newly_tainted = ancestors - self._tainted
        self._tainted.update(ancestors)

        return newly_tainted

    def calculate_zones(self) -> SagaZones:
        """
        Calculate zones for all steps.

        Zones are determined by:
        - REVERSIBLE: Steps before any pivot (not ancestors of pivots if no pivot completed)
        - PIVOT: Steps marked as pivot
        - TAINTED: Ancestors of completed pivots
        - COMMITTED: Descendants of completed pivots (including the pivot itself in some sense)

        Returns:
            SagaZones with classified step names
        """
        zones = SagaZones()
        zones.pivots = self.pivots.copy()

        # Calculate tainted (ancestors of completed pivots)
        for pivot_name in self.completed_pivots:
            ancestors = self.get_ancestors(pivot_name)
            zones.tainted.update(ancestors)

        # Calculate committed (descendants of completed pivots, plus pivot itself once complete)
        for pivot_name in self.completed_pivots:
            descendants = self.get_descendants(pivot_name)
            zones.committed.update(descendants)
            zones.committed.add(pivot_name)  # Pivot becomes committed once done

        # Everything else before pivots is reversible
        for step_name in self.step_names:
            if (
                step_name not in zones.pivots
                and step_name not in zones.tainted
                and step_name not in zones.committed
            ):
                zones.reversible.add(step_name)

        return zones

    def get_rollback_boundary(self, failed_step: str) -> str | None:
        """
        Get the rollback boundary for a failed step.

        If the failed step is after a completed pivot, rollback stops
        at the pivot (does not cross into tainted ancestors).

        Args:
            failed_step: Name of the step that failed

        Returns:
            Name of the pivot step where rollback should stop,
            or None if full rollback is available
        """
        for pivot_name in self.completed_pivots:
            descendants = self.get_descendants(pivot_name)
            # Check if failed step is after this pivot
            if failed_step in descendants or failed_step == pivot_name:
                return pivot_name

        return None  # Full rollback available

    def is_tainted(self, step_name: str) -> bool:
        """
        Check if a step is tainted.

        Args:
            step_name: Name of the step to check

        Returns:
            True if the step is tainted (locked from rollback)
        """
        return step_name in self._tainted

    def can_compensate(self, step_name: str) -> bool:
        """
        Check if a step can be compensated.

        Args:
            step_name: Name of the step to check

        Returns:
            True if compensation is allowed for this step
        """
        # Cannot compensate tainted steps
        if step_name in self._tainted:
            return False
        # Cannot compensate incomplete pivots
        if step_name in self.pivots and step_name not in self.completed_pivots:  # pragma: no cover
            return True  # Can still compensate if pivot didn't complete  # pragma: no cover
        return True


__all__ = [
    # Type aliases
    "ForwardRecoveryHandler",
    # Dataclasses
    "PivotInfo",
    # Enums
    "RecoveryAction",
    "SagaZones",
    "StepZone",
    # Classes
    "TaintPropagator",
]
