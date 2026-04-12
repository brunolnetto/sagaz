"""Utility helpers for compensation signature detection."""

import inspect
from collections.abc import Awaitable, Callable
from typing import Any


def _detect_compensation_signature(
    compensation_fn: Callable[[dict[str, Any]], Awaitable[Any]],
) -> bool:
    """
    Detect if compensation function accepts compensation_results parameter.

    Args:
        compensation_fn: The compensation function to inspect

    Returns:
        True if function accepts compensation_results parameter (new signature),
        False if it only accepts context (context-only signature)
    """
    sig = inspect.signature(compensation_fn)
    params = list(sig.parameters.keys())

    # Remove 'self' if present (for bound methods)
    if params and params[0] == "self":
        params = params[1:]

    # New signature: (ctx, compensation_results) or (ctx, comp_results=None)
    # Context-only signature: (ctx)
    return len(params) >= 2 or (
        (len(params) == 2 and "comp_results" in params) or "compensation_results" in params
    )
