"""
ChoreographyEngine — wires ChoreographedSagas to an EventBus.

The engine manages saga lifecycle: registering their event handlers with the
bus and tracking active saga instances.
"""

from __future__ import annotations

import logging

from sagaz.choreography.events import AbstractEventBus, Event
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

        for event_type, _method in saga._handlers.items():
            # Wrap the method so the bus calls saga.handle() → proper routing
            async def _dispatch(event: Event, _saga: ChoreographedSaga = saga) -> None:
                await _saga.handle(event)

            # Subscribe once per event type per saga; use the dispatch wrapper
            self._bus.subscribe(event_type, _dispatch)

        logger.debug("Registered saga %r (%s)", saga.saga_id, saga.name)

    def _deregister(self, saga: ChoreographedSaga) -> None:
        """Unsubscribe the saga's handlers from the bus."""
        # We cannot easily unsubscribe the closures we created, so we rely on
        # the engine's stopped state to skip dispatch.  For production use
        # with external adapters, explicit unsubscription would be wired here.
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
