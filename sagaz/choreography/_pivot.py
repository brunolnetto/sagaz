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

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from sagaz.choreography._identity import names
from sagaz.choreography._observe import Listeners, with_trace_context
from sagaz.choreography.events import PIVOTED, Event
from sagaz.choreography.state import ParticipantState

logger = logging.getLogger("sagaz.choreography")


class Participant(Protocol):
    """What pivots and compensation read of a ``ChoreographedSaga`` (no import: no cycle)."""

    name: str
    formerly: tuple[str, ...]
    _pivots: set[str]
    _pivoting: set[str]
    _state: ParticipantState
    _publish: Callable[[Event], Awaitable[None]] | None
    _listeners: Listeners
    _compensators: dict[str, Any]
    _undo_policies: dict[str, tuple[int | None, float | None]]


#: Sources already reported for events without a lineage, per participant (bounded).
_REPORTED: set[tuple[str, str | None]] = set()
_REPORTED_LIMIT = 1_000


def lost_lineage(participant: str, event: Event) -> bool:
    """True if *event* has a cause and no lineage leading to it (logged once per source).

    Its producer is older than 2.6.0, or built the event without ``caused_by``. The
    actions before it cannot be recognised as a pivot's ancestors: a compensation
    would undo them (#571).
    """
    if event.causation_id is None:
        return False
    if event.lineage and event.lineage[-1][0] == event.causation_id:
        return False
    key = (participant, event.source)
    if key not in _REPORTED and len(_REPORTED) < _REPORTED_LIMIT:
        _REPORTED.add(key)
        logger.warning(
            "%s received %r from %r without the lineage of its cause: its producer is "
            "older than sagaz 2.6.0 or did not use caused_by(). If a pivot follows, the "
            "actions before this event are undone by a compensation instead of kept",
            participant,
            event.event_type,
            event.source,
        )
    return True


def fragile(saga: Participant, durable: bool) -> str | None:
    """Why *saga*'s pivots cannot be relied on as it is set up, or None."""
    if not saga._pivots or durable:
        return None
    return (
        f"{saga.name} has a pivot and keeps its state in memory: after a restart, or in "
        "another replica, it does not know what led to the pivot, and a compensation "
        "undoes it. Give the engine a durable state= or a saga_log="
    )


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
        mine = any((event.event_id, name) in committed for name in names(saga))
        if mine or event.event_type in saga._pivots:
            kept.append(event.event_type)
        else:
            undo.append(event)
    return undo, kept
