"""The ``ChoreographyTracker``'s listener hooks: whole transactions, once each (#563).

A participant does not see the whole transaction, so ``on_saga_start``,
``on_saga_complete`` and ``on_saga_failed`` come from the tracker, the one observer of
every event, on the status transitions it records.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

from sagaz.choreography._observe import Listeners, notify
from sagaz.choreography._status import COMPLETED, FAILED, RECORD_NAME, ROLLED_BACK


class TransactionStatus(Protocol):
    """What the hooks read of a ``tracker.TransactionStatus`` (no import: no cycle)."""

    correlation_id: str
    tenant_id: str
    status: str
    participants: list[str]
    failure: dict[str, Any] | None

    def initiators(self) -> list[str]: ...


#: Transactions remembered as announced, so that a redelivered first event is not.
ANNOUNCED_LIMIT = 10_000


@dataclass(frozen=True)
class Change:
    """What observing one event did to its transaction."""

    started: bool  # the transaction was first recorded by this event
    before: str | None  # its status before (None if it was not known)
    status: TransactionStatus


async def announce(listeners: Listeners, announced: OrderedDict[str, None], change: Change) -> None:
    """Tell *listeners* what *change* means for the whole transaction.

    *announced* holds the transactions whose start was already announced (bounded).
    """
    status = change.status
    key = status.correlation_id
    ctx: dict[str, Any] = {
        "saga_id": key,
        "tenant_id": status.tenant_id,
        "initiators": status.initiators(),
        "participants": list(status.participants),
        "status": status.status,
    }
    if change.started and key not in announced:
        announced[key] = None
        while len(announced) > ANNOUNCED_LIMIT:
            announced.popitem(last=False)
        await notify(listeners, "on_saga_start", RECORD_NAME, key, ctx)
    if change.before == status.status:
        return
    if status.status == COMPLETED:
        await notify(listeners, "on_saga_complete", RECORD_NAME, key, ctx)
    elif status.status in (ROLLED_BACK, FAILED):
        await notify(listeners, "on_saga_failed", RECORD_NAME, key, ctx, failure_error(status))


def failure_error(status: TransactionStatus) -> Exception:
    """The error an ``on_saga_failed`` listener gets: the failing participant's report."""
    from sagaz.core.exceptions import SagaExecutionError

    failure = status.failure or {}
    reason = failure.get("reason") or "the transaction was compensated"
    where = failure.get("participant")
    message = f"{where}: {reason}" if where else str(reason)
    if status.status == FAILED:
        message += " (and a compensation failed too)"
    return SagaExecutionError(message)
