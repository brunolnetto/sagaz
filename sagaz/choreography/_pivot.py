"""Pivots in a choreography: a handler that is a point of no return (#571, ADR-023).

Once a pivot handler completes, what led to it is not undone. The participant that ran
it publishes ``choreography.pivoted``, and every participant then *commits* the actions
it had completed in that transaction: a later ``choreography.compensate`` leaves them
done. What a participant does after it learned of the pivot is still undone.

A participant only knows its own actions, so "what led to the pivot" is "what I had done
when I learned of it". For a chain of steps that is exactly the pivot's ancestors. An
action of a branch that ran in parallel with the pivot is committed too if it was done
by then.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Protocol

from sagaz.choreography._observe import Listeners, with_trace_context
from sagaz.choreography.events import PIVOTED, Event
from sagaz.choreography.state import ParticipantState

logger = logging.getLogger("sagaz.choreography")


class Participant(Protocol):
    """What pivots and compensation read of a ``ChoreographedSaga`` (no import: no cycle)."""

    name: str
    _pivots: set[str]
    _pivoting: set[str]
    _state: ParticipantState
    _publish: Callable[[Event], Awaitable[None]] | None
    _listeners: Listeners
    _compensators: dict[str, Any]
    _undo_policies: dict[str, tuple[int | None, float | None]]


_PIVOT_ID = "pivot_event_id"
_COMMITTED = "committed"


async def announce(saga: Participant, cause: Event | None) -> None:
    """Tell every participant that *saga*'s pivot on *cause* is done, once per handling.

    Called when the pivot handler emits its result (the local action is done, and on an
    in-process bus the rest of the transaction runs inside ``emit``) and when it returns.
    """
    if cause is None or not cause.saga_id or cause.event_type not in saga._pivots:
        return
    if cause.event_id in saga._pivoting or saga._publish is None:
        return
    saga._pivoting.add(cause.event_id)
    data = {
        "participant": saga.name,
        "pivot_event_type": cause.event_type,
        _PIVOT_ID: cause.event_id,
    }
    notice = with_trace_context(Event(PIVOTED, data, source=saga.name).caused_by(cause))
    await saga._state.publish(saga.name, notice, saga._publish)


async def commit(saga: Participant, notice: Event) -> None:
    """*saga* learned of a pivot: the actions it completed so far are not undone."""
    if not notice.saga_id:
        return
    done = await saga._state.actions(saga.name, notice.saga_id)
    pivot = notice.data.get(_PIVOT_ID)
    if any(e.event_type == PIVOTED and e.data.get(_PIVOT_ID) == pivot for e in done):
        return  # announced again by a retried handler: what came after stays undoable
    committed = [e.event_id for e in done if e.event_type != PIVOTED]
    record = replace(notice, data={**notice.data, _COMMITTED: committed})
    await saga._state.record_action(saga.name, record)
    if committed:
        logger.info(
            "%s keeps %d action(s) of %s: %s completed a pivot",
            saga.name,
            len(committed),
            notice.saga_id,
            notice.data.get("participant"),
        )


def split(saga: Participant, done: list[Event]) -> tuple[list[Event], list[str]]:
    """*done*, a participant's record of a transaction, as (actions to undo, types kept).

    Kept: the actions committed by a pivot, and the participant's own pivot actions.
    """
    committed: set[str] = set()
    for event in done:
        if event.event_type == PIVOTED:
            committed.update(event.data.get(_COMMITTED) or ())
    undo: list[Event] = []
    kept: list[str] = []
    for event in done:
        if event.event_type == PIVOTED:
            continue
        if event.event_id in committed or event.event_type in saga._pivots:
            kept.append(event.event_type)
        else:
            undo.append(event)
    return undo, kept
