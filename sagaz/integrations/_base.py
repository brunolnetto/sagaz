"""
Base integration utilities for Sagaz.

Provides framework-agnostic utilities used by all integrations:
- SagaContextManager: Thread-local context for request-scoped data
- Correlation ID generation and propagation
"""

import contextvars
import uuid
from contextlib import contextmanager
from typing import Any

from sagaz.core.logger import get_logger

logger = get_logger(__name__)


# Context variable for request-scoped saga context
_saga_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "saga_context", default={}
)


class SagaContextManager:
    """
    Thread-safe, request-scoped context manager for saga data.

    Uses Python's contextvars for proper async/thread isolation.

    Example:
        # In middleware
        with SagaContextManager.scope(correlation_id="abc-123", user_id="user-1"):
            # Handle request - all saga operations can access this context
            ...

        # In saga code
        correlation_id = SagaContextManager.get("correlation_id")
    """

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """Set a value in the current context."""
        ctx = _saga_context.get().copy()
        ctx[key] = value
        _saga_context.set(ctx)

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get a value from the current context."""
        return _saga_context.get().get(key, default)

    @classmethod
    def get_all(cls) -> dict[str, Any]:
        """Get all values in the current context."""
        return _saga_context.get().copy()

    @classmethod
    def clear(cls) -> None:
        """Clear the current context."""
        _saga_context.set({})

    @classmethod
    @contextmanager
    def scope(cls, **initial_values):
        """
        Create a new context scope with initial values.

        When exiting the scope, the previous context is restored.

        Args:
            **initial_values: Initial key-value pairs for the scope

        Example:
            with SagaContextManager.scope(correlation_id="123"):
                # This scope has correlation_id set
                ...
            # Previous context is restored
        """
        # Save current context
        token = _saga_context.set(initial_values.copy())
        try:
            yield
        finally:
            # Restore previous context
            _saga_context.reset(token)


def generate_correlation_id() -> str:
    """
    Generate a new unique correlation ID.

    Returns:
        A UUID string suitable for distributed tracing.
    """
    return str(uuid.uuid4())


def get_correlation_id() -> str:
    """
    Get the current correlation ID, generating one if needed.

    If a correlation ID is already set in the context, returns it.
    Otherwise, generates a new one and stores it in the context.

    Returns:
        The correlation ID string.
    """
    correlation_id = SagaContextManager.get("correlation_id")
    if correlation_id is None:
        correlation_id = generate_correlation_id()
        SagaContextManager.set("correlation_id", correlation_id)
    return str(correlation_id)
