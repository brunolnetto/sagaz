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
from sagaz.core.listeners._defaults import default_listeners
from sagaz.core.listeners._logging import LoggingSagaListener
from sagaz.core.listeners._metrics import MetricsSagaListener
from sagaz.core.listeners._outbox import OutboxSagaListener
from sagaz.core.listeners._tracing import TracingSagaListener

__all__ = [
    "LoggingSagaListener",
    "MetricsSagaListener",
    "OutboxSagaListener",
    "SagaListener",
    "TracingSagaListener",
    "default_listeners",
]
