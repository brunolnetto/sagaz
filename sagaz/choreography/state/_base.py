"""What a choreography participant must remember (#448).

To compensate correctly and handle each delivery once, a participant keeps,
per transaction (correlation id):

- the actions it completed that have a ``@compensate`` method;
- whether the transaction is finished (completed or compensated), so late
  actions are not remembered, and whether it was compensated (a tombstone:
  later business events are not acted on, #446);
- which deliveries (``event_id``) it already handled.

:class:`ParticipantState` stores this. The in-memory implementation is the
default; the SQL ones survive restarts and are shared by every replica of a
participant. All operations act in the current tenant scope (ADR-020).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from sagaz.choreography.events import Event

COMPLETED, COMPENSATED = "completed", "compensated"


@dataclass(frozen=True)
class Deadline:
    """A transaction that *participant* wants completed by *due_at* (#449)."""

    tenant_id: str
    participant: str
    correlation_id: str
    due_at: datetime


class ParticipantState(ABC):
    """Per-participant, per-transaction memory of a choreography participant."""

    @abstractmethod
    async def record_action(self, participant: str, event: Event) -> None:
        """Remember that *participant* completed the action triggered by *event*.

        Ignored when the event's transaction is already finished, and for an
        event already recorded.
        """

    @abstractmethod
    async def finish(
        self, participant: str, correlation_id: str, *, compensated: bool
    ) -> list[Event]:
        """End *participant*'s part of *correlation_id*.

        Returns the recorded actions, oldest first, and forgets them, together
        with its deadline. Once compensated, a transaction stays compensated.
        """

    @abstractmethod
    async def was_compensated(self, participant: str, correlation_id: str) -> bool:
        """True if *participant* compensated *correlation_id*."""

    @abstractmethod
    async def first_delivery(self, participant: str, event_id: str) -> bool:
        """Claim *event_id* for *participant*: True the first time only."""

    @abstractmethod
    async def set_deadline(self, participant: str, correlation_id: str, due_at: datetime) -> None:
        """Expect *correlation_id* to finish by *due_at* (ignored if it already ended)."""

    @abstractmethod
    async def claim_due_deadlines(
        self, participants: Collection[str], now: datetime, lease: timedelta, limit: int = 100
    ) -> list[Deadline]:
        """Claim deadlines of *participants* due at *now*, in every tenant.

        A claimed deadline is not returned again for *lease*, so one replica
        acts on it. It is deleted when its transaction finishes; if the claimer
        dies first, the lease expires and another replica claims it.
        """

    async def publish(
        self,
        participant: str,
        event: Event,
        send: Callable[[Event], Awaitable[None]],
        *,
        cause: Event | None = None,
        remember: bool = False,
        begin: bool = False,
    ) -> None:
        """Publish *event* for *participant*, first recording *cause* if *remember*.

        *begin* marks the first event of a transaction. Here the two steps are
        separate (record, then ``send`` on the bus); the unified saga log does
        both in one database transaction through its outbox (ADR-041).
        """
        if remember and cause is not None:
            await self.record_action(participant, cause)
        await send(event)

    async def prune(self, older_than: timedelta) -> int:
        """Delete finished transactions and handled deliveries older than *older_than*.

        Returns how many records were deleted. Bounded stores prune themselves.
        """
        return 0

    async def close(self) -> None:
        """Release connections."""
