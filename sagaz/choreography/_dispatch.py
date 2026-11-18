"""Delivering events to participants: idempotency, tenancy, failures and compensation.

Used by :class:`~sagaz.choreography.engine.ChoreographyEngine` for every event a
registered participant receives (ADR-029, #56).
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from sagaz.choreography.events import COMPENSATE, COMPENSATED, Event
from sagaz.choreography.saga import ChoreographedSaga, current_cause
from sagaz.core.tenant import tenant_scope

if TYPE_CHECKING:
    import prometheus_client

logger = logging.getLogger(__name__)

CHOREOGRAPHY_EVENTS: prometheus_client.Counter | None
CHOREOGRAPHY_HANDLER_SECONDS: prometheus_client.Histogram | None
CHOREOGRAPHY_COMPENSATIONS: prometheus_client.Counter | None

try:
    from prometheus_client import Counter, Histogram

    CHOREOGRAPHY_EVENTS = Counter(
        "sagaz_choreography_events_total",
        "Events delivered to choreography participants, by outcome",
        ["participant", "event_type", "outcome"],
    )
    CHOREOGRAPHY_HANDLER_SECONDS = Histogram(
        "sagaz_choreography_handler_seconds",
        "Time spent in choreography event handlers",
        ["participant", "event_type"],
    )
    CHOREOGRAPHY_COMPENSATIONS = Counter(
        "sagaz_choreography_compensations_total",
        "Compensations run by choreography participants, by outcome",
        ["participant", "outcome"],
    )
except ImportError:  # pragma: no cover - prometheus_client is optional
    CHOREOGRAPHY_EVENTS = CHOREOGRAPHY_HANDLER_SECONDS = CHOREOGRAPHY_COMPENSATIONS = None


def _count(participant: str, event_type: str, outcome: str) -> None:
    if CHOREOGRAPHY_EVENTS is not None:
        CHOREOGRAPHY_EVENTS.labels(participant, event_type, outcome).inc()


class Dispatcher:
    """Delivers one event to one participant, at most once per ``event_id``."""

    #: Delivered ``(participant, event_id)`` pairs remembered for deduplication.
    max_seen = 100_000

    def __init__(
        self, publish: Callable[[Event], Awaitable[None]], completion_events: frozenset[str]
    ) -> None:
        self._publish = publish
        self._completion_events = completion_events
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()

    def _first_delivery(self, saga: ChoreographedSaga, event: Event) -> bool:
        key = (saga.saga_id, event.event_id)
        if key in self._seen:
            return False
        self._seen[key] = None
        while len(self._seen) > self.max_seen:
            self._seen.popitem(last=False)
        return True

    async def dispatch(self, saga: ChoreographedSaga, event: Event) -> None:
        if not self._first_delivery(saga, event):
            _count(saga.name, event.event_type, "duplicate")
            return
        if event.event_type == COMPENSATE:
            await self._compensate(saga, event)
            return
        if saga.handles(event.event_type) and not self._after_compensation(saga, event):
            await self._handle(saga, event)
        if event.event_type in self._completion_events and event.saga_id:
            saga.forget(event.saga_id)

    @staticmethod
    def _after_compensation(saga: ChoreographedSaga, event: Event) -> bool:
        """True (and counted) if *saga* already compensated *event*'s transaction.

        Acting on such an event now would leave an effect nothing will undo, so
        it is not handled: compensation commutes with late events (#446).
        """
        if event.event_type == COMPENSATED or not saga.was_compensated(event.saga_id):
            return False
        _count(saga.name, event.event_type, "after_compensation")
        logger.warning(
            "%s ignores %r: transaction %s was already compensated",
            saga.name,
            event.event_type,
            event.saga_id,
        )
        return True

    async def _handle(self, saga: ChoreographedSaga, event: Event) -> None:
        token = current_cause.set(event)
        started = time.perf_counter()
        try:
            with tenant_scope(event.tenant_id):
                await saga.handle(event)
        except Exception as error:
            _count(saga.name, event.event_type, "failed")
            logger.exception(
                "%s failed on %r (saga_id=%s)", saga.name, event.event_type, event.saga_id
            )
            await self._publish_failure(saga, event, error)
        else:
            _count(saga.name, event.event_type, "handled")
        finally:
            current_cause.reset(token)
            if CHOREOGRAPHY_HANDLER_SECONDS is not None:
                CHOREOGRAPHY_HANDLER_SECONDS.labels(saga.name, event.event_type).observe(
                    time.perf_counter() - started
                )

    async def _publish_failure(
        self, saga: ChoreographedSaga, event: Event, error: Exception
    ) -> None:
        if not event.saga_id:
            return  # no transaction to compensate
        data: dict[str, Any] = {
            "participant": saga.name,
            "failed_event_type": event.event_type,
            "failed_event_id": event.event_id,
            "reason": f"{type(error).__name__}: {error}",
        }
        await self._publish(Event(COMPENSATE, data, source=saga.name).caused_by(event))

    async def _compensate(self, saga: ChoreographedSaga, event: Event) -> None:
        if not event.saga_id:
            return
        with tenant_scope(event.tenant_id):
            undone, failed = await saga.compensate_transaction(event.saga_id)
        if CHOREOGRAPHY_COMPENSATIONS is not None:
            if undone:
                CHOREOGRAPHY_COMPENSATIONS.labels(saga.name, "undone").inc(len(undone))
            if failed:
                CHOREOGRAPHY_COMPENSATIONS.labels(saga.name, "failed").inc(len(failed))
        data = {"participant": saga.name, "undone": undone, "failed": failed}
        await self._publish(Event(COMPENSATED, data, source=saga.name).caused_by(event))
