"""The event store interface (ADR-033, #57)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sagaz.core.events import SagaEvent


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class SagaSnapshot:
    """A saga's projected state as of event ``sequence``."""

    saga_id: str
    sequence: int
    state: dict[str, Any]
    tenant_id: str = "default"
    created_at: datetime = field(default_factory=_now)


class SagaEventStore(ABC):
    """Append-only storage of saga event streams, with snapshots.

    Each saga's events form a stream numbered 1, 2, 3, ... The store assigns
    the numbers, so concurrent appends to one stream never share a sequence.
    Events and snapshots belong to the tenant of the scope that wrote them
    (ADR-020); reads see the current tenant's only, or every tenant's in the
    system scope.
    """

    @abstractmethod
    async def append(self, event: SagaEvent) -> SagaEvent:
        """Append ``event`` to its saga's stream; return it with its sequence."""

    @abstractmethod
    async def load_stream(self, saga_id: str) -> list[SagaEvent]:
        """Every event of ``saga_id``, in sequence order."""

    @abstractmethod
    async def load_stream_after(self, saga_id: str, after_sequence: int) -> list[SagaEvent]:
        """The events of ``saga_id`` with a sequence above ``after_sequence``."""

    @abstractmethod
    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """Store ``snapshot`` (replacing one at the same sequence)."""

    @abstractmethod
    async def load_latest_snapshot(self, saga_id: str) -> SagaSnapshot | None:
        """The snapshot of ``saga_id`` with the highest sequence, if any."""

    async def close(self) -> None:
        """Release connections."""

    async def __aenter__(self) -> SagaEventStore:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
