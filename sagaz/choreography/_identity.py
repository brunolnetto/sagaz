"""Who a choreography participant is: its names, and the service that owns them (#571).

A participant is known by its ``name``: its state is kept under it, and the lineage of
events names it. Two things can go wrong with a name, and each has its guard here.

- **It changes.** A participant renamed while transactions are in flight would no
  longer recognise its own actions. ``formerly=`` lists the names it had: it reads its
  state, and recognises itself in a lineage, under any of them.
- **Two services use the same one.** Replicas of a service share a name on purpose; two
  different services must not. An engine refuses two participants with one name, and,
  given ``service=``, engines announce their participants on the bus and report a name
  claimed by another service.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any, Protocol
from uuid import uuid4

from sagaz.choreography.events import PARTICIPANT, AbstractEventBus, Event
from sagaz.choreography.state import ParticipantState
from sagaz.core.exceptions import SagaDefinitionError
from sagaz.core.storage._reserved import RESERVED_SAGA_PREFIX

logger = logging.getLogger("sagaz.choreography")


class Named(Protocol):
    """What identity reads of a ``ChoreographedSaga`` (no import: no cycle)."""

    name: str
    formerly: tuple[str, ...]
    _state: ParticipantState


def identify(name: str, formerly: Iterable[str] = ()) -> tuple[str, tuple[str, ...]]:
    """*name* and the names the participant had before, checked."""
    former = tuple(dict.fromkeys(formerly))
    for each in (name, *former):
        if each.startswith(RESERVED_SAGA_PREFIX):
            msg = f"participant names starting with {RESERVED_SAGA_PREFIX!r} are reserved"
            raise SagaDefinitionError(msg)
    if name in former:
        msg = f"{name!r} is the participant's name: formerly= lists the names it no longer has"
        raise SagaDefinitionError(msg)
    return name, former


def names(saga: Named) -> tuple[str, ...]:
    """Every name *saga* answers to: the current one first."""
    return (saga.name, *saga.formerly)


async def finish(saga: Named, correlation_id: str, *, compensated: bool) -> list[Event]:
    """End *saga*'s part of *correlation_id* under every name; its actions, oldest first."""
    done: list[Event] = []
    for name in reversed(names(saga)):  # what it did under an older name came first
        done += await saga._state.finish(name, correlation_id, compensated=compensated)
    return done


async def was_compensated(saga: Named, correlation_id: str) -> bool:
    """True if *saga* compensated *correlation_id*, under any of its names."""
    for name in names(saga):
        if await saga._state.was_compensated(name, correlation_id):
            return True
    return False


def claim(saga: Named, registered: Iterable[Named]) -> None:
    """Refuse *saga* if a participant already registered answers to one of its names."""
    mine = set(names(saga))
    for other in registered:
        shared = sorted(mine & set(names(other)))
        if other is not saga and shared:
            msg = (
                f"two participants answer to the name {shared[0]!r}: they would share their "
                "state and be taken for each other. Give each a name= of its own"
            )
            raise SagaDefinitionError(msg)


class Identity:
    """Announces an engine's participants, and reports names another service claims.

    Without a *service* nothing is announced: a replica cannot be told from a stranger.
    """

    def __init__(
        self, bus: AbstractEventBus, service: str | None, participants: Callable[[], Iterable[Any]]
    ) -> None:
        self._bus = bus
        self.service = service
        self._participants = participants
        self._engine = str(uuid4())
        #: Names of this engine's participants that another service announced.
        self.conflicts: list[dict[str, Any]] = []

    async def start(self) -> None:
        if self.service is None:
            return
        self._bus.subscribe(PARTICIPANT, self._hear)
        await self._announce()

    async def stop(self) -> None:
        if self.service is not None:
            self._bus.unsubscribe(PARTICIPANT, self._hear)

    async def _announce(self) -> None:
        for saga in list(self._participants()):
            data = {"engine": self._engine, "service": self.service, "names": list(names(saga))}
            await self._bus.publish(Event(PARTICIPANT, data, source=saga.name))

    async def _hear(self, event: Event) -> None:
        theirs = event.data.get("service")
        if event.data.get("engine") == self._engine or theirs == self.service:
            return  # this engine, or a replica of this service
        mine = {name for saga in self._participants() for name in names(saga)}
        new = False
        for name in sorted(mine & set(event.data.get("names") or ())):
            conflict = {"name": name, "service": theirs}
            if conflict not in self.conflicts:
                new = True
                self.conflicts.append(conflict)
                logger.error(
                    "participant name %r is claimed by service %r and by this one (%r): "
                    "they share state and are taken for each other. Rename one of them",
                    name,
                    theirs,
                    self.service,
                )
        if new:  # the other service may have started after this one announced
            await self._announce()
