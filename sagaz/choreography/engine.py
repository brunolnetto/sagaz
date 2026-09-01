"""
ChoreographyEngine — wires ChoreographedSagas to an EventBus.

The engine manages saga lifecycle: registering their event handlers with the
bus and tracking active saga instances.
"""

from __future__ import annotations

import logging

from sagaz.choreography.events import AbstractEventBus, Event, HandlerT
from sagaz.choreography.saga import ChoreographedSaga

logger = logging.getLogger(__name__)


class ChoreographyEngine:
    """
    Routes events from an ``EventBus`` to registered ``ChoreographedSaga``
    instances.

    Parameters
    ----------
    bus:
        The ``EventBus`` to subscribe to.

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

    def __init__(self, bus: AbstractEventBus) -> None:
        self._bus = bus
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

        for event_type in saga._handlers:
            # Capture saga via default arg to avoid closure-over-loop-variable.
            async def _dispatch(event: Event, _saga: ChoreographedSaga = saga) -> None:
                await _saga.handle(event)

            # Store the closure so _deregister() can later call bus.unsubscribe().
            self._closures.setdefault(saga.saga_id, {})[event_type] = _dispatch
            self._bus.subscribe(event_type, _dispatch)

        logger.debug("Registered saga %r (%s)", saga.saga_id, saga.name)

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
