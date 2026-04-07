"""
SagaSummaryProjection — read-model derived from a saga's event stream.

Applies each ``SagaEvent`` in sequence to produce a plain-dict summary that
mirrors the snapshot-based representation used by the existing storage layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sagaz.core.events import (
    CompensationStarted,
    SagaCompleted,
    SagaEvent,
    SagaFailed,
    SagaRolledBack,
    SagaStarted,
    StepCompensated,
    StepExecuted,
    StepFailed,
)


@dataclass
class StepSummary:
    name: str
    status: str = "pending"
    result: Any = None
    error: str | None = None
    compensated: bool = False
    duration_ms: float = 0.0


@dataclass
class SagaSummaryProjection:
    """
    A mutable read-model built by replaying a saga's event stream.

    Parameters
    ----------
    saga_id:
        The saga whose events are being replayed.

    Example
    -------
    ::

        proj = SagaSummaryProjection("saga-123")
        for event in await store.load_stream("saga-123"):
            proj.apply(event)
        print(proj.to_dict())
    """

    saga_id: str
    saga_name: str = ""
    status: str = "pending"
    steps: dict[str, StepSummary] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    failed_step: str | None = None
    error_message: str | None = None

    # Sequence tracking for snapshot integration
    last_sequence: int = 0

    def apply(self, event: SagaEvent) -> None:
        """Apply *event* to update projection state."""
        if isinstance(event, SagaStarted):
            self.saga_name = event.saga_name
            self.status = "executing"
            self.started_at = event.occurred_at

        elif isinstance(event, StepExecuted):
            step = self.steps.setdefault(event.step_name, StepSummary(event.step_name))
            step.status = "completed"
            step.result = event.step_result
            step.duration_ms = event.duration_ms

        elif isinstance(event, StepFailed):
            step = self.steps.setdefault(event.step_name, StepSummary(event.step_name))
            step.status = "failed"
            step.error = f"{event.error_type}: {event.error_message}"

        elif isinstance(event, CompensationStarted):
            self.status = "compensating"
            self.failed_step = event.failed_step

        elif isinstance(event, StepCompensated):
            step = self.steps.get(event.step_name)
            if step:
                step.compensated = True
                step.status = "compensated"

        elif isinstance(event, SagaCompleted):
            self.status = "completed"
            self.completed_at = event.occurred_at
            self.duration_ms = event.duration_ms

        elif isinstance(event, SagaRolledBack):
            self.status = "rolled_back"
            self.completed_at = event.occurred_at
            self.duration_ms = event.compensation_duration_ms

        elif isinstance(event, SagaFailed):
            self.status = "failed"
            self.error_message = event.error_message
            self.completed_at = event.occurred_at

        self.last_sequence += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "saga_id": self.saga_id,
            "saga_name": self.saga_name,
            "status": self.status,
            "steps": {
                name: {
                    "status": s.status,
                    "result": s.result,
                    "error": s.error,
                    "compensated": s.compensated,
                    "duration_ms": s.duration_ms,
                }
                for name, s in self.steps.items()
            },
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "failed_step": self.failed_step,
            "error_message": self.error_message,
        }


def build_projection(saga_id: str, events: list[SagaEvent]) -> SagaSummaryProjection:
    """Convenience function: build a projection from a list of events."""
    proj = SagaSummaryProjection(saga_id=saga_id)
    for event in events:
        proj.apply(event)
    return proj
