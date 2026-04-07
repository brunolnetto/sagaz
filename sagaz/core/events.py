"""
SagaEvent hierarchy for event-sourced storage strategy.

These domain events represent every state change in a saga's lifecycle.
They form the immutable, append-only stream persisted by ``SagaEventStore``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class SagaEvent:
    """Base class for all saga domain events."""

    saga_id: str
    event_id: str = field(default_factory=_new_id)
    occurred_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": type(self).__name__,
            "saga_id": self.saga_id,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SagaStarted(SagaEvent):
    """Raised when a saga begins execution."""

    saga_name: str = ""
    initial_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(saga_name=self.saga_name, initial_context=self.initial_context)
        return d


@dataclass(frozen=True)
class StepExecuted(SagaEvent):
    """Raised when a saga step completes successfully."""

    step_name: str = ""
    step_result: Any = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            step_name=self.step_name,
            step_result=self.step_result,
            duration_ms=self.duration_ms,
        )
        return d


@dataclass(frozen=True)
class StepFailed(SagaEvent):
    """Raised when a saga step fails."""

    step_name: str = ""
    error_type: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            step_name=self.step_name,
            error_type=self.error_type,
            error_message=self.error_message,
        )
        return d


@dataclass(frozen=True)
class StepCompensated(SagaEvent):
    """Raised when a step's compensation action completes."""

    step_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(step_name=self.step_name)
        return d


@dataclass(frozen=True)
class CompensationStarted(SagaEvent):
    """Raised when the saga begins rolling back."""

    failed_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(failed_step=self.failed_step)
        return d


@dataclass(frozen=True)
class SagaCompleted(SagaEvent):
    """Raised when all saga steps succeed."""

    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(duration_ms=self.duration_ms)
        return d


@dataclass(frozen=True)
class SagaRolledBack(SagaEvent):
    """Raised when a saga successfully rolls back all steps."""

    compensation_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(compensation_duration_ms=self.compensation_duration_ms)
        return d


@dataclass(frozen=True)
class SagaFailed(SagaEvent):
    """Raised when a saga cannot be rolled back (unrecoverable)."""

    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(error_message=self.error_message)
        return d


# Registry for deserialization
_EVENT_REGISTRY: dict[str, type[SagaEvent]] = {
    cls.__name__: cls
    for cls in [
        SagaStarted,
        StepExecuted,
        StepFailed,
        StepCompensated,
        CompensationStarted,
        SagaCompleted,
        SagaRolledBack,
        SagaFailed,
    ]
}


def event_type_from_name(name: str) -> type[SagaEvent] | None:
    return _EVENT_REGISTRY.get(name)
