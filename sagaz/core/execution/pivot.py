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
    >>> from sagaz.core.execution.pivot import RecoveryAction
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
from typing import TYPE_CHECKING, Any

from sagaz.core.execution._pivot_types import PivotInfo, RecoveryAction, SagaZones, StepZone

if TYPE_CHECKING:
    pass


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
            return set()  # defensive check

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
        if step_name in self.pivots and step_name not in self.completed_pivots:
            return True  # Can still compensate if pivot didn't complete
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
