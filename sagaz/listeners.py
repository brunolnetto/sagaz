"""
Saga Listeners - Observer pattern for saga lifecycle events.

Provides a clean way to add cross-cutting concerns (logging, metrics,
tracing, outbox publishing) to all saga steps without decorating each one.

Example:
    >>> from sagaz import Saga, step
    >>> from sagaz.listeners import SagaListener, MetricsSagaListener
    >>>
    >>> class OrderSaga(Saga):
    ...     saga_name = "order-processing"
    ...     listeners = [MetricsSagaListener(), LoggingSagaListener()]
    ...
    ...     @step("create_order")
    ...     async def create_order(self, ctx):
    ...         return {"order_id": "ORD-123"}
"""

import logging
from abc import ABC
from typing import Any

logger = logging.getLogger(__name__)


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


class LoggingSagaListener(SagaListener):
    """
    Logs all saga lifecycle events.

    Use this for debugging and observability.

    Example:
        >>> class OrderSaga(Saga):
        ...     listeners = [LoggingSagaListener(level=logging.DEBUG)]
    """

    def __init__(self, logger_instance: logging.Logger | None = None, level: int = logging.INFO):
        self.log = logger_instance or logger
        self.level = level

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        self.log.log(self.level, f"[SAGA] Starting: {saga_name} (id={saga_id})")

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        self.log.log(self.level, f"[STEP] Entering: {saga_name}.{step_name}")

    async def on_step_success(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], result: Any
    ) -> None:
        self.log.log(self.level, f"[STEP] Success: {saga_name}.{step_name}")

    async def on_step_failure(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self.log.error(f"[STEP] Failed: {saga_name}.{step_name} - {error}")

    async def on_compensation_start(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        self.log.log(self.level, f"[COMPENSATION] Starting: {saga_name}.{step_name}")

    async def on_compensation_complete(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        self.log.log(self.level, f"[COMPENSATION] Complete: {saga_name}.{step_name}")

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        self.log.log(self.level, f"[SAGA] Completed: {saga_name} (id={saga_id})")

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        self.log.error(f"[SAGA] Failed: {saga_name} (id={saga_id}) - {error}")


class MetricsSagaListener(SagaListener):
    """
    Records saga metrics using the existing SagaMetrics class.

    Integrates withsagaz.monitoring.metrics for consistent metrics collection.

    Example:
        >>> from sagaz.monitoring.metrics import SagaMetrics
        >>> metrics = SagaMetrics()
        >>>
        >>> class OrderSaga(Saga):
        ...     listeners = [MetricsSagaListener(metrics=metrics)]
    """

    def __init__(self, metrics=None):
        if metrics is None:
            from sagaz.monitoring.metrics import SagaMetrics

            metrics = SagaMetrics()
        self.metrics = metrics
        self._start_times: dict[str, float] = {}

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        import time

        self._start_times[saga_id] = time.time()

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        import time

        from sagaz.types import SagaStatus

        start_time = self._start_times.pop(saga_id, time.time())
        duration = time.time() - start_time
        self.metrics.record_execution(saga_name, SagaStatus.COMPLETED, duration)

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        import time

        from sagaz.types import SagaStatus

        start_time = self._start_times.pop(saga_id, time.time())
        duration = time.time() - start_time
        self.metrics.record_execution(saga_name, SagaStatus.FAILED, duration)


class TracingSagaListener(SagaListener):
    """
    Provides distributed tracing using the existing SagaTracer class.

    Integrates withsagaz.monitoring.tracing for OpenTelemetry support.

    Example:
        >>> from sagaz.monitoring.tracing import setup_tracing
        >>> tracer = setup_tracing("order-service")
        >>>
        >>> class OrderSaga(Saga):
        ...     listeners = [TracingSagaListener(tracer=tracer)]
    """

    def __init__(self, tracer=None):
        if tracer is None:
            from sagaz.monitoring.tracing import saga_tracer

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


class OutboxSagaListener(SagaListener):
    """
    Publishes saga events to outbox storage for reliable event delivery.

    Events are published with topic format: {saga_name}.{event_type}

    Example:
        >>> from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage
        >>> storage = PostgreSQLOutboxStorage(conn_string)
        >>>
        >>> class OrderSaga(Saga):
        ...     saga_name = "order-processing"
        ...     listeners = [OutboxSagaListener(storage=storage)]
        >>>
        >>> # Events published:
        >>> # - order-processing.create_order.success
        >>> # - order-processing.completed
    """

    def __init__(self, storage, publish_step_events: bool = True):
        self.storage = storage
        self.publish_step_events = publish_step_events

    async def on_step_success(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], result: Any
    ) -> None:
        if not self.publish_step_events:
            return

        await self._publish_event(
            saga_id=ctx.get("saga_id", "unknown"),
            event_type=f"{saga_name}.{step_name}.success",
            payload={
                "step": step_name,
                "result": result if isinstance(result, dict) else {},
            },
        )

    async def on_step_failure(
        self, saga_name: str, step_name: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        await self._publish_event(
            saga_id=ctx.get("saga_id", "unknown"),
            event_type=f"{saga_name}.{step_name}.failed",
            payload={
                "step": step_name,
                "error": str(error),
                "error_type": type(error).__name__,
            },
        )

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        await self._publish_event(
            saga_id=saga_id,
            event_type=f"{saga_name}.completed",
            payload={
                "saga_id": saga_id,
                "status": "completed",
            },
        )

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        await self._publish_event(
            saga_id=saga_id,
            event_type=f"{saga_name}.failed",
            payload={
                "saga_id": saga_id,
                "status": "failed",
                "error": str(error),
            },
        )

    async def on_compensation_complete(
        self, saga_name: str, step_name: str, ctx: dict[str, Any]
    ) -> None:
        await self._publish_event(
            saga_id=ctx.get("saga_id", "unknown"),
            event_type=f"{saga_name}.{step_name}.compensated",
            payload={
                "step": step_name,
                "compensated": True,
            },
        )

    async def _publish_event(self, saga_id: str, event_type: str, payload: dict) -> None:
        """Publish event to outbox storage."""
        from sagaz.outbox.types import OutboxEvent

        try:
            event = OutboxEvent(
                saga_id=saga_id,
                event_type=event_type,
                payload=payload,
            )
            await self.storage.insert(event)
        except Exception as e:
            logger.warning(f"Failed to publish outbox event {event_type}: {e}")


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
