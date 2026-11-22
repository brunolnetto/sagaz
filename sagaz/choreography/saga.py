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
from typing import TYPE_CHECKING, Any

from sagaz.choreography._attempts import DEFAULT_RETRY_BACKOFF_BASE, attempt
from sagaz.choreography._compensation import run_compensation
from sagaz.choreography._observe import Listeners, span, with_trace_context
from sagaz.choreography.decorators import (
    RetryPolicy,
    call_maybe_async,
    get_compensated_event_type,
    get_event_type,
    get_retry_policy,
)
from sagaz.choreography.events import Event
from sagaz.choreography.state import InMemoryParticipantState, ParticipantState
from sagaz.core.exceptions import SagaAlreadyExistsError, SagaDefinitionError
from sagaz.core.storage._reserved import RESERVED_SAGA_PREFIX

#: The participant name under which ``begin`` records a correlation id it started, in
#: the participant state's delivery records (#562). Reserved: no participant uses it.
BEGIN_RECORD = f"{RESERVED_SAGA_PREFIX}begin"

if TYPE_CHECKING:
    from sagaz.core.tenant import TenantContext

logger = logging.getLogger(__name__)

#: The event whose handler is running, so ``emit()`` can continue its transaction.
current_cause: ContextVar[Event | None] = ContextVar("sagaz_choreography_cause", default=None)


