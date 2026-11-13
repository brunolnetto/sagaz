"""
Decorators that trace saga actions and compensations with a SagaTracer.

Re-exported from :mod:`sagaz.observability.monitoring.tracing`.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import TYPE_CHECKING, ParamSpec, TypeVar

if TYPE_CHECKING:
    from sagaz.observability.monitoring.tracing import SagaTracer

P = ParamSpec("P")
T = TypeVar("T")


def trace_saga_action(tracer: SagaTracer):
    """
    Decorator to automatically trace saga actions

    Usage:
        @trace_saga_action(saga_tracer)
        async def my_action(ctx: SagaContext) -> Any:
            # Action implementation
            pass
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extract saga context from arguments
            saga_context = None
            for arg in args:
                if hasattr(arg, "saga_id"):
                    saga_context = arg
                    break

            if not saga_context:
                # No saga context found, execute without tracing
                return await func(*args, **kwargs)  # type: ignore[no-any-return, misc]

            step_name = getattr(saga_context, "step_name", func.__name__)
            saga_id = getattr(saga_context, "saga_id", "unknown")
            saga_name = getattr(saga_context, "saga_name", "unknown")

            with tracer.start_step_trace(saga_id, saga_name, step_name, "action"):
                return await func(*args, **kwargs)  # type: ignore[no-any-return, misc]

        return wrapper  # type: ignore[return-value]

    return decorator


def trace_saga_compensation(tracer: SagaTracer):
    """
    Decorator to automatically trace saga compensations

    Usage:
        @trace_saga_compensation(saga_tracer)
        async def my_compensation(result: Any, ctx: SagaContext) -> None:
            # Compensation implementation
            pass
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extract saga context from arguments (usually second arg)
            saga_context = None
            if len(args) >= 2 and hasattr(args[1], "saga_id"):
                saga_context = args[1]

            if not saga_context:
                return await func(*args, **kwargs)  # type: ignore[no-any-return, misc]

            step_name = getattr(saga_context, "step_name", func.__name__)
            saga_id = getattr(saga_context, "saga_id", "unknown")
            saga_name = getattr(saga_context, "saga_name", "unknown")

            with tracer.start_step_trace(saga_id, saga_name, step_name, "compensation"):
                return await func(*args, **kwargs)  # type: ignore[no-any-return, misc]

        return wrapper  # type: ignore[return-value]

    return decorator
