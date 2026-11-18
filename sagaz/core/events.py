"""Saga domain events for the event-sourced storage strategy (ADR-033, #57).

Each event records one state change of a saga run. Appended in order to a
:class:`~sagaz.core.storage.event_store.SagaEventStore`, they form the saga's
history, from which its state is rebuilt (see :mod:`sagaz.projections`).

Events are immutable. Their payloads hold JSON-safe values only, so a stream
reads back exactly as it was written, including ``event_id`` and
``occurred_at``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from typing import Any, ClassVar

from sagaz.core.storage.canonical import canonical_value

#: Version of the event schema. Bump it, and keep reading older versions, when
#: an event's fields change incompatibly.
EVENT_VERSION = 1

#: Fields every event has. ``SagaEvent.from_dict`` reads them; subclass fields
#: are the payload.
_BASE_FIELDS = (
    "saga_id",
    "event_id",
    "occurred_at",
    "sequence",
    "saga_name",
    "tenant_id",
    "event_version",
    "metadata",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


def json_safe(value: Any) -> Any:
    """``value`` as plain JSON data (objects without a JSON form become strings)."""
    return json.loads(json.dumps(canonical_value(value), default=str))


@dataclass(frozen=True)
class SagaEvent:
    """Base of every saga event.

    ``sequence`` is the event's 1-based position in its saga's stream. The
    event store assigns it on append; it is 0 before that.
    """

    saga_id: str
    event_id: str = field(default_factory=_new_id)
    occurred_at: datetime = field(default_factory=_now)
    sequence: int = 0
    saga_name: str = ""
    tenant_id: str = "default"
    event_version: int = EVENT_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    #: Name stored as the event's type; the class name unless overridden.
    event_type: ClassVar[str] = "SagaEvent"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.event_type = cls.__name__

    @property
    def payload(self) -> dict[str, Any]:
        """The event-specific fields."""
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in _BASE_FIELDS}

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "saga_id": self.saga_id,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at.isoformat(),
            "sequence": self.sequence,
            "saga_name": self.saga_name,
            "tenant_id": self.tenant_id,
            "event_version": self.event_version,
            "metadata": json_safe(self.metadata),
            "payload": json_safe(self.payload),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> SagaEvent:
        """Rebuild an event written by :meth:`to_dict`.

        An event type this version does not know (written by a newer one)
        comes back as :class:`UnrecognizedEvent`, so reading a stream never
        fails on it.
        """
        cls = _EVENT_TYPES.get(data.get("event_type", ""))
        payload = dict(data.get("payload") or {})
        base = _base_fields(data)
        if cls is None:
            return UnrecognizedEvent(
                **base, original_type=str(data.get("event_type")), data=payload
            )
        known = {f.name for f in fields(cls)}
        return cls(**base, **{k: v for k, v in payload.items() if k in known})


def _base_fields(data: dict[str, Any]) -> dict[str, Any]:
    """The common fields of a serialized event, with defaults for missing ones."""
    return {
        "saga_id": data["saga_id"],
        "event_id": data.get("event_id") or _new_id(),
        "occurred_at": _parse_time(data.get("occurred_at")),
        "sequence": int(data.get("sequence") or 0),
        "saga_name": data.get("saga_name") or "",
        "tenant_id": data.get("tenant_id") or "default",
        "event_version": int(data.get("event_version") or EVENT_VERSION),
        "metadata": dict(data.get("metadata") or {}),
    }


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return _now()


@dataclass(frozen=True)
class SagaStarted(SagaEvent):
    """A saga run began with ``initial_context``."""

    initial_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepExecuted(SagaEvent):
    """A step's action succeeded."""

    step_name: str = ""
    step_result: Any = None
    duration_ms: float = 0.0


@dataclass(frozen=True)
class StepFailed(SagaEvent):
    """A step's action failed (after its retries)."""

    step_name: str = ""
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class CompensationStarted(SagaEvent):
    """The saga began undoing completed steps after ``failed_step`` failed."""

    failed_step: str = ""
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class StepCompensated(SagaEvent):
    """A step's compensation succeeded."""

    step_name: str = ""


@dataclass(frozen=True)
class StepCompensationFailed(SagaEvent):
    """A step's compensation failed; the step's effects remain."""

    step_name: str = ""
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class SagaCompleted(SagaEvent):
    """Every step succeeded."""

    duration_ms: float = 0.0


@dataclass(frozen=True)
class SagaRolledBack(SagaEvent):
    """A step failed and every completed step was compensated."""

    duration_ms: float = 0.0


@dataclass(frozen=True)
class SagaFailed(SagaEvent):
    """The saga failed and could not be fully compensated."""

    error_message: str = ""
    duration_ms: float = 0.0


@dataclass(frozen=True)
class UnrecognizedEvent(SagaEvent):
    """An event of a type this version of sagaz does not know."""

    original_type: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["event_type"] = self.original_type
        d["payload"] = json_safe(self.data)
        return d


_EVENT_TYPES: dict[str, type[SagaEvent]] = {
    cls.__name__: cls
    for cls in (
        SagaStarted,
        StepExecuted,
        StepFailed,
        CompensationStarted,
        StepCompensated,
        StepCompensationFailed,
        SagaCompleted,
        SagaRolledBack,
        SagaFailed,
    )
}

#: Event types that end a saga run.
TERMINAL_EVENTS: frozenset[type[SagaEvent]] = frozenset({SagaCompleted, SagaRolledBack, SagaFailed})


def event_class(event_type: str) -> type[SagaEvent] | None:
    """The event class named ``event_type``, if known."""
    return _EVENT_TYPES.get(event_type)


__all__ = [
    "EVENT_VERSION",
    "TERMINAL_EVENTS",
    "CompensationStarted",
    "SagaCompleted",
    "SagaEvent",
    "SagaFailed",
    "SagaRolledBack",
    "SagaStarted",
    "StepCompensated",
    "StepCompensationFailed",
    "StepExecuted",
    "StepFailed",
    "UnrecognizedEvent",
    "event_class",
    "json_safe",
]
