"""Convenience factory for common listener combinations."""

from typing import TYPE_CHECKING

from sagaz.core.listeners._base import SagaListener
from sagaz.core.listeners._logging import LoggingSagaListener
from sagaz.core.listeners._metrics import MetricsSagaListener
from sagaz.core.listeners._outbox import OutboxSagaListener
from sagaz.core.listeners._tracing import TracingSagaListener

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces.outbox import OutboxStorage


# Convenience function to create common listener combinations
def default_listeners(
    metrics: bool = True,
    logging_enabled: bool = True,
    tracing: bool = False,
    outbox_storage: "OutboxStorage | None" = None,
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
