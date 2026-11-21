"""
Decorators that trace saga actions and compensations with a SagaTracer.

Re-exported from :mod:`sagaz.observability.monitoring.tracing`.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import ParamSpec, Protocol, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class StepTracer(Protocol):
    """What the decorators need from a tracer; ``SagaTracer`` fits.

    A protocol, not an import of ``SagaTracer``: ``tracing`` re-exports this module's
    decorators, so importing it back from here would be a cycle.
    """

    def start_step_trace(
        self, saga_id: str, saga_name: str, step_name: str, step_type: str = ...
    ) -> AbstractContextManager[object]: ...


def trace_saga_action(tracer: StepTracer) -> Callable[[Callable[P, T]], Callable[P, T]]:
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


def trace_saga_compensation(tracer: StepTracer) -> Callable[[Callable[P, T]], Callable[P, T]]:
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
