"""Running one compensation of a choreography participant (#561, #563)."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from sagaz.choreography._attempts import attempt
from sagaz.choreography._observe import Listeners, listener_context, notify, span
from sagaz.choreography._pivot import Participant, split
from sagaz.choreography.decorators import call_maybe_async
from sagaz.choreography.events import Event

logger = logging.getLogger("sagaz.choreography")


async def compensate_all(
    saga: Participant,
    correlation_id: str,
    *,
    max_retries: int,
    timeout_seconds: float | None,
    retry_backoff_base: float,
) -> tuple[list[str], list[str], list[str]]:
    """Undo, newest first, what *saga* did in *correlation_id*.

    Returns the event types whose actions were undone, those whose compensation still
    raised, and those kept because a pivot committed them (#571).
    """
    undone: list[str] = []
    failed: list[str] = []
    done = await saga._state.finish(saga.name, correlation_id, compensated=True)
    undo, kept = split(saga, done)
    for original in reversed(undo):
        own_retries, own_timeout = saga._undo_policies.get(original.event_type, (None, None))
        ok = await run_compensation(
            saga.name,
            saga._compensators[original.event_type],
            original,
            saga._listeners,
            max_retries=max_retries if own_retries is None else own_retries,
            timeout_seconds=timeout_seconds if own_timeout is None else own_timeout,
            retry_backoff_base=retry_backoff_base,
        )
        (undone if ok else failed).append(original.event_type)
    return undone, failed, kept


async def run_compensation(
    participant: str,
    compensation: Callable[..., Any],
    original: Event,
    listeners: Listeners,
    *,
    max_retries: int,
    timeout_seconds: float | None,
    retry_backoff_base: float,
) -> bool:
    """Undo what *participant* did on *original*: True if the compensation ran.

    It is retried like a handler, runs in a span, and the listeners see it start and
    complete or fail. A compensation that still raises is logged, not propagated.
    """
    ctx = listener_context(original)
    step = original.event_type
    await notify(listeners, "on_compensation_start", participant, step, ctx)
    # A child of the current span (the transaction's compensation), not of *original*'s.
    with span(participant, replace(original, trace_context={}), "compensate") as outcome:
        try:
            await attempt(
                functools.partial(call_maybe_async, compensation, original),
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                retry_backoff_base=retry_backoff_base,
                what=f"{participant} compensating {step!r}",
            )
        except Exception as error:
            logger.exception("%s failed to compensate %r", participant, step)
            outcome.failed(error)
            await notify(listeners, "on_compensation_failed", participant, step, ctx, error)
            return False
    await notify(listeners, "on_compensation_complete", participant, step, ctx)
    return True
