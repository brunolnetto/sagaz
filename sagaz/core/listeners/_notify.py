"""Calling listeners without letting them hold up a saga (#563, #633).

Listeners run on the hot path: an orchestrated step, a choreography handler or the
choreography tracker's observation of an event waits for them. So both coordination
styles call them through :func:`notify`, which logs and skips a listener that raises,
and cancels, logs and skips an async listener call slower than the timeout.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagaz.core.listeners._base import SagaListener

logger = logging.getLogger("sagaz.listeners")

#: Seconds an async listener call may take before it is skipped.
DEFAULT_LISTENER_TIMEOUT = 5.0


class Listeners:
    """``SagaListener`` instances, and how long each call may take.

    An async listener call that takes longer than *timeout* seconds is cancelled,
    logged and skipped, as one that raises is. ``None`` waits as long as it takes. A
    synchronous listener cannot be interrupted.
    """

    __slots__ = ("items", "timeout")

    def __init__(
        self,
        items: Iterable[SagaListener] = (),
        timeout: float | None = DEFAULT_LISTENER_TIMEOUT,
    ) -> None:
        self.items: list[SagaListener] = list(items)
        self.timeout = timeout

    def __bool__(self) -> bool:
        return bool(self.items)


async def notify(listeners: Listeners, hook: str, *args: object) -> None:
    """Call *hook* on every listener; one that raises or is too slow is logged and skipped."""
    for listener in listeners.items:
        try:
            method = getattr(listener, hook, None)
            if method is None:
                continue
            result = method(*args)
            if inspect.isawaitable(result):
                async with asyncio.timeout(listeners.timeout):
                    await result
        except TimeoutError:
            name = f"{type(listener).__name__}.{hook}"
            logger.warning("Listener %s took longer than %ss: skipped", name, listeners.timeout)
        except Exception as error:
            logger.warning("Listener %s.%s error: %s", type(listener).__name__, hook, error)
