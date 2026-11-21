"""
@on_event decorator for ChoreographedSaga handler methods.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

_HANDLER_ATTR = "_choreography_event_type"


def on_event(event_type: str) -> Callable:
    """
    Mark an async method as an event handler for *event_type*.

    The decorated method must accept ``(self, event: Event) -> None``.

    Parameters
    ----------
    event_type:
        The event type string to listen for (e.g. ``"order.created"``).
        Use ``"*"`` to receive all events.

    Example
    -------
    ::

        class MySaga(ChoreographedSaga):
            @on_event("order.created")
            async def handle_order(self, event: Event) -> None:
                ...
    """

    def decorator(fn: Callable) -> Callable:
        setattr(fn, _HANDLER_ATTR, event_type)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await call_maybe_async(fn, *args, **kwargs)

        setattr(wrapper, _HANDLER_ATTR, event_type)
        return wrapper

    return decorator


def get_event_type(method: Callable) -> str | None:
    """Return the event type associated with *method*, or *None*."""
    return getattr(method, _HANDLER_ATTR, None)


_COMPENSATES_ATTR = "_choreography_compensates"


def compensate(event_type: str) -> Callable:
    """Mark an async method as the undo of the action taken on *event_type*.

    When a transaction fails, a :data:`~sagaz.choreography.COMPENSATE` event
    reaches every participant; each one runs, in reverse order, the
    compensations of the events it handled successfully in that transaction.
    The method receives the original event.

    Example
    -------
    ::

        class Payments(ChoreographedSaga):
            @on_event("inventory.reserved")
            async def charge(self, event: Event) -> None: ...

            @compensate("inventory.reserved")
            async def refund(self, event: Event) -> None: ...
    """

    def decorator(fn: Callable) -> Callable:
        setattr(fn, _COMPENSATES_ATTR, event_type)
        return fn

    return decorator


def get_compensated_event_type(method: Callable) -> str | None:
    """Return the event type whose action *method* undoes, or *None*."""
    return getattr(method, _COMPENSATES_ATTR, None)


async def call_maybe_async(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """Call a handler or compensation that may be a plain ``def`` (#553)."""
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result
