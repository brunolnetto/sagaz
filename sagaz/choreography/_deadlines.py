"""Deadlines of choreographed transactions (#449).

The participant that starts a transaction with ``begin(..., deadline=...)``
owns its time limit. Its engine's :class:`DeadlineWatcher` claims expired
deadlines from the participant state and publishes ``choreography.compensate``
on the participant's behalf. A claim holds for ``lease`` seconds, so one replica
publishes. If that replica dies first, another publishes after the lease.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta

from sagaz.choreography import _dispatch
from sagaz.choreography.events import COMPENSATE, Event
from sagaz.choreography.saga import ChoreographedSaga
from sagaz.choreography.state import ParticipantState
from sagaz.core.tenant import system_scope, tenant_scope

logger = logging.getLogger(__name__)

#: ``reason`` of the compensation published when a deadline expires.
DEADLINE_EXCEEDED = "deadline exceeded"


class DeadlineWatcher:
    """Publishes compensation for the expired deadlines of some participants."""

    def __init__(
        self,
        publish: Callable[[Event], Awaitable[None]],
        participants: Callable[[], Iterable[ChoreographedSaga]],
        *,
        poll_interval: float = 1.0,
        lease: float = 60.0,
    ) -> None:
        self._publish = publish
        self._participants = participants
        self.poll_interval = poll_interval
        self.lease = timedelta(seconds=lease)
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start polling (idempotent; needs a running event loop)."""
        if not self.running:
            self._task = asyncio.get_running_loop().create_task(self._poll())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _poll(self) -> None:
        while True:
            try:
                await self.expire()
            except Exception:
                logger.exception("Checking choreography deadlines failed")
            await asyncio.sleep(self.poll_interval)

    async def expire(self, now: datetime | None = None) -> int:
        """Compensate the transactions whose deadline passed; return how many."""
        now = now or datetime.now(UTC)
        expired = 0
        for state, names in self._by_state().items():
            with system_scope():  # deadlines of every tenant
                due = await state.claim_due_deadlines(names, now, self.lease)
            for deadline in due:
                event = Event(
                    COMPENSATE,
                    {
                        "participant": deadline.participant,
                        "reason": DEADLINE_EXCEEDED,
                        "deadline": deadline.due_at.isoformat(),
                    },
                    saga_id=deadline.correlation_id,
                    tenant_id=deadline.tenant_id,
                    source=deadline.participant,
                )
                logger.warning(
                    "Transaction %s exceeded its deadline (%s); compensating",
                    deadline.correlation_id,
                    deadline.participant,
                )
                with tenant_scope(deadline.tenant_id):
                    # Through the owner's state: on the unified saga log the
                    # compensation request is logged and published atomically.
                    await state.publish(deadline.participant, event, self._publish)
                if _dispatch.CHOREOGRAPHY_DEADLINES is not None:
                    _dispatch.CHOREOGRAPHY_DEADLINES.labels(deadline.participant).inc()
                expired += 1
        return expired

    def _by_state(self) -> dict[ParticipantState, set[str]]:
        groups: dict[ParticipantState, set[str]] = {}
        for participant in self._participants():
            groups.setdefault(participant._state, set()).add(participant.name)
        return groups
