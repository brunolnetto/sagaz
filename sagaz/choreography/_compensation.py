"""Running one compensation of a choreography participant (#561, #563)."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sagaz.choreography._attempts import attempt
from sagaz.choreography._observe import listener_context, notify, span
from sagaz.choreography.decorators import call_maybe_async
from sagaz.choreography.events import Event

if TYPE_CHECKING:
    from sagaz.core.listeners import SagaListener

logger = logging.getLogger("sagaz.choreography")


async def run_compensation(
    participant: str,
    compensation: Callable[..., Any],
    original: Event,
    listeners: Sequence[SagaListener],
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
