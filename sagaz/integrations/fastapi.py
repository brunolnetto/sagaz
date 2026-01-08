"""
FastAPI integration for Sagaz.

Provides:
- Lifespan hooks for saga initialization (composable)
- Middleware for correlation ID propagation
- Background saga task runner
- Webhook router factory for event triggers (async, fire-and-forget)
"""

from typing import Any, Callable
from contextlib import asynccontextmanager
import asyncio

from sagaz.logger import get_logger
from sagaz.integrations._base import (
    SagaContextManager,
    generate_correlation_id,
    get_correlation_id,
)

logger = get_logger(__name__)

__all__ = [
    "get_logger",
    "SagaContextManager",
    "generate_correlation_id",
    "get_correlation_id",
    "create_webhook_router",
    "sagaz_startup",
    "sagaz_shutdown",
]


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
        from fastapi import APIRouter, Request, BackgroundTasks
        from fastapi.responses import JSONResponse
    except ImportError:  # pragma: no cover
        raise ImportError("FastAPI is required for this integration. Install with: pip install fastapi")
    
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
        
        # Fire event in background (fire-and-forget)
        async def process_event():
            try:
                saga_ids = await fire_event(source, payload)
                logger.debug(f"Webhook {source} triggered sagas: {saga_ids}")
            except Exception as e:
                logger.error(f"Webhook {source} processing error: {e}")
        
        background_tasks.add_task(process_event)
        
        return JSONResponse(
            status_code=202,  # Accepted
            content={
                "status": "accepted",
                "source": source,
                "message": "Event queued for processing"
            }
        )
    
    return router
