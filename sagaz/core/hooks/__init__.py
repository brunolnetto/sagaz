"""
Sagaz Hooks - Convenience functions for step lifecycle hooks.

Provides helper functions to easily create common hook patterns
like publishing events to outbox on step success/failure.

Example:
    >>> from sagaz import Saga, step
    >>> from sagaz.core.hooks import publish_on_success, on_step_enter
    >>>
    >>> class OrderSaga(Saga):
    ...     @step(
    ...         "create_order",
    ...         on_success=publish_on_success(
    ...             storage=outbox_storage,
    ...             event_type="order.created"
    ...         )
    ...     )
    ...     async def create_order(self, ctx):
    ...         return {"order_id": "ORD-123"}
"""

from sagaz.core.hooks._decorators import (
    on_step_compensate,
    on_step_enter,
    on_step_exit,
    on_step_failure,
    on_step_success,
)
from sagaz.core.hooks._logging import log_step_lifecycle
from sagaz.core.hooks._publishing import (
    publish_on_compensate,
    publish_on_failure,
    publish_on_success,
)

__all__ = [
    "log_step_lifecycle",
    "on_step_compensate",
    "on_step_enter",
    "on_step_exit",
    "on_step_failure",
    "on_step_success",
    "publish_on_compensate",
    "publish_on_failure",
    "publish_on_success",
]
