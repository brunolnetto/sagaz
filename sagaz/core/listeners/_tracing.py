"""Tracing listener for distributed tracing support."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from sagaz.core.listeners._base import SagaListener
from sagaz.core.logger import get_logger

logger = get_logger(__name__)


class TracingSagaListener(SagaListener):
    """
    Provides distributed tracing using the existing SagaTracer class.

    Integrates with sagaz.monitoring.tracing for OpenTelemetry support.

    Example:
        >>> from sagaz.observability.monitoring.tracing import setup_tracing
        >>> tracer = setup_tracing("order-service")
        >>>
        >>> class OrderSaga(Saga):
        ...     listeners = [TracingSagaListener(tracer=tracer)]
    """

    def __init__(self, tracer=None):
        if tracer is None:
            from sagaz.observability.monitoring.tracing import saga_tracer

            tracer = saga_tracer
        self.tracer = tracer

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        total_steps = len(ctx.get("_steps", []))
        self.tracer.start_saga_trace(saga_id, saga_name, total_steps)

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        saga_id = ctx.get("saga_id", "unknown")
        self.tracer.start_step_trace(saga_id, saga_name, step_name, step_type="action")

    async def on_compensation_start(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        saga_id = ctx.get("saga_id", "unknown")
        self.tracer.start_step_trace(saga_id, saga_name, step_name, step_type="compensation")
