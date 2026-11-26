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
from sagaz.choreography._compensation import compensate_all
from sagaz.choreography._observe import listener_context, notify, span, with_trace_context
from sagaz.choreography._pivot import commit, lost_lineage
from sagaz.choreography._tenancy import REFUSED, Tenancy
from sagaz.choreography.events import COMPENSATE, COMPENSATED, PIVOTED, Event
from sagaz.choreography.saga import ChoreographedSaga, current_cause
from sagaz.core.tenant import tenant_scope

if TYPE_CHECKING:
    import prometheus_client

logger = logging.getLogger(__name__)

CHOREOGRAPHY_EVENTS: prometheus_client.Counter | None
CHOREOGRAPHY_HANDLER_SECONDS: prometheus_client.Histogram | None
CHOREOGRAPHY_COMPENSATIONS: prometheus_client.Counter | None
CHOREOGRAPHY_DEADLINES: prometheus_client.Counter | None
CHOREOGRAPHY_LOST_LINEAGE: prometheus_client.Counter | None

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
    CHOREOGRAPHY_LOST_LINEAGE = Counter(
        "sagaz_choreography_events_without_lineage_total",
        "Events delivered with a cause and no lineage leading to it (an older producer)",
        ["participant", "source"],
    )
except ImportError:  # pragma: no cover - prometheus_client is optional
    CHOREOGRAPHY_EVENTS = CHOREOGRAPHY_HANDLER_SECONDS = CHOREOGRAPHY_COMPENSATIONS = None
    CHOREOGRAPHY_DEADLINES = CHOREOGRAPHY_LOST_LINEAGE = None


def _check_lineage(participant: str, event: Event) -> None:
    """Count (and log, once per source) an event whose lineage was lost on the way (#571)."""
    if lost_lineage(participant, event) and CHOREOGRAPHY_LOST_LINEAGE is not None:
        CHOREOGRAPHY_LOST_LINEAGE.labels(participant, event.source or "").inc()


def _count(participant: str, event_type: str, outcome: str) -> None:
    if CHOREOGRAPHY_EVENTS is not None:
        CHOREOGRAPHY_EVENTS.labels(participant, event_type, outcome).inc()


