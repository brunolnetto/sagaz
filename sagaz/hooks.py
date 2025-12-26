"""
Sagaz Hooks - Convenience functions for step lifecycle hooks.

Provides helper functions to easily create common hook patterns
like publishing events to outbox on step success/failure.

Example:
    >>> from sagaz import Saga, step
    >>> from sagaz.hooks import publish_on_success, on_step_enter
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

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def on_step_enter(func: Callable) -> Callable:
    """
    Decorator to mark a function as an on_enter hook.

    This is optional - any async/sync function can be used as a hook.
    This decorator is mainly for documentation purposes.

    Example:
        >>> @on_step_enter
        ... async def log_step_start(ctx, step_name):
        ...     logger.info(f"Starting step: {step_name}")
    """
    return func


def on_step_success(func: Callable) -> Callable:
    """Decorator to mark a function as an on_success hook."""
    return func


def on_step_failure(func: Callable) -> Callable:
    """Decorator to mark a function as an on_failure hook."""
    return func


def on_step_compensate(func: Callable) -> Callable:
    """Decorator to mark a function as an on_compensate hook."""
    return func


def publish_on_success(
    storage,
    event_type: str,
    payload_builder: Callable[[dict[str, Any], Any], dict[str, Any]] | None = None,
    aggregate_type: str = "saga",
) -> Callable:
    """
    Create a hook that publishes an event to outbox on step success.

    Args:
        storage: OutboxStorage instance to use for publishing
        event_type: Event type string (e.g., "order.created")
        payload_builder: Optional function (ctx, result) -> payload dict
        aggregate_type: Aggregate type for the event

    Returns:
        Hook function suitable for on_success parameter

    Example:
        >>> @step(
        ...     "create_order",
        ...     on_success=publish_on_success(
        ...         storage=outbox_storage,
        ...         event_type="order.created",
        ...         payload_builder=lambda ctx, r: {"order_id": r["order_id"]}
        ...     )
        ... )
        ... async def create_order(self, ctx):
        ...     return {"order_id": "ORD-123"}
    """
    from sagaz.outbox.types import OutboxEvent

    async def hook(ctx: dict[str, Any], step_name: str, result: Any):
        # Build payload
        if payload_builder:
            payload = payload_builder(ctx, result)
        else:
            payload = result if isinstance(result, dict) else {"result": result}

        # Create and insert event
        event = OutboxEvent(
            saga_id=ctx.get("saga_id", "unknown"),
            event_type=event_type,
            payload=payload,
            aggregate_type=aggregate_type,
            aggregate_id=ctx.get("aggregate_id", ctx.get("saga_id", "unknown")),
        )

        try:
            await storage.insert(event)
            logger.debug(f"Published event {event_type} for step {step_name}")
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")

    return hook


def publish_on_failure(
    storage,
    event_type: str,
    include_error: bool = True,
    aggregate_type: str = "saga",
) -> Callable:
    """
    Create a hook that publishes a failure event to outbox.

    Args:
        storage: OutboxStorage instance
        event_type: Event type string (e.g., "order.failed")
        include_error: Whether to include error message in payload
        aggregate_type: Aggregate type for the event

    Returns:
        Hook function suitable for on_failure parameter
    """
    from sagaz.outbox.types import OutboxEvent

    async def hook(ctx: dict[str, Any], step_name: str, error: Exception):
        payload = {
            "step": step_name,
            "saga_id": ctx.get("saga_id", "unknown"),
        }

        if include_error:
            payload["error"] = str(error)
            payload["error_type"] = type(error).__name__

        event = OutboxEvent(
            saga_id=ctx.get("saga_id", "unknown"),
            event_type=event_type,
            payload=payload,
            aggregate_type=aggregate_type,
            aggregate_id=ctx.get("aggregate_id", ctx.get("saga_id", "unknown")),
        )

        try:
            await storage.insert(event)
            logger.debug(f"Published failure event {event_type} for step {step_name}")
        except Exception as e:
            logger.warning(f"Failed to publish failure event {event_type}: {e}")

    return hook


def publish_on_compensate(
    storage,
    event_type: str,
    aggregate_type: str = "saga",
) -> Callable:
    """
    Create a hook that publishes a compensation event to outbox.

    Args:
        storage: OutboxStorage instance
        event_type: Event type string (e.g., "order.cancelled")
        aggregate_type: Aggregate type for the event

    Returns:
        Hook function suitable for on_compensate parameter
    """
    from sagaz.outbox.types import OutboxEvent

    async def hook(ctx: dict[str, Any], step_name: str):
        payload = {
            "step": step_name,
            "saga_id": ctx.get("saga_id", "unknown"),
            "compensated": True,
        }

        event = OutboxEvent(
            saga_id=ctx.get("saga_id", "unknown"),
            event_type=event_type,
            payload=payload,
            aggregate_type=aggregate_type,
            aggregate_id=ctx.get("aggregate_id", ctx.get("saga_id", "unknown")),
        )

        try:
            await storage.insert(event)
            logger.debug(f"Published compensation event {event_type} for step {step_name}")
        except Exception as e:
            logger.warning(f"Failed to publish compensation event {event_type}: {e}")

    return hook


def log_step_lifecycle(logger_instance=None) -> dict[str, Callable]:
    """
    Create a set of hooks that log all step lifecycle events.

    Returns:
        Dict with on_enter, on_success, on_failure hooks

    Example:
        >>> hooks = log_step_lifecycle()
        >>> @step("my_step", **hooks)
        ... async def my_step(self, ctx):
        ...     ...
    """
    log = logger_instance or logger

    async def on_enter(ctx: dict[str, Any], step_name: str):
        log.info(f"[STEP] Entering: {step_name}")

    async def on_success(ctx: dict[str, Any], step_name: str, result: Any):
        log.info(f"[STEP] Success: {step_name}")

    async def on_failure(ctx: dict[str, Any], step_name: str, error: Exception):
        log.error(f"[STEP] Failed: {step_name} - {error}")

    return {
        "on_enter": on_enter,
        "on_success": on_success,
        "on_failure": on_failure,
    }
