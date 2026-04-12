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

from sagaz.core.listeners._base import SagaListener

# Import after SagaListener is defined to avoid circular imports
from sagaz.core.listeners._logging import LoggingSagaListener
from sagaz.core.listeners._metrics import MetricsSagaListener
from sagaz.core.listeners._outbox import OutboxSagaListener
from sagaz.core.listeners._tracing import TracingSagaListener


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

