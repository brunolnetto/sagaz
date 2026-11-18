"""
ChoreographyEngine — wires ChoreographedSagas to an EventBus.

The engine manages saga lifecycle: registering their event handlers with the
bus and tracking active saga instances.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sagaz.choreography._dispatch import Dispatcher
from sagaz.choreography.events import COMPENSATE, AbstractEventBus, Event, HandlerT
from sagaz.choreography.saga import ChoreographedSaga
from sagaz.choreography.state import ParticipantState, create_participant_state

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
        participants then forget what they would have compensated.
    state:
        Where registered participants keep their completed actions, tombstones
        and handled deliveries: a ``ParticipantState`` or a URL
        (``sqlite://...``, ``postgresql://...``). Default: each participant's
        own memory, lost on restart. A shared durable state lets replicas of a
        participant compensate each other's actions (#448).

    Each delivery is deduplicated by ``event_id`` and runs in the event's tenant
    scope. If a handler raises, the engine publishes a ``COMPENSATE`` event and
    every participant undoes its ``@compensate`` actions for that transaction.

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
    ) -> None:
        self._bus = bus
        self._state = create_participant_state(state) if isinstance(state, str) else state
        self._completion_events = frozenset(completion_events)
        self._dispatcher = Dispatcher(bus.publish, self._completion_events)
        self._sagas: dict[str, ChoreographedSaga] = {}
        self._running = False
        # Tracks dispatch closures created per saga so they can be properly unsubscribed.
        self._closures: dict[str, dict[str, HandlerT]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Mark the engine as running (enables event dispatch)."""
        self._running = True
        logger.info("ChoreographyEngine started with %d saga(s)", len(self._sagas))

    async def stop(self) -> None:
        """Deregister all sagas and shut down the engine."""
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

    def _subscriptions(self, saga: ChoreographedSaga) -> list[str]:
        """Event types to route to *saga*: its handlers, compensation, and completion.

        Every participant receives ``COMPENSATE`` (and reports, even with nothing to
        undo) so a tracker can tell when a failed transaction is fully compensated.
        """
        types = [*saga._handlers, COMPENSATE]
        if saga._compensators:
            types += sorted(self._completion_events)
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