class ChoreographedSaga:
    """
    Base class for saga participants in a choreography.

    Handlers are declared in one of two styles, not both:

    - declarative: a subclass marks methods with ``@on_event`` (and ``@compensate``);
    - imperative: ``ChoreographedSaga(name=...).on(event_type, handler, compensation=)``,
      where *handler* and *compensation* are called as ``fn(event, participant)``.

    The ``ChoreographyEngine`` subscribes the handlers to the ``EventBus`` when
    ``engine.register(saga)`` is called. Two handlers for one event type are a
    ``SagaDefinitionError``.

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
        if self.name.startswith(RESERVED_SAGA_PREFIX):
            msg = f"participant names starting with {RESERVED_SAGA_PREFIX!r} are reserved"
            raise SagaDefinitionError(msg)
        self._events_handled: list[Event] = []
        self._handlers: dict[str, Any] = {}  # event_type → bound method
        self._compensators: dict[str, Any] = {}  # event_type → bound undo method
        self._policies: dict[str, RetryPolicy] = {}  # event_type → (max_retries, timeout)
        self._undo_policies: dict[str, RetryPolicy] = {}  # the same, for compensations
        # Completed actions, finished and compensated transactions, handled
        # deliveries (#448). In memory unless the engine provides a durable state.
        self._state: ParticipantState = InMemoryParticipantState(self.max_tracked_transactions)
        self._publish: Callable[[Event], Awaitable[None]] | None = None
        # Set by the engine: makes sure deadlines are watched once one is set.
        self._watch_deadlines: Callable[[], None] | None = None
        # Set by the engine: its listeners (#563).
        self._listeners: Listeners = Listeners()
        self._discover_handlers()
        self._declarative = bool(self._handlers)

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
                self._undo_policies[undone] = get_retry_policy(method)
            event_type = get_event_type(method)
            if event_type is not None:
                self._add_handler(event_type, method, _name)
                self._policies[event_type] = get_retry_policy(method)
                logger.debug(
                    "%s registered handler %r for %r",
                    self.name,
                    _name,
                    event_type,
                )

    def _add_handler(self, event_type: str, handler: Callable[[Event], Any], what: str) -> None:
        if event_type in self._handlers:
            msg = f"{self.name} has two handlers for event type {event_type!r} (the second: {what})"
            raise SagaDefinitionError(msg)
        self._handlers[event_type] = handler

    def on(
        self,
        event_type: str,
        handler: Callable[[Event, ChoreographedSaga], Any],
        compensation: Callable[[Event, ChoreographedSaga], Any] | None = None,
        *,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
    ) -> ChoreographedSaga:
        """Handle *event_type* with *handler*, undone by *compensation* (#560).

        The imperative counterpart of ``@on_event`` / ``@compensate``. Both functions
        are called as ``fn(event, participant)``, sync or async; the participant is
        how a handler emits its result (``await participant.emit(...)``). Returns
        the participant, so calls can be chained. *max_retries* and
        *timeout_seconds* are those of ``@on_event``.

        Raises:
            SagaDefinitionError: *event_type* already has a handler, the participant
                declares ``@on_event`` handlers, or it is already registered with an
                engine (which subscribed to its event types then).
        """
        if self._declarative:
            msg = f"{self.name} declares @on_event handlers: use one style, not both"
            raise SagaDefinitionError(msg)
        if self._publish is not None:
            msg = f"{self.name} is registered with an engine: add handlers before registering"
            raise SagaDefinitionError(msg)

        async def run(event: Event) -> object:
            return await call_maybe_async(handler, event, self)

        self._add_handler(event_type, run, getattr(handler, "__name__", repr(handler)))
        self._policies[event_type] = (max_retries, timeout_seconds)
        if compensation is not None:

            async def undo(event: Event) -> object:
                return await call_maybe_async(compensation, event, self)

            self._compensators[event_type] = undo
        return self

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def retry_policy(self, event_type: str) -> RetryPolicy:
        """The handler's ``(max_retries, timeout_seconds)``; ``None`` takes the default."""
        key = event_type if event_type in self._handlers else "*"
        return self._policies.get(key, (None, None))

    async def handle(self, event: Event) -> None:
        """
        Dispatch *event* to the appropriate ``@on_event`` handler, once.

        Looks up by exact event type first, then by ``"*"`` wildcard. The engine
        does not call this method (a participant may name a handler ``handle``): it
        runs the handler with its retries and timeout (#561).

        Parameters
        ----------
        event:
            The incoming domain event.
        """
        await self._run(event)

    async def _run(
        self,
        event: Event,
        *,
        max_retries: int = 0,
        timeout_seconds: float | None = None,
        retry_backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE,
    ) -> None:
        """Run *event*'s handler ``max_retries + 1`` times at most (#561)."""
        handler = self._handlers.get(event.event_type) or self._handlers.get("*")
        if handler is None:
            logger.debug("%s has no handler for %r; ignoring", self.name, event.event_type)
            return

        self._events_handled.append(event)
        logger.debug("%s handling %r (saga_id=%s)", self.name, event.event_type, self.saga_id)
        await attempt(
            lambda: handler(event),
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            retry_backoff_base=retry_backoff_base,
            what=f"{self.name} handling {event.event_type!r}",
        )
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
        event = with_trace_context(event)  # its handlers' spans continue this trace (#563)
        await self._state.publish(self.name, event, self._publish, cause=cause, remember=remember)
        return event

    async def begin(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        correlation_id: str | None = None,
        tenant: TenantContext | str | None = None,
        deadline: timedelta | float | None = None,
        tenant_id: str | None = None,
        allow_rerun: bool = False,
    ) -> Event:
        """Start a new transaction by publishing its first event.

        A *correlation_id* runs once per tenant (#562), as a saga id does for
        ``Saga.run``: a second ``begin`` with it raises ``SagaAlreadyExistsError``
        before anything is published, so a retried request does not start the
        transaction (and its effects) again. ``allow_rerun=True`` starts it anyway.
        A generated correlation id is new, so it is not checked. The record lives
        with the participant state's handled deliveries, and is pruned with them.

        The event gets a new correlation id (or *correlation_id*), the given
        *tenant*, a ``TenantContext`` or a tenant id (default: the current tenant
        scope), and this participant as source. ``tenant_id=`` is the deprecated
        name of ``tenant`` (until 3.0).

        With a *deadline* (a ``timedelta`` or seconds), this participant owns
        the transaction's time limit: if no completion event arrives in time,
        its engine publishes ``choreography.compensate`` (#449).
        """
        from uuid import uuid4

        from sagaz.core.tenant import TenantContext, current_tenant_id, tenant_argument

        given = tenant_argument(f"{type(self).__name__}.begin", tenant, tenant_id=tenant_id)
        if self._publish is None:
            msg = f"{self.name} is not registered with a ChoreographyEngine"
            raise RuntimeError(msg)
        event = Event(
            event_type,
            dict(data or {}),
            saga_id=correlation_id or str(uuid4()),
            tenant_id=(given.tenant_id if isinstance(given, TenantContext) else given)
            or current_tenant_id(),
            source=self.name,
        )
        if correlation_id is not None and not allow_rerun:
            await self._claim_correlation_id(event)
        if deadline is not None:
            await self._set_deadline(event, deadline)
        with span(self.name, event, "begin", producer=True):  # the transaction's trace
            event = with_trace_context(event)
            await self._state.publish(self.name, event, self._publish, begin=True)
        return event

    async def _claim_correlation_id(self, event: Event) -> None:
        """Record *event*'s correlation id as started; raise if it already was (#562)."""
        from sagaz.core.tenant import tenant_scope

        correlation_id = event.saga_id or ""
        with tenant_scope(event.tenant_id):
            first = await self._state.first_delivery(BEGIN_RECORD, correlation_id)
        if not first:
            raise SagaAlreadyExistsError(correlation_id)

    async def _set_deadline(self, event: Event, deadline: timedelta | float) -> None:
        """Make this participant own *event*'s transaction deadline (#449)."""
        from sagaz.core.tenant import tenant_scope

        seconds = deadline.total_seconds() if isinstance(deadline, timedelta) else deadline
        due_at = datetime.now(UTC) + timedelta(seconds=seconds)
        with tenant_scope(event.tenant_id):  # set before the transaction can finish
            await self._state.set_deadline(self.name, event.saga_id or "", due_at)
        if self._watch_deadlines is not None:
            self._watch_deadlines()

    async def compensate_transaction(
        self,
        correlation_id: str,
        *,
        max_retries: int = 0,
        timeout_seconds: float | None = None,
        retry_backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE,
    ) -> tuple[list[str], list[str]]:
        """Undo, newest first, what this participant did in *correlation_id*.

        Each compensation runs ``max_retries + 1`` times at most (its own
        ``@compensate`` values take precedence, #561). Returns the event types whose
        actions were undone and those whose compensation still raised (logged, and
        the remaining ones still run).
        """
        undone: list[str] = []
        failed: list[str] = []
        done = await self._state.finish(self.name, correlation_id, compensated=True)
        for original in reversed(done):
            own_retries, own_timeout = self._undo_policies.get(original.event_type, (None, None))
            ok = await run_compensation(
                self.name,
                self._compensators[original.event_type],
                original,
                self._listeners,
                max_retries=max_retries if own_retries is None else own_retries,
                timeout_seconds=timeout_seconds if own_timeout is None else own_timeout,
                retry_backoff_base=retry_backoff_base,
            )
            (undone if ok else failed).append(original.event_type)
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
