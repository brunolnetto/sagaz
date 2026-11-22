"""
ChoreographyEngine — wires ChoreographedSagas to an EventBus.

The engine manages saga lifecycle: registering their event handlers with the
bus and tracking active saga instances.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from sagaz.choreography._attempts import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF_BASE,
    DEFAULT_TIMEOUT,
)
from sagaz.choreography._deadlines import DeadlineWatcher
from sagaz.choreography._dispatch import Dispatcher, RetryDefaults
from sagaz.choreography._observe import DEFAULT_LISTENER_TIMEOUT, Listeners
from sagaz.choreography.events import COMPENSATE, AbstractEventBus, Event, HandlerT
from sagaz.choreography.relay import ChoreographyRelay
from sagaz.choreography.saga import ChoreographedSaga
from sagaz.choreography.state import ParticipantState, create_participant_state

if TYPE_CHECKING:
    from sagaz.core.listeners import SagaListener
    from sagaz.core.storage.saga_log import SagaLogStore

logger = logging.getLogger(__name__)


class ChoreographyEngine:
    """
    Routes events from an ``EventBus`` to registered ``ChoreographedSaga``
    instances.

    Parameters
    ----------
    bus:
        The ``EventBus`` to subscribe to.
    completion_events:
        Event types that end a transaction successfully (e.g. ``"order.shipped"``);
        participants then forget what they would have compensated, and the
        transaction's deadline is cleared.
    state:
        Where registered participants keep their completed actions, tombstones
        and handled deliveries: a ``ParticipantState`` or a URL
        (``sqlite://...``, ``postgresql://...``). Default: each participant's
        own memory, lost on restart. A shared durable state lets replicas of a
        participant compensate each other's actions (#448).
    saga_log:
        A ``SagaLogStore`` or URL (ADR-041): participant state lives on the
        unified saga log, and every published event is written to the log and
        its outbox in one database transaction. ``engine.relay`` then publishes
        the outbox on *bus*, every *relay_interval* seconds while the engine
        runs (or call ``await engine.relay.relay()``).
    deadline_poll_interval / deadline_lease:
        How often expired deadlines (``begin(..., deadline=...)``) are checked,
        and for how long a replica's claim on one holds (seconds, #449).
    default_max_retries / default_timeout / retry_backoff_base:
        For a handler that does not set ``max_retries`` / ``timeout_seconds``: it runs
        ``default_max_retries + 1`` times at most (3 retries), each attempt under
        ``default_timeout`` seconds (60; ``None`` for no limit), waiting
        ``retry_backoff_base * 2**n`` seconds between attempts (#561), as an
        orchestrated step does. Since 2.6.0; before, a handler ran once. A handler
        with a non-idempotent external effect should set ``max_retries=0``.
    delivery_lease:
        How long a delivery stays reserved while its handler runs (seconds, #561).
        If the process dies meanwhile, the broker's redelivery is handled once
        the reservation expired; a duplicate arriving before is dropped. Default
        ``None``: long enough for all the handler's attempts (``(max_retries + 1)
        * timeout`` plus the backoffs and a minute), or an hour for a handler
        without a timeout. When given, it is the reservation of every delivery.
    listeners:
        ``SagaListener`` instances (``LoggingSagaListener``, ``MetricsSagaListener``,
        your own) told what each registered participant does (#563): its steps
        (``on_step_*``: the saga name is the participant's name, a step is the event
        type it handles, the saga id is the correlation id) and its compensations
        (``on_compensation_*``). A participant does not see the whole transaction,
        so the ``on_saga_*`` hooks come from a ``ChoreographyTracker``'s listeners,
        once per transaction. A listener that raises is logged and ignored.
    listener_timeout:
        Seconds an async listener call may take (default 5): listeners run on the
        hot path, so a slower one is cancelled, logged and skipped. ``None``
        waits as long as it takes.

    Handlers and compensations also run in OpenTelemetry spans when
    ``opentelemetry`` is installed: an event carries its publisher's trace
    context, so a transaction is one trace across participants and services.

    Each delivery is deduplicated by ``event_id`` and runs in the event's tenant
    scope. If a handler still raises after its retries, the engine publishes a
    ``COMPENSATE`` event and every participant undoes its ``@compensate`` actions
    for that transaction.

    Example
    -------
    ::

        bus = EventBus()
        engine = ChoreographyEngine(bus)

        class MySaga(ChoreographedSaga):
            @on_event("order.created")
            async def handle_order(self, event: Event) -> None:
                await bus.publish(Event("payment.initiate", event.data))

        engine.register(MySaga())
        await engine.start()
        await bus.publish(Event("order.created", {"order_id": "ORD-1"}))
        await engine.stop()
    """

    def __init__(
        self,
        bus: AbstractEventBus,
        *,
        completion_events: Iterable[str] = (),
        state: ParticipantState | str | None = None,
        deadline_poll_interval: float = 1.0,
        deadline_lease: float = 60.0,
        saga_log: SagaLogStore | str | None = None,
        relay_interval: float = 0.1,
        default_max_retries: int = DEFAULT_MAX_RETRIES,
        default_timeout: float | None = DEFAULT_TIMEOUT,
        delivery_lease: float | None = None,
        retry_backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE,
        listeners: Iterable[SagaListener] = (),
        listener_timeout: float | None = DEFAULT_LISTENER_TIMEOUT,
    ) -> None:
        self._bus = bus
        self._listeners = Listeners(listeners, listener_timeout)
        #: The engine's listeners; add to it before registering participants.
        self.listeners: list[SagaListener] = self._listeners.items
        self._state = create_participant_state(state) if isinstance(state, str) else state
        self.relay: ChoreographyRelay | None = None
        if saga_log is not None:  # ADR-041: state and atomic publishing on the log
            if isinstance(saga_log, str):
                from sagaz.core.storage.saga_log import create_saga_log_store

                saga_log = create_saga_log_store(saga_log)
            from sagaz.choreography.state.unified import UnifiedParticipantState

            self._state = UnifiedParticipantState(saga_log)
            self.relay = ChoreographyRelay(
                saga_log.outbox_storage(), bus, poll_interval=relay_interval
            )
        self._completion_events = frozenset(completion_events)
        self._dispatcher = Dispatcher(
            bus.publish,
            self._completion_events,
            RetryDefaults(default_max_retries, default_timeout, retry_backoff_base, delivery_lease),
        )
        self._sagas: dict[str, ChoreographedSaga] = {}
        self._running = False
        # Tracks dispatch closures created per saga so they can be properly unsubscribed.
        self._closures: dict[str, dict[str, HandlerT]] = {}
        self.deadlines = DeadlineWatcher(
            bus.publish,
            lambda: self._sagas.values(),
            poll_interval=deadline_poll_interval,
            lease=deadline_lease,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Mark the engine as running (enables event dispatch)."""
        self._running = True
        if self._state is not None:  # deadlines may outlive a restart
            self.deadlines.start()
        if self.relay is not None:
            await self.relay.start()
        logger.info("ChoreographyEngine started with %d saga(s)", len(self._sagas))

    async def stop(self) -> None:
        """Deregister all sagas and shut down the engine."""
        await self.deadlines.stop()
        if self.relay is not None:
            await self.relay.close()
        for saga in list(self._sagas.values()):
            self._deregister(saga)
        self._sagas.clear()
        self._running = False
        logger.info("ChoreographyEngine stopped")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, saga: ChoreographedSaga) -> None:
        """
        Register *saga* and subscribe its handlers to the bus.

        Parameters
        ----------
        saga:
            A ``ChoreographedSaga`` instance with ``@on_event``-decorated
            methods.
        """
        if saga.saga_id in self._sagas:
            logger.warning("Saga %r is already registered; replacing.", saga.saga_id)
            self._deregister(self._sagas[saga.saga_id])

        self._sagas[saga.saga_id] = saga
        saga._publish = self._bus.publish
        saga._watch_deadlines = self._watch_deadlines
        saga._listeners = self._listeners
        if self._state is not None:
            saga._state = self._state

        for event_type in self._subscriptions(saga):
            # Capture saga via default arg to avoid closure-over-loop-variable.
            async def _dispatch(event: Event, _saga: ChoreographedSaga = saga) -> None:
                await self._dispatcher.dispatch(_saga, event)

            # Store the closure so _deregister() can later call bus.unsubscribe().
            self._closures.setdefault(saga.saga_id, {})[event_type] = _dispatch
            self._bus.subscribe(event_type, _dispatch)

        logger.debug("Registered saga %r (%s)", saga.saga_id, saga.name)

    def _watch_deadlines(self) -> None:
        """A participant set a deadline: poll for expiry while the engine runs."""
        if self._running:
            self.deadlines.start()

    def _subscriptions(self, saga: ChoreographedSaga) -> list[str]:
        """Event types to route to *saga*: its handlers, compensation, and completion.

        Every participant receives ``COMPENSATE`` (and reports, even with nothing to
        undo) so a tracker can tell when a failed transaction is fully compensated.
        """
        # Completion events also clear the deadline of the participant that began
        # the transaction, so every participant receives them.
        types = [*saga._handlers, COMPENSATE, *sorted(self._completion_events)]
        return list(dict.fromkeys(types))

    def _deregister(self, saga: ChoreographedSaga) -> None:
        """Unsubscribe the saga's dispatch closures from the bus."""
        closures = self._closures.pop(saga.saga_id, {})
        for event_type, closure in closures.items():
            self._bus.unsubscribe(event_type, closure)
        logger.debug("Deregistered saga %r", saga.saga_id)

    def unregister(self, saga_id: str) -> None:
        """Remove a saga from the engine by its *saga_id*."""
        saga = self._sagas.pop(saga_id, None)
        if saga:
            self._deregister(saga)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def registered_sagas(self) -> list[ChoreographedSaga]:
        """List of all currently registered sagas."""
        return list(self._sagas.values())

    @property
    def is_running(self) -> bool:
        return self._running

    def get_saga(self, saga_id: str) -> ChoreographedSaga | None:
        """Return the registered saga with *saga_id*, or *None*."""
        return self._sagas.get(saga_id)
