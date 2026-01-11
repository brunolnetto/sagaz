"""
Django integration for Sagaz.

Provides:
- Django app configuration
- Middleware for correlation ID propagation
- Webhook view for event triggers (async, fire-and-forget)
"""

import asyncio
import json
import threading
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
    "SagaDjangoMiddleware",
    "create_saga",
    "get_logger",
    "get_sagaz_config",
    "get_webhook_status",
    "run_saga_sync",
    "sagaz_webhook_view",
]


def get_sagaz_config() -> dict[str, Any]:
    """
    Get Sagaz configuration from Django settings.

    Returns:
        Configuration dictionary from django.conf.settings.SAGAZ
    """
    try:
        from django.conf import settings

        return getattr(settings, "SAGAZ", {})
    except ImportError:  # pragma: no cover
        return {}


def run_saga_sync(saga, context: dict[str, Any]) -> dict[str, Any]:
    """
    Run a saga synchronously (blocking).

    Useful for Django views that need to wait for saga completion.

    Args:
        saga: The saga instance to run
        context: The saga context

    Returns:
        The saga result
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(saga.run(context))
    finally:
        loop.close()


def create_saga(saga_class: type) -> Any:
    """
    Create a saga instance with correlation ID from context.

    Args:
        saga_class: The saga class to instantiate

    Returns:
        A new saga instance
    """
    saga = saga_class()
    correlation_id = SagaContextManager.get("correlation_id")
    if correlation_id and hasattr(saga, "correlation_id"):
        saga.correlation_id = correlation_id
    return saga


class SagaDjangoMiddleware:
    """
    Django middleware for Sagaz correlation ID propagation.

    Sets up correlation ID for each request and clears context after.

    Usage in settings.py:
        MIDDLEWARE = [
            ...
            'sagaz.integrations.django.SagaDjangoMiddleware',
        ]
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Get or generate correlation ID
        correlation_id = request.META.get("HTTP_X_CORRELATION_ID", generate_correlation_id())

        # Set on request and context
        request.saga_correlation_id = correlation_id
        SagaContextManager.set("correlation_id", correlation_id)

        try:
            response = self.get_response(request)

            # Add correlation ID to response
            response["X-Correlation-ID"] = correlation_id

            return response
        finally:
            # Clear context after request
            SagaContextManager.clear()


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
    tracking = getattr(sagaz_webhook_view, "_tracking", {})
    return tracking.get(correlation_id)


def sagaz_webhook_view(request, source: str):
    """
    Django view for handling webhook events (fire-and-forget).

    Events are processed asynchronously in a background thread.
    Returns immediately with 202 Accepted.

    Usage in urls.py:
        from django.views.decorators.csrf import csrf_exempt
        from sagaz.integrations.django import sagaz_webhook_view

        urlpatterns = [
            path('webhooks/<str:source>/', csrf_exempt(sagaz_webhook_view)),
        ]
    """
    try:
        from django.http import JsonResponse
    except ImportError:  # pragma: no cover
        msg = "Django is required. Install with: pip install django"
        raise ImportError(msg)

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    # Generate correlation ID for tracking
    correlation_id = request.headers.get("X-Correlation-ID") or generate_correlation_id()

    # Store correlation -> saga mapping for status checks
    _webhook_tracking = getattr(sagaz_webhook_view, "_tracking", {})
    _webhook_tracking[correlation_id] = {"status": "queued", "saga_ids": [], "source": source}
    sagaz_webhook_view._tracking = _webhook_tracking

    # Fire event in background thread (fire-and-forget)
    def process_in_thread():
        from sagaz.triggers import fire_event

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            _webhook_tracking[correlation_id]["status"] = "processing"
            saga_ids = loop.run_until_complete(fire_event(source, payload))
            _webhook_tracking[correlation_id]["saga_ids"] = saga_ids
            _webhook_tracking[correlation_id]["status"] = "completed"
            logger.info(f"Webhook {source} triggered sagas: {saga_ids}")
        except Exception as e:
            _webhook_tracking[correlation_id]["status"] = "failed"
            _webhook_tracking[correlation_id]["error"] = str(e)
            logger.error(f"Webhook {source} processing error: {e}")
        finally:
            loop.close()

    thread = threading.Thread(target=process_in_thread, daemon=True)
    thread.start()

    return JsonResponse(
        {
            "status": "accepted",
            "source": source,
            "message": "Event queued for processing",
            "correlation_id": correlation_id,
        },
        status=202,
    )  # Accepted
