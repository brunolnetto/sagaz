"""Delivering events to participants: idempotency, tenancy, failures and compensation.

Used by :class:`~sagaz.choreography.engine.ChoreographyEngine` for every event a
registered participant receives (ADR-029, #56).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sagaz.choreography._attempts import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF_BASE,
    DEFAULT_TIMEOUT,
)
from sagaz.choreography.events import COMPENSATE, COMPENSATED, Event
from sagaz.choreography.saga import ChoreographedSaga, current_cause
from sagaz.core.tenant import tenant_scope

if TYPE_CHECKING:
    import prometheus_client

logger = logging.getLogger(__name__)

CHOREOGRAPHY_EVENTS: prometheus_client.Counter | None
CHOREOGRAPHY_HANDLER_SECONDS: prometheus_client.Histogram | None
CHOREOGRAPHY_COMPENSATIONS: prometheus_client.Counter | None
CHOREOGRAPHY_DEADLINES: prometheus_client.Counter | None

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
    CHOREOGRAPHY_DEADLINES = Counter(
        "sagaz_choreography_deadlines_expired_total",
        "Choreographed transactions compensated because their deadline expired",
        ["participant"],
    )
except ImportError:  # pragma: no cover - prometheus_client is optional
    CHOREOGRAPHY_EVENTS = CHOREOGRAPHY_HANDLER_SECONDS = CHOREOGRAPHY_COMPENSATIONS = None
    CHOREOGRAPHY_DEADLINES = None


def _count(participant: str, event_type: str, outcome: str) -> None:
    if CHOREOGRAPHY_EVENTS is not None:
        CHOREOGRAPHY_EVENTS.labels(participant, event_type, outcome).inc()


#: Added to the time all attempts of a handler may take, for its delivery's lease.
LEASE_MARGIN = 60.0
#: The lease of a delivery whose handler has no timeout.
UNBOUNDED_LEASE = 3600.0


@dataclass(frozen=True)
class RetryDefaults:
    """The engine's retry settings for handlers that do not set their own (#561).

    *delivery_lease*, when set, is the reservation of every delivery (seconds);
    otherwise :meth:`lease` derives it from the handler's retries and timeout.
    """

    max_retries: int = DEFAULT_MAX_RETRIES
    timeout_seconds: float | None = DEFAULT_TIMEOUT
    retry_backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE
    delivery_lease: float | None = None

    def lease(self, max_retries: int, timeout_seconds: float | None) -> timedelta:
        """How long a delivery stays reserved: long enough for all its attempts."""
        if self.delivery_lease is not None:
            return timedelta(seconds=self.delivery_lease)
        if timeout_seconds is None:
            return timedelta(seconds=UNBOUNDED_LEASE)
        backoffs = sum(self.retry_backoff_base * 2**n for n in range(max_retries))
        return timedelta(seconds=(max_retries + 1) * timeout_seconds + backoffs + LEASE_MARGIN)


class Dispatcher:
    """Delivers one event to one participant, once per ``event_id``.

    A delivery is reserved while it is handled (a lease, #561): a duplicate
    arriving meanwhile is dropped, and a redelivery after a crash is handled
    once the reservation expired. When handled (or its failure reported), it
    is done for good. Deduplication, completed actions and tombstones live in
    the participant's state (#448), in the event's tenant scope.
    """

    def __init__(
        self,
        publish: Callable[[Event], Awaitable[None]],
        completion_events: frozenset[str],
        defaults: RetryDefaults | None = None,
    ) -> None:
        self._publish = publish
        self._completion_events = completion_events
        self._defaults = defaults or RetryDefaults()

    async def dispatch(self, saga: ChoreographedSaga, event: Event) -> None:
        with tenant_scope(event.tenant_id):
            await self._dispatch(saga, event)

    def _policy(self, saga: ChoreographedSaga, event: Event) -> tuple[int, float | None]:
        """The handler's ``(max_retries, timeout_seconds)``, the engine's where unset."""
        max_retries, timeout_seconds = saga.retry_policy(event.event_type)
        return (
            self._defaults.max_retries if max_retries is None else max_retries,
            self._defaults.timeout_seconds if timeout_seconds is None else timeout_seconds,
        )

    async def _dispatch(self, saga: ChoreographedSaga, event: Event) -> None:
        if event.event_type == COMPENSATE:
            lease = self._defaults.lease(self._defaults.max_retries, self._defaults.timeout_seconds)
        else:
            lease = self._defaults.lease(*self._policy(saga, event))
        if not await saga._state.claim_delivery(saga.name, event.event_id, lease):
            _count(saga.name, event.event_type, "duplicate")
            return
        # Every path below finishes the delivery; only a crash (or cancellation)
        # leaves the reservation to expire, so that a redelivery is handled.
        if event.event_type == COMPENSATE:
            await self._compensate(saga, event)
            await saga._state.finish_delivery(saga.name, event.event_id)
            return
        if saga.handles(event.event_type) and not await self._after_compensation(saga, event):
            await self._handle(saga, event)  # raises only if its failure was not reported
        await saga._state.finish_delivery(saga.name, event.event_id)
        if event.event_type in self._completion_events and event.saga_id:
            await saga.forget(event.saga_id)

    @staticmethod
    async def _after_compensation(saga: ChoreographedSaga, event: Event) -> bool:
        """True (and counted) if *saga* already compensated *event*'s transaction.

        Acting on such an event now would leave an effect nothing will undo, so
        it is not handled: compensation commutes with late events (#446).
        """
        if event.event_type == COMPENSATED or not await saga.was_compensated(event.saga_id):
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
            max_retries, timeout_seconds = self._policy(saga, event)
            with tenant_scope(event.tenant_id):
                await saga._run(
                    event,
                    max_retries=max_retries,
                    timeout_seconds=timeout_seconds,
                    retry_backoff_base=self._defaults.retry_backoff_base,
                )
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
        report = Event(COMPENSATE, data, source=saga.name).caused_by(event)
        await saga._state.publish(saga.name, report, self._publish)

    async def _compensate(self, saga: ChoreographedSaga, event: Event) -> None:
        if not event.saga_id:
            return
        with tenant_scope(event.tenant_id):
            undone, failed = await saga.compensate_transaction(
                event.saga_id,
                max_retries=self._defaults.max_retries,
                timeout_seconds=self._defaults.timeout_seconds,
                retry_backoff_base=self._defaults.retry_backoff_base,
            )
        if CHOREOGRAPHY_COMPENSATIONS is not None:
            if undone:
                CHOREOGRAPHY_COMPENSATIONS.labels(saga.name, "undone").inc(len(undone))
            if failed:
                CHOREOGRAPHY_COMPENSATIONS.labels(saga.name, "failed").inc(len(failed))
        data = {"participant": saga.name, "undone": undone, "failed": failed}
        report = Event(COMPENSATED, data, source=saga.name).caused_by(event)
        await saga._state.publish(saga.name, report, self._publish)
