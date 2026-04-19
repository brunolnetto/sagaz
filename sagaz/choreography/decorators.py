"""
@on_event decorator for ChoreographedSaga handler methods.
"""

from __future__ import annotations

import functools
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
            return await fn(*args, **kwargs)

        setattr(wrapper, _HANDLER_ATTR, event_type)
        return wrapper

    return decorator


def get_event_type(method: Callable) -> str | None:
    """Return the event type associated with *method*, or *None*."""
    return getattr(method, _HANDLER_ATTR, None)
