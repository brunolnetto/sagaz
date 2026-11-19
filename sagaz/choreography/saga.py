"""
ChoreographedSaga — base class for event-driven saga participants.

A ``ChoreographedSaga`` discovers all ``@on_event``-decorated methods at
construction time and exposes them via ``_handlers``.  It is registered with
a ``ChoreographyEngine`` that subscribes each handler to the ``EventBus``.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.choreography.decorators import get_compensated_event_type, get_event_type
from sagaz.choreography.events import Event
from sagaz.choreography.state import InMemoryParticipantState, ParticipantState

logger = logging.getLogger(__name__)

#: The event whose handler is running, so ``emit()`` can continue its transaction.
current_cause: ContextVar[Event | None] = ContextVar("sagaz_choreography_cause", default=None)


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
        self._compensators: dict[str, Any] = {}  # event_type → bound undo method
        # Completed actions, finished and compensated transactions, handled
        # deliveries (#448). In memory unless the engine provides a durable state.
        self._state: ParticipantState = InMemoryParticipantState(self.max_tracked_transactions)
        self._publish: Callable[[Event], Awaitable[None]] | None = None
        # Set by the engine: makes sure deadlines are watched once one is set.
        self._watch_deadlines: Callable[[], None] | None = None
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
            if (undone := get_compensated_event_type(method)) is not None:
                self._compensators[undone] = method
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
        await self._remember(event)

    # ------------------------------------------------------------------
    # Emitting and compensation
    # ------------------------------------------------------------------

    #: Transactions whose completed actions are remembered for compensation.
    max_tracked_transactions = 10_000

    async def _remember(self, event: Event) -> None:
        """Record *event*'s action as completed, so it can be compensated later.

        Called when the handler emits its result (the local action is done) and
        when it returns; on an in-process bus the rest of the transaction runs
        inside ``emit``, so waiting for the return would be too late. Actions of
        a transaction that already finished are not recorded.
        """
        if event.saga_id and event.event_type in self._compensators:
            await self._state.record_action(self.name, event)

    async def was_compensated(self, correlation_id: str | None) -> bool:
        """True if this participant compensated *correlation_id* (a tombstone, #446)."""
        if correlation_id is None:
            return False
        return await self._state.was_compensated(self.name, correlation_id)

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> Event:
        """Publish a follow-on event in the transaction of the event being handled.

        The new event keeps the correlation id and tenant of the event that
        triggered the running handler, records it as its cause, and names this
        participant as its source.
        """
        if self._publish is None:
            msg = f"{self.name} is not registered with a ChoreographyEngine"
            raise RuntimeError(msg)
        event = Event(event_type, dict(data or {}), source=self.name)
        cause = current_cause.get()
        if cause is not None:
            event = event.caused_by(cause)
        # Announcing the result: the local action is done, so it is recorded
        # (atomically with the event on the unified saga log).
        remember = (
            cause is not None and bool(cause.saga_id) and cause.event_type in self._compensators
        )
        await self._state.publish(self.name, event, self._publish, cause=cause, remember=remember)
        return event

    async def begin(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        deadline: timedelta | float | None = None,
    ) -> Event:
        """Start a new transaction by publishing its first event.

        The event gets a new correlation id (or *correlation_id*), the given
        tenant (default: the current tenant scope) and this participant as source.

        With a *deadline* (a ``timedelta`` or seconds), this participant owns
        the transaction's time limit: if no completion event arrives in time,
        its engine publishes ``choreography.compensate`` (#449).
        """
        from uuid import uuid4

        from sagaz.core.tenant import current_tenant_id, tenant_scope

        if self._publish is None:
            msg = f"{self.name} is not registered with a ChoreographyEngine"
            raise RuntimeError(msg)
        event = Event(
            event_type,
            dict(data or {}),
            saga_id=correlation_id or str(uuid4()),
            tenant_id=tenant_id or current_tenant_id(),
            source=self.name,
        )
        if deadline is not None:
            seconds = deadline.total_seconds() if isinstance(deadline, timedelta) else deadline
            due_at = datetime.now(UTC) + timedelta(seconds=seconds)
            with tenant_scope(event.tenant_id):  # set before the transaction can finish
                await self._state.set_deadline(self.name, event.saga_id or "", due_at)
            if self._watch_deadlines is not None:
                self._watch_deadlines()
        await self._state.publish(self.name, event, self._publish, begin=True)
        return event

    async def compensate_transaction(self, correlation_id: str) -> tuple[list[str], list[str]]:
        """Undo, newest first, what this participant did in *correlation_id*.

        Returns the event types whose actions were undone and those whose
        compensation raised (logged, and the remaining ones still run).
        """
        undone: list[str] = []
        failed: list[str] = []
        done = await self._state.finish(self.name, correlation_id, compensated=True)
        for original in reversed(done):
            try:
                await self._compensators[original.event_type](original)
                undone.append(original.event_type)
            except Exception:
                logger.exception("%s failed to compensate %r", self.name, original.event_type)
                failed.append(original.event_type)
        return undone, failed

    async def forget(self, correlation_id: str) -> None:
        """Drop what is remembered for a transaction that completed."""
        await self._state.finish(self.name, correlation_id, compensated=False)

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
