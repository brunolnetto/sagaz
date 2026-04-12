"""
Saga Listeners - Observer pattern for saga lifecycle events.

Provides a clean way to add cross-cutting concerns (logging, metrics,
tracing, outbox publishing) to all saga steps without decorating each one.

Example:
    >>> from sagaz import Saga, step
    >>> from sagaz.core.listeners import SagaListener, MetricsSagaListener
    >>>
    >>> class OrderSaga(Saga):
    ...     saga_name = "order-processing"
    ...     listeners = [MetricsSagaListener(), LoggingSagaListener()]
    ...
    ...     @step("create_order")
    ...     async def create_order(self, ctx):
    ...         return {"order_id": "ORD-123"}
"""

from abc import ABC
from typing import Any

from sagaz.core.listeners._logging import LoggingSagaListener
from sagaz.core.listeners._metrics import MetricsSagaListener
from sagaz.core.listeners._outbox import OutboxSagaListener
from sagaz.core.listeners._tracing import TracingSagaListener
from sagaz.core.logger import get_logger

logger = get_logger(__name__)


class SagaListener(ABC):
    """
    Base class for saga event listeners.

    Subclass this to create custom listeners that respond to saga lifecycle
    events. All methods are optional - implement only what you need.

    Listeners are called in the order they appear in the `listeners` list.
    Errors in listeners are logged but do not break saga execution.
    """

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        """Called when saga execution begins."""

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        """Called before each step executes."""

    async def on_step_success(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], result: Any
    ) -> None:
        """Called after successful step completion."""

    async def on_step_failure(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        """Called when a step fails."""

    async def on_compensation_start(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        """Called before compensation runs for a step."""

    async def on_compensation_complete(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        """Called after compensation completes for a step."""

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        """Called when saga completes successfully."""

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        """Called when saga fails (after compensation attempts)."""


# Convenience function to create common listener combinations
def default_listeners(
    metrics: bool = True,
    logging_enabled: bool = True,
    tracing: bool = False,
    outbox_storage=None,
) -> list[SagaListener]:
    """
    Create a list of commonly used listeners.

    Args:
        metrics: Include MetricsSagaListener
        logging_enabled: Include LoggingSagaListener
        tracing: Include TracingSagaListener
        outbox_storage: If provided, include OutboxSagaListener

    Returns:
        List of configured listeners

    Example:
        >>> class OrderSaga(Saga):
        ...     listeners = default_listeners(metrics=True, logging=True)
    """
    listeners: list[SagaListener] = []

    if logging_enabled:
        listeners.append(LoggingSagaListener())

    if metrics:
        listeners.append(MetricsSagaListener())

    if tracing:
        listeners.append(TracingSagaListener())

    if outbox_storage:
        listeners.append(OutboxSagaListener(storage=outbox_storage))

    return listeners


__all__ = [
    "LoggingSagaListener",
    "MetricsSagaListener",
    "OutboxSagaListener",
    "SagaListener",
    "TracingSagaListener",
    "default_listeners",
]
