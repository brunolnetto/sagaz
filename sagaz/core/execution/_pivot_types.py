"""Pivot step types: recovery actions, step zones and zone analysis results.

Re-exported from :mod:`sagaz.core.execution.pivot`, which is the public import path.
"""

from dataclasses import dataclass, field
from enum import Enum


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
            return next(iter(self.pivots)) if self.pivots else None
        return None
