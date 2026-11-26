"""Retries and timeouts of choreography handlers (#561).

A handler runs ``max_retries + 1`` times at most, each attempt under its timeout, with
exponential backoff between attempts (``retry_backoff_base * 2**n`` seconds), as an
orchestrated step does. A handler that sets neither takes the engine's defaults
(``ChoreographyEngine(default_max_retries=3, default_timeout=60.0)``). Cancellation is
never retried.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable

logger = logging.getLogger("sagaz.choreography")

DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRY_BACKOFF_BASE = 0.01


async def attempt(
    run: Callable[[], Awaitable[object]],
    *,
    max_retries: int,
    timeout_seconds: float | None,
    retry_backoff_base: float,
    what: str,
) -> None:
    """Run *run* until an attempt succeeds; re-raise the last attempt's error.

    The current tenant's ``max_retries`` and ``max_step_duration_seconds`` cap
    *max_retries* and *timeout_seconds* (#564), as for orchestrated steps.
    """
    from sagaz.core.tenant import capped_retries, capped_timeout

    attempts = capped_retries(max_retries) + 1
    capped = capped_timeout(math.inf if timeout_seconds is None else timeout_seconds)
    timeout_seconds = None if capped == math.inf else capped
    for number in range(attempts):
        try:
            await asyncio.wait_for(run(), timeout=timeout_seconds)
            return
        except Exception as error:  # asyncio.CancelledError is not an Exception
            if number == attempts - 1:
                raise
            delay = retry_backoff_base * (2**number)
            logger.warning(
                "%s failed (attempt %d/%d): %s: %s; retrying in %gs",
                what,
                number + 1,
                attempts,
                type(error).__name__,
                error,
                delay,
            )
            await asyncio.sleep(delay)
