"""
ChoreographedSaga — base class for event-driven saga participants.

A ``ChoreographedSaga`` discovers all ``@on_event``-decorated methods at
construction time and exposes them via ``_handlers``.  It is registered with
a ``ChoreographyEngine`` that subscribes each handler to the ``EventBus``.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from sagaz.choreography.decorators import get_event_type
from sagaz.choreography.events import Event

logger = logging.getLogger(__name__)


class ChoreographedSaga:
    """
    Base class for saga participants in a choreography.

    Subclasses declare event handlers using the ``@on_event`` decorator.
    The ``ChoreographyEngine`` subscribes these handlers to the ``EventBus``
    when ``engine.register(saga)`` is called.

    Parameters
    ----------
    saga_id:
        Optional correlation ID.  Auto-assigned if omitted.
    name:
        Human-readable saga name for logging.
    """

    def __init__(
        self,
        saga_id: str | None = None,
        name: str | None = None,
    ) -> None:
        from uuid import uuid4

        self.saga_id: str = saga_id or str(uuid4())
        self.name: str = name or type(self).__name__
        self._events_handled: list[Event] = []
        self._handlers: dict[str, Any] = {}  # event_type → bound method
        self._discover_handlers()

    # ------------------------------------------------------------------
    # Handler discovery
    # ------------------------------------------------------------------

    def _discover_handlers(self) -> None:
        """
        Inspect all methods and collect those marked with ``@on_event``.
        Populates ``self._handlers`` as ``{event_type: bound_method}``.
        """
        for _name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            event_type = get_event_type(method)
            if event_type is not None:
                if event_type in self._handlers:
                    logger.warning(
                        "%s has multiple handlers for event type %r; last one wins.",
                        self.name,
                        event_type,
                    )
                self._handlers[event_type] = method
                logger.debug(
                    "%s registered handler %r for %r",
                    self.name,
                    _name,
                    event_type,
                )

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    async def handle(self, event: Event) -> None:
        """
        Dispatch *event* to the appropriate ``@on_event`` handler.

        Looks up by exact event type first, then by ``"*"`` wildcard.

        Parameters
        ----------
        event:
            The incoming domain event.
        """
        handler = self._handlers.get(event.event_type) or self._handlers.get("*")
        if handler is None:
            logger.debug("%s has no handler for %r; ignoring", self.name, event.event_type)
            return

        self._events_handled.append(event)
        logger.debug("%s handling %r (saga_id=%s)", self.name, event.event_type, self.saga_id)
        await handler(event)

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    @property
    def events_handled(self) -> list[Event]:
        """All events dispatched to this saga since construction."""
        return list(self._events_handled)

    def handles(self, event_type: str) -> bool:
        """Return *True* if this saga has a handler for *event_type*."""
        return event_type in self._handlers or "*" in self._handlers
