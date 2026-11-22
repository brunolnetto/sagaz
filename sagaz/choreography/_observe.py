"""Tracing and listeners for choreography (#563).

Tracing: every handler and every compensation runs in an OpenTelemetry span. An event
carries the W3C trace context of the span that published it (``Event.trace_context``),
and the span that handles it is that span's child, so a transaction is one trace across
services. Without ``opentelemetry`` installed, nothing is traced and events carry no
context.

Listeners: the ``SagaListener`` hooks of orchestrated sagas, seen from one participant:
the saga name is the participant's name, a step is the event type it handles, and the
saga id is the correlation id. ``LoggingSagaListener``, ``MetricsSagaListener`` and
custom listeners work as they are; a listener that raises is logged and ignored.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from types import ModuleType
from typing import TYPE_CHECKING, Any

from sagaz.choreography.events import Event

if TYPE_CHECKING:
    from opentelemetry import trace
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    from sagaz.core.listeners import SagaListener

logger = logging.getLogger("sagaz.choreography")

#: The instrumentation scope of choreography spans.
TRACER_NAME = "sagaz.choreography"


@functools.cache
def _trace() -> ModuleType | None:
    """``opentelemetry.trace``, imported on first use: ``import sagaz`` must not load it."""
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    return trace


def _propagator() -> TraceContextTextMapPropagator:
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    return TraceContextTextMapPropagator()


def tracer() -> trace.Tracer:
    """The tracer of choreography spans, from the global tracer provider."""
    otel = _trace()
    assert otel is not None  # only called when opentelemetry is installed
    found: trace.Tracer = otel.get_tracer(TRACER_NAME)
    return found


def with_trace_context(event: Event) -> Event:
    """*event* carrying the current span's trace context, if there is one."""
    otel = _trace()
    if otel is None or not otel.get_current_span().get_span_context().is_valid:
        return event
    carrier: dict[str, str] = {}
    _propagator().inject(carrier)
    return replace(event, trace_context=carrier)


class Outcome:
    """The span a choreography operation runs in, to mark it failed."""

    def __init__(self, current: trace.Span | None = None) -> None:
        self._span = current
        self.ok = True

    def failed(self, error: BaseException) -> None:
        """Record *error* on the span: its status is an error, even if it was handled."""
        self.ok = False
        otel = _trace()
        if self._span is not None and otel is not None:
            self._span.record_exception(error)
            description = f"{type(error).__name__}: {error}"
            self._span.set_status(otel.Status(otel.StatusCode.ERROR, description))


@contextmanager
def span(
    participant: str, event: Event, operation: str, *, producer: bool = False
) -> Iterator[Outcome]:
    """A span for *participant* doing *operation* on *event*.

    It continues the trace *event* carries (the span that published it is its
    parent), or the caller's current span when the event carries none, as for the
    event ``begin`` publishes (``producer=True``).
    """
    otel = _trace()
    if otel is None:
        yield Outcome()
        return
    parent = _propagator().extract(event.trace_context) if event.trace_context else None
    with tracer().start_as_current_span(
        f"{participant} {operation} {event.event_type}",
        context=parent,
        kind=otel.SpanKind.PRODUCER if producer else otel.SpanKind.CONSUMER,
        attributes={
            "sagaz.participant": participant,
            "sagaz.operation": operation,
            "sagaz.event_type": event.event_type,
            "sagaz.event_id": event.event_id,
            "sagaz.correlation_id": event.saga_id or "",
            "sagaz.tenant_id": event.tenant_id,
        },
        record_exception=True,
        set_status_on_exception=True,
    ) as current:
        outcome = Outcome(current)
        yield outcome
        if outcome.ok:
            current.set_status(otel.Status(otel.StatusCode.OK))


def listener_context(event: Event) -> dict[str, Any]:
    """What a listener receives as ``ctx``: the event's data, its correlation and tenant."""
    return {**event.data, "saga_id": event.saga_id, "tenant_id": event.tenant_id}


async def notify(listeners: Sequence[SagaListener], hook: str, *args: object) -> None:
    """Call *hook* on every listener; one that raises is logged, never propagated."""
    for listener in listeners:
        try:
            method = getattr(listener, hook, None)
            if method is not None:
                result = method(*args)
                if inspect.isawaitable(result):
                    await result
        except Exception as error:
            logger.warning("Listener %s.%s error: %s", type(listener).__name__, hook, error)
