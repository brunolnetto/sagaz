"""``SagaSummaryProjection``: a saga's state, rebuilt from its events (ADR-033, #57).

Applying a saga's events in order gives its status, the outcome of each step
and the failure, if any. The projection is also what the event store saves as
a snapshot, so loading a long stream only replays the events after the latest
snapshot (:func:`load_projection`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from sagaz.core.events import (
    CompensationStarted,
    SagaCompleted,
    SagaEvent,
    SagaFailed,
    SagaRolledBack,
    SagaStarted,
    StepCompensated,
    StepCompensationFailed,
    StepExecuted,
    StepFailed,
)

if TYPE_CHECKING:
    from sagaz.core.storage.event_store import SagaEventStore

PENDING, EXECUTING, COMPENSATING, COMPLETED, ROLLED_BACK, FAILED = (
    "pending",
    "executing",
    "compensating",
    "completed",
    "rolled_back",
    "failed",
)


@dataclass
class StepSummary:
    """What happened to one step."""

    name: str
    status: str = PENDING
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class SagaSummaryProjection:
    """A saga's state as of ``last_sequence``.

    Example::

        projection = SagaSummaryProjection("saga-123")
        for event in await store.load_stream("saga-123"):
            projection.apply(event)
    """

    saga_id: str
    saga_name: str = ""
    tenant_id: str = "default"
    status: str = PENDING
    context: dict[str, Any] = field(default_factory=dict)
    steps: dict[str, StepSummary] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: float = 0.0
    failed_step: str | None = None
    error: str | None = None
    #: Sequence of the last event applied.
    last_sequence: int = 0
    #: Events applied, including those a snapshot already accounted for.
    event_count: int = 0
    #: Runs started with this saga id (a re-run appends to the same stream).
    runs: int = 0

    def apply(self, event: SagaEvent) -> None:
        """Fold ``event`` into the state. Events already applied are ignored."""
        if event.sequence and event.sequence <= self.last_sequence:
            return
        handler = _HANDLERS.get(type(event))
        if handler is not None:
            handler(self, event)
        self.saga_name = event.saga_name or self.saga_name
        self.tenant_id = event.tenant_id
        self.last_sequence = event.sequence or self.last_sequence + 1
        self.event_count += 1

    def _step(self, name: str) -> StepSummary:
        return self.steps.setdefault(name, StepSummary(name))

    def _on_started(self, event: SagaStarted) -> None:
        self.status = EXECUTING
        self.runs += 1
        self.context = dict(event.initial_context)
        self.steps = {}
        self.started_at = event.occurred_at.isoformat()
        self.finished_at = None
        self.failed_step = self.error = None
        self.duration_ms = 0.0

    def _on_step_executed(self, event: StepExecuted) -> None:
        step = self._step(event.step_name)
        step.status, step.result, step.error = COMPLETED, event.step_result, None
        step.duration_ms = event.duration_ms
        if isinstance(event.step_result, dict):
            self.context.update(event.step_result)

    def _on_step_failed(self, event: StepFailed) -> None:
        step = self._step(event.step_name)
        step.status, step.error = FAILED, f"{event.error_type}: {event.error_message}"
        self.failed_step = self.failed_step or event.step_name

    def _on_compensation_started(self, event: CompensationStarted) -> None:
        self.status = COMPENSATING
        self.failed_step = event.failed_step or self.failed_step
        self.error = f"{event.error_type}: {event.error_message}"

    def _on_step_compensated(self, event: StepCompensated) -> None:
        self._step(event.step_name).status = "compensated"

    def _on_step_compensation_failed(self, event: StepCompensationFailed) -> None:
        step = self._step(event.step_name)
        step.status = "compensation_failed"
        step.error = f"{event.error_type}: {event.error_message}"

    def _finish(self, status: str, event: SagaEvent, duration_ms: float) -> None:
        self.status = status
        self.finished_at = event.occurred_at.isoformat()
        self.duration_ms = duration_ms

    def _on_completed(self, event: SagaCompleted) -> None:
        self._finish(COMPLETED, event, event.duration_ms)

    def _on_rolled_back(self, event: SagaRolledBack) -> None:
        self._finish(ROLLED_BACK, event, event.duration_ms)

    def _on_failed(self, event: SagaFailed) -> None:
        self._finish(FAILED, event, event.duration_ms)
        self.error = event.error_message or self.error

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SagaSummaryProjection:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        steps = {
            name: StepSummary(
                **{k: v for k, v in step.items() if k in StepSummary.__dataclass_fields__}
            )
            for name, step in (known.pop("steps", None) or {}).items()
        }
        return cls(**known, steps=steps)


_HANDLERS: dict[type[SagaEvent], Any] = {
    SagaStarted: SagaSummaryProjection._on_started,
    StepExecuted: SagaSummaryProjection._on_step_executed,
    StepFailed: SagaSummaryProjection._on_step_failed,
    CompensationStarted: SagaSummaryProjection._on_compensation_started,
    StepCompensated: SagaSummaryProjection._on_step_compensated,
    StepCompensationFailed: SagaSummaryProjection._on_step_compensation_failed,
    SagaCompleted: SagaSummaryProjection._on_completed,
    SagaRolledBack: SagaSummaryProjection._on_rolled_back,
    SagaFailed: SagaSummaryProjection._on_failed,
}


def build_projection(saga_id: str, events: list[SagaEvent]) -> SagaSummaryProjection:
    """The projection of ``events`` (a full stream, in order)."""
    projection = SagaSummaryProjection(saga_id)
    for event in events:
        projection.apply(event)
    return projection


async def load_projection(store: SagaEventStore, saga_id: str) -> SagaSummaryProjection | None:
    """``saga_id``'s current state: the latest snapshot plus the events after it.

    Returns ``None`` when the saga has no events (in the current tenant scope).
    """
    snapshot = await store.load_latest_snapshot(saga_id)
    if snapshot is None:
        events = await store.load_stream(saga_id)
        return build_projection(saga_id, events) if events else None
    projection = SagaSummaryProjection.from_dict(snapshot.state)
    for event in await store.load_stream_after(saga_id, snapshot.sequence):
        projection.apply(event)
    return projection
