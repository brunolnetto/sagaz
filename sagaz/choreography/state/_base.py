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
from datetime import timedelta

from sagaz.choreography.events import Event

COMPLETED, COMPENSATED = "completed", "compensated"


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

        Returns the recorded actions, oldest first, and forgets them. Once
        compensated, a transaction stays compensated.
        """

    @abstractmethod
    async def was_compensated(self, participant: str, correlation_id: str) -> bool:
        """True if *participant* compensated *correlation_id*."""

    @abstractmethod
    async def first_delivery(self, participant: str, event_id: str) -> bool:
        """Claim *event_id* for *participant*: True the first time only."""

    async def prune(self, older_than: timedelta) -> int:
        """Delete finished transactions and handled deliveries older than *older_than*.

        Returns how many records were deleted. Bounded stores prune themselves.
        """
        return 0

    async def close(self) -> None:
        """Release connections."""
