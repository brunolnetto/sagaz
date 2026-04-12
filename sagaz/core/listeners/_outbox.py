"""Outbox listener for reliable event delivery."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from sagaz.core.listeners._base import SagaListener
from sagaz.core.logger import get_logger

logger = get_logger(__name__)


class OutboxSagaListener(SagaListener):
    """
    Publishes saga events to outbox storage for reliable event delivery.

    Events are published with topic format: {saga_name}.{event_type}

    Example:
        >>> from sagaz.outbox import PostgreSQLOutboxStorage
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
