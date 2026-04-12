"""Hook decorator utilities for documentation purposes."""

from collections.abc import Callable


def on_step_enter(func: Callable) -> Callable:
    """
    Decorator to mark a function as an on_enter hook.

    This is optional - any async/sync function can be used as a hook.
    This decorator is mainly for documentation purposes.

    Example:
        >>> @on_step_enter
        ... async def log_step_start(ctx, step_name):
        ...     logger.info(f"Starting step: {step_name}")
    """
    return func


def on_step_success(func: Callable) -> Callable:
    """Decorator to mark a function as an on_success hook."""
    return func


def on_step_failure(func: Callable) -> Callable:
    """Decorator to mark a function as an on_failure hook."""
    return func


def on_step_compensate(func: Callable) -> Callable:
    """Decorator to mark a function as an on_compensate hook."""
    return func
