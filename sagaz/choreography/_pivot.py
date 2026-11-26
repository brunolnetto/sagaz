"""Pivots in a choreography: a handler that is a point of no return (#571, ADR-023).

Once a pivot handler completes, what led to it is not undone. The participant that ran
it publishes ``choreography.pivoted``, an event caused by the one the pivot handled, so
its ``lineage`` names every action the pivot descends from: which participant handled
which event. Each participant records the notice, and a later ``choreography.compensate``
leaves done its actions named there: the pivot's ancestors, exactly, as in an
orchestrated saga. Everything else (what followed the pivot, and branches beside it,
even one that handled the same event) is still undone.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from sagaz.choreography._observe import Listeners, with_trace_context
from sagaz.choreography.events import PIVOTED, Event
from sagaz.choreography.state import ParticipantState


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
        "pivot_event_id": cause.event_id,
    }
    notice = with_trace_context(Event(PIVOTED, data, source=saga.name).caused_by(cause))
    await saga._state.publish(saga.name, notice, saga._publish)


async def commit(saga: Participant, notice: Event) -> None:
    """*saga* learned of a pivot: it remembers the notice, whose lineage says what stays."""
    if notice.saga_id:
        await saga._state.record_action(saga.name, notice)


def split(saga: Participant, done: list[Event]) -> tuple[list[Event], list[str]]:
    """*done*, a participant's record of a transaction, as (actions to undo, types kept).

    Kept: the actions triggered by an event a completed pivot descends from, and the
    participant's own pivot actions.
    """
    committed: set[tuple[str, str | None]] = set()
    for event in done:
        if event.event_type == PIVOTED:  # the pivot's action, and those it descends from
            committed.update(event.lineage)
    undo: list[Event] = []
    kept: list[str] = []
    for event in done:
        if event.event_type == PIVOTED:
            continue
        if (event.event_id, saga.name) in committed or event.event_type in saga._pivots:
            kept.append(event.event_type)
        else:
            undo.append(event)
    return undo, kept
