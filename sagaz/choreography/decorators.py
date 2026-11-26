"""
@on_event decorator for ChoreographedSaga handler methods.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterable
from typing import Any

_HANDLER_ATTR = "_choreography_event_type"
_POLICY_ATTR = "_choreography_retry_policy"
_EMITS_ATTR = "_choreography_emits"
_PIVOT_ATTR = "_choreography_pivot"

#: A handler's ``(max_retries, timeout_seconds)``; ``None`` takes the engine's default.
RetryPolicy = tuple[int | None, float | None]


def on_event(
    event_type: str,
    *,
    max_retries: int | None = None,
    timeout_seconds: float | None = None,
    emits: Iterable[str] | None = None,
    pivot: bool = False,
) -> Callable:
    """
    Mark an async method as an event handler for *event_type*.

    ``pivot=True`` makes it a point of no return (#571): once it completes, what the
    participants had done in the transaction is kept, whatever fails later.

    The decorated method must accept ``(self, event: Event) -> None``.

    Parameters
    ----------
    event_type:
        The event type string to listen for (e.g. ``"order.created"``).
        Use ``"*"`` to receive all events.
    max_retries:
        Attempts after the first one when the handler raises, with exponential
        backoff (#561). Default: the engine's ``default_max_retries`` (3).
    timeout_seconds:
        Time limit of one attempt. Default: the engine's ``default_timeout`` (60 s).
    emits:
        The event types the handler publishes with ``emit()`` (#565). Optional: it
        draws the handler's edges in ``ChoreographyEngine.to_mermaid()``, and an
        ``emit()`` of an undeclared type logs a warning.

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
        setattr(wrapper, _POLICY_ATTR, (max_retries, timeout_seconds))
        if emits is not None:
            setattr(wrapper, _EMITS_ATTR, frozenset(emits))
        setattr(wrapper, _PIVOT_ATTR, pivot)
        return wrapper

    return decorator


def get_event_type(method: Callable) -> str | None:
    """Return the event type associated with *method*, or *None*."""
    return getattr(method, _HANDLER_ATTR, None)


def is_pivot(method: Callable) -> bool:
    """True if ``@on_event(pivot=True)`` marked *method* as a point of no return."""
    return bool(getattr(method, _PIVOT_ATTR, False))


def get_emits(method: Callable) -> frozenset[str] | None:
    """The event types ``@on_event(emits=...)`` declared for *method*, or *None*."""
    declared: frozenset[str] | None = getattr(method, _EMITS_ATTR, None)
    return declared


def get_retry_policy(method: Callable) -> RetryPolicy:
    """The ``(max_retries, timeout_seconds)`` given to ``@on_event`` for *method*."""
    policy: RetryPolicy = getattr(method, _POLICY_ATTR, (None, None))
    return policy


_COMPENSATES_ATTR = "_choreography_compensates"


def compensate(
    event_type: str, *, max_retries: int | None = None, timeout_seconds: float | None = None
) -> Callable:
    """Mark an async method as the undo of the action taken on *event_type*.

    A compensation that raises is retried like a handler (#561): ``max_retries`` and
    ``timeout_seconds`` default to the engine's ``default_max_retries`` and
    ``default_timeout``.

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
        setattr(fn, _POLICY_ATTR, (max_retries, timeout_seconds))
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