#: Never refused nor queued for a tenant: they undo, or record what is not undone.
_CONTROL = (COMPENSATE, COMPENSATED, PIVOTED)

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
        tenancy: Tenancy | None = None,
    ) -> None:
        self._publish = publish
        self._completion_events = completion_events
        self._defaults = defaults or RetryDefaults()
        self._tenancy = tenancy or Tenancy()

    async def dispatch(self, saga: ChoreographedSaga, event: Event) -> None:
        """Deliver *event* to *saga* as its tenant (#564).

        Undoing is never refused nor queued: compensation runs whatever the tenant's
        state. For the rest, a tenant the registry refuses is not run (the participant
        asks for compensation instead), and a transaction waits for a quota slot.
        """
        _check_lineage(saga.name, event)
        if event.event_type in _CONTROL or not saga.handles(event.event_type):
            with tenant_scope(self._tenancy.context(event.tenant_id)):
                await self._dispatch(saga, event)
            return
        try:
            tenant = self._tenancy.resolve(event.tenant_id)
        except REFUSED as error:
            with tenant_scope(event.tenant_id):
                await self._refuse(saga, event, error)
            return
        async with self._tenancy.transaction(tenant, event.saga_id, wait=True):
            with tenant_scope(tenant):
                await self._dispatch(saga, event)

    async def _refuse(self, saga: ChoreographedSaga, event: Event, error: Exception) -> None:
        """Do not run *saga*'s handler for a refused tenant: ask for compensation."""
        lease = self._defaults.lease(*self._policy(saga, event))
        if not await saga._state.claim_delivery(saga.name, event.event_id, lease):
            _count(saga.name, event.event_type, "duplicate")
            return
        _count(saga.name, event.event_type, "tenant_refused")
        logger.warning("%s refuses %r: %s", saga.name, event.event_type, error)
        await self._publish_failure(saga, event, error)
        await saga._state.finish_delivery(saga.name, event.event_id)

    def _policy(self, saga: ChoreographedSaga, event: Event) -> tuple[int, float | None]:
        """The handler's ``(max_retries, timeout_seconds)``, the engine's where unset."""
        max_retries, timeout_seconds = saga.retry_policy(event.event_type)
        return (
            self._defaults.max_retries if max_retries is None else max_retries,
            self._defaults.timeout_seconds if timeout_seconds is None else timeout_seconds,
        )

    async def _dispatch(self, saga: ChoreographedSaga, event: Event) -> None:
        if event.event_type in (COMPENSATE, PIVOTED):
            lease = self._defaults.lease(self._defaults.max_retries, self._defaults.timeout_seconds)
        else:
            lease = self._defaults.lease(*self._policy(saga, event))
        if not await saga._state.claim_delivery(saga.name, event.event_id, lease):
            _count(saga.name, event.event_type, "duplicate")
            return
        # Every path below finishes the delivery; only a crash (or cancellation)
        # leaves the reservation to expire, so that a redelivery is handled.
        if event.event_type == COMPENSATE:
            with span(saga.name, event, "compensate transaction"):
                await self._compensate(saga, event)
            await saga._state.finish_delivery(saga.name, event.event_id)
            return
        if event.event_type == PIVOTED:
            await commit(saga, event)  # what this participant did so far stays done (#571)
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
        ctx = listener_context(event)
        await notify(saga._listeners, "on_step_enter", saga.name, event.event_type, ctx)
        try:
            # The handler, its follow-on events and its failure report are in one
            # span, continuing the trace of the span that published *event* (#563).
            with span(saga.name, event, "handle") as outcome:
                try:
                    await self._run(saga, event)
                except Exception as error:
                    outcome.failed(error)
                    await self._failed(saga, event, ctx, error)
                else:
                    _count(saga.name, event.event_type, "handled")
                    await notify(
                        saga._listeners, "on_step_success", saga.name, event.event_type, ctx, None
                    )
        finally:
            current_cause.reset(token)
            if CHOREOGRAPHY_HANDLER_SECONDS is not None:
                CHOREOGRAPHY_HANDLER_SECONDS.labels(saga.name, event.event_type).observe(
                    time.perf_counter() - started
                )

    async def _run(self, saga: ChoreographedSaga, event: Event) -> None:
        max_retries, timeout_seconds = self._policy(saga, event)
        # In the tenant scope dispatch() set, with its TenantContext: its quotas cap these.
        await saga._run(
            event,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            retry_backoff_base=self._defaults.retry_backoff_base,
        )

    async def _failed(
        self, saga: ChoreographedSaga, event: Event, ctx: dict[str, Any], error: Exception
    ) -> None:
        _count(saga.name, event.event_type, "failed")
        logger.exception("%s failed on %r (saga_id=%s)", saga.name, event.event_type, event.saga_id)
        await notify(saga._listeners, "on_step_failure", saga.name, event.event_type, ctx, error)
        await self._publish_failure(saga, event, error)

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
        report = with_trace_context(Event(COMPENSATE, data, source=saga.name).caused_by(event))
        await saga._state.publish(saga.name, report, self._publish)

    async def _compensate(self, saga: ChoreographedSaga, event: Event) -> None:
        if not event.saga_id:
            return
        undone, failed, kept = await compensate_all(  # in dispatch()'s tenant scope
            saga,
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
            if kept:
                CHOREOGRAPHY_COMPENSATIONS.labels(saga.name, "kept").inc(len(kept))
        data = {"participant": saga.name, "undone": undone, "failed": failed, "kept": kept}
        report = with_trace_context(Event(COMPENSATED, data, source=saga.name).caused_by(event))
        await saga._state.publish(saga.name, report, self._publish)
