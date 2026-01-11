"""
FastAPI integration for Sagaz.

Provides:
- Lifespan hooks for saga initialization (composable)
- Middleware for correlation ID propagation
- Background saga task runner
- Webhook router factory for event triggers (async, fire-and-forget)
- Webhook status tracking
"""

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from sagaz.core.logger import get_logger
from sagaz.integrations._base import (
    SagaContextManager,
    generate_correlation_id,
    get_correlation_id,
)

logger = get_logger(__name__)

__all__ = [
    "SagaContextManager",
    "create_webhook_router",
    "generate_correlation_id",
    "get_correlation_id",
    "get_logger",
    "get_webhook_status",
    "sagaz_shutdown",
    "sagaz_startup",
]

# Global tracking for webhook status (in-memory for demo)
_webhook_tracking: dict[str, dict[str, Any]] = {}


def get_webhook_status(correlation_id: str) -> dict[str, Any] | None:
    """
    Get status of a webhook event by correlation ID.

    Args:
        correlation_id: The correlation ID from the webhook response

    Returns:
        Status dictionary or None if not found

    Example:
        status = get_webhook_status("abc-123-xyz")
        if status:
            print(f"Status: {status['status']}")
            print(f"Saga IDs: {status['saga_ids']}")
    """
    return _webhook_tracking.get(correlation_id)


async def sagaz_startup():
    """
    Sagaz startup hook. Call this in your application's lifespan.

    Example:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await sagaz_startup()
            # ... your other startup code ...
            yield
            # ... your cleanup code ...
            await sagaz_shutdown()
    """
    logger.info("Sagaz initialized")


async def sagaz_shutdown():
    """
    Sagaz shutdown hook. Call this in your application's lifespan.
    """
    logger.info("Sagaz shutdown complete")


def create_webhook_router(url_prefix: str = "/webhooks"):
    """
    Create a FastAPI router for webhook event handling.

    The router exposes a POST endpoint that accepts JSON payloads
    and fires events via sagaz.triggers.fire_event().

    Events are processed asynchronously (fire-and-forget). The webhook
    returns immediately with "accepted" status.

    Args:
        url_prefix: URL prefix for webhook endpoints

    Returns:
        APIRouter instance

    Example:
        from fastapi import FastAPI
        from sagaz.integrations.fastapi import create_webhook_router

        app = FastAPI()
        app.include_router(create_webhook_router("/webhooks"))

        # Now POST /webhooks/stripe with JSON body will fire event "stripe"
    """
    try:
        from fastapi import APIRouter, BackgroundTasks, Request
        from fastapi.responses import JSONResponse
    except ImportError:  # pragma: no cover
        msg = "FastAPI is required for this integration. Install with: pip install fastapi"
        raise ImportError(msg)

    router = APIRouter(prefix=url_prefix, tags=["webhooks"])

    @router.post("/{source}")
    async def webhook_handler(source: str, request: Request, background_tasks: BackgroundTasks):
        """
        Handle incoming webhook events (fire-and-forget).

        The event is processed asynchronously in the background.
        Returns immediately with 202 Accepted.
        """
        from sagaz.triggers import fire_event

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        # Get or generate correlation ID
        correlation_id = request.headers.get("X-Correlation-ID") or generate_correlation_id()

        # Store initial status
        _webhook_tracking[correlation_id] = {
            "status": "queued",
            "saga_ids": [],
            "source": source,
        }

        # Fire event in background (fire-and-forget)
        async def process_event():
            try:
                _webhook_tracking[correlation_id]["status"] = "processing"
                saga_ids = await fire_event(source, payload)
                _webhook_tracking[correlation_id]["saga_ids"] = saga_ids
                _webhook_tracking[correlation_id]["status"] = "completed"
                logger.info(f"Webhook {source} triggered sagas: {saga_ids}")
            except Exception as e:
                _webhook_tracking[correlation_id]["status"] = "failed"
                _webhook_tracking[correlation_id]["error"] = str(e)
                logger.error(f"Webhook {source} processing error: {e}")

        background_tasks.add_task(process_event)

        return JSONResponse(
            status_code=202,  # Accepted
            content={
                "status": "accepted",
                "source": source,
                "message": "Event queued for processing",
                "correlation_id": correlation_id,
            },
        )

    @router.get("/{source}/status/{correlation_id}")
    async def webhook_status_handler(source: str, correlation_id: str):
        """
        Check status of a webhook event.

        Returns the current status of event processing.
        """
        status = get_webhook_status(correlation_id)

        if not status:
            return JSONResponse(
                status_code=404,
                content={
                    "correlation_id": correlation_id,
                    "source": source,
                    "status": "not_found",
                    "message": "No webhook event found with this correlation ID",
                },
            )

        response_data = {
            "correlation_id": correlation_id,
            "source": source,
            "status": status["status"],
            "saga_ids": status.get("saga_ids", []),
        }

        if "error" in status:
            response_data["error"] = status["error"]

        # Add helpful messages based on status
        if status["status"] == "queued":
            response_data["message"] = "Event is queued for processing"
        elif status["status"] == "processing":
            response_data["message"] = "Event is currently being processed"
        elif status["status"] == "completed":
            response_data["message"] = (
                f"Event processed successfully, triggered {len(status['saga_ids'])} saga(s)"
            )
        elif status["status"] == "failed":
            response_data["message"] = "Event processing failed"

        return JSONResponse(content=response_data)

    return router
