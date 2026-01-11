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

from sagaz.core.listeners import SagaListener
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
    "sagaz_webhook_status_view",
    "sagaz_webhook_view",
]


# Global tracking for webhook status (in-memory for demo)
_webhook_tracking: dict[str, dict[str, Any]] = {}
_saga_to_webhook: dict[str, str] = {}  # saga_id -> correlation_id mapping
_listener_registered = False


class _WebhookStatusListener(SagaListener):
    """Internal listener to track saga outcomes for webhook status."""

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        """Mark saga as successful in webhook tracking."""
        correlation_id = _saga_to_webhook.get(saga_id)
        if correlation_id and correlation_id in _webhook_tracking:
            if "saga_statuses" not in _webhook_tracking[correlation_id]:
                _webhook_tracking[correlation_id]["saga_statuses"] = {}
            _webhook_tracking[correlation_id]["saga_statuses"][saga_id] = "completed"

    async def on_saga_failed(
        self, saga_name: str, saga_id: str, ctx: dict[str, Any], error: Exception
    ) -> None:
        """Mark saga as failed in webhook tracking."""
        correlation_id = _saga_to_webhook.get(saga_id)
        if correlation_id and correlation_id in _webhook_tracking:
            if "saga_statuses" not in _webhook_tracking[correlation_id]:
                _webhook_tracking[correlation_id]["saga_statuses"] = {}
            _webhook_tracking[correlation_id]["saga_statuses"][saga_id] = "failed"
            _webhook_tracking[correlation_id]["saga_errors"] = _webhook_tracking[
                correlation_id
            ].get("saga_errors", {})
            _webhook_tracking[correlation_id]["saga_errors"][saga_id] = str(error)


def _ensure_listener_registered():
    """Ensure webhook status listener is registered (called lazily on first use)."""
    global _listener_registered
    if not _listener_registered:
        from sagaz.core.config import get_config

        # Add webhook status listener to config
        config = get_config()
        if _WebhookStatusListener not in [type(listener) for listener in config.listeners]:
            config._listeners.append(_WebhookStatusListener())
        _listener_registered = True
        logger.info("Sagaz Django initialized with webhook status tracking")


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
    return _webhook_tracking.get(correlation_id)


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

    # Ensure listener is registered on first webhook
    _ensure_listener_registered()

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    # Generate correlation ID for tracking
    correlation_id = request.headers.get("X-Correlation-ID") or generate_correlation_id()

    # Store correlation -> saga mapping for status checks
    _webhook_tracking[correlation_id] = {"status": "queued", "saga_ids": [], "source": source}

    # Fire event in background thread (fire-and-forget)
    def process_in_thread():
        from sagaz.triggers import fire_event

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            _webhook_tracking[correlation_id]["status"] = "processing"
            saga_ids = loop.run_until_complete(fire_event(source, payload))
            _webhook_tracking[correlation_id]["saga_ids"] = saga_ids

            # Map saga IDs to correlation ID for status tracking
            for saga_id in saga_ids:
                _saga_to_webhook[saga_id] = correlation_id

            # Check if any saga_ids already have completion status (idempotent case)
            from sagaz.core.config import get_config

            config = get_config()
            if config.storage and saga_ids:
                for saga_id in saga_ids:
                    try:
                        state = loop.run_until_complete(config.storage.load_saga_state(saga_id))
                        if state:
                            # Saga already exists - populate status immediately
                            if "saga_statuses" not in _webhook_tracking[correlation_id]:
                                _webhook_tracking[correlation_id]["saga_statuses"] = {}

                            from sagaz.core.types import SagaStatus

                            status_val = state.get("status")
                            if status_val == SagaStatus.COMPLETED:
                                _webhook_tracking[correlation_id]["saga_statuses"][saga_id] = (
                                    "completed"
                                )
                            elif status_val in (SagaStatus.FAILED, SagaStatus.ROLLED_BACK):
                                _webhook_tracking[correlation_id]["saga_statuses"][saga_id] = (
                                    "failed"
                                )
                                if state.get("error"):
                                    if "saga_errors" not in _webhook_tracking[correlation_id]:
                                        _webhook_tracking[correlation_id]["saga_errors"] = {}
                                    _webhook_tracking[correlation_id]["saga_errors"][saga_id] = (
                                        state["error"]
                                    )
                    except Exception:
                        pass  # status will be tracked via listener

            # Mark as triggered (saga outcomes will be tracked by listener for new sagas)
            _webhook_tracking[correlation_id]["status"] = "triggered"
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


def sagaz_webhook_status_view(request, source: str, correlation_id: str):
    """
    Django view for checking webhook event status.

    Usage in urls.py:
        from sagaz.integrations.django import sagaz_webhook_status_view

        urlpatterns = [
            path('webhooks/<str:source>/status/<str:correlation_id>/',
                 sagaz_webhook_status_view),
        ]
    """
    try:
        from django.http import JsonResponse
    except ImportError:  # pragma: no cover
        msg = "Django is required. Install with: pip install django"
        raise ImportError(msg)

    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    status = get_webhook_status(correlation_id)

    if not status:
        return JsonResponse(
            {
                "correlation_id": correlation_id,
                "source": source,
                "status": "not_found",
                "message": "No webhook event found with this correlation ID",
            },
            status=404,
        )

    # Compute overall status based on individual saga statuses
    saga_statuses = status.get("saga_statuses", {})
    saga_ids = status.get("saga_ids", [])
    overall_status = status["status"]

    # If triggered, check if all sagas have finished
    if overall_status == "triggered" and saga_ids:
        finished_count = sum(1 for s in saga_statuses.values() if s in ("completed", "failed"))
        if finished_count == len(saga_ids):
            # All sagas finished - determine overall outcome
            failed_count = sum(1 for s in saga_statuses.values() if s == "failed")
            if failed_count == len(saga_ids):
                # All sagas failed
                overall_status = "failed"
            elif failed_count > 0:
                # Some failed, some succeeded
                overall_status = "completed_with_failures"
            else:
                # All succeeded
                overall_status = "completed"

    response_data = {
        "correlation_id": correlation_id,
        "source": source,
        "status": overall_status,
        "saga_ids": saga_ids,
    }

    # Add saga details if available
    if saga_statuses:
        response_data["saga_statuses"] = saga_statuses

    if "saga_errors" in status:
        response_data["saga_errors"] = status["saga_errors"]

    if "error" in status:
        response_data["error"] = status["error"]

    # Add helpful messages based on status
    if overall_status == "queued":
        response_data["message"] = "Event is queued for processing"
    elif overall_status == "processing":
        response_data["message"] = "Event is currently being processed"
    elif overall_status == "triggered":
        response_data["message"] = (
            f"Event triggered {len(saga_ids)} saga(s), waiting for completion"
        )
    elif overall_status == "completed":
        response_data["message"] = f"All {len(saga_ids)} saga(s) completed successfully"
    elif overall_status == "completed_with_failures":
        failed_count = sum(1 for s in saga_statuses.values() if s == "failed")
        response_data["message"] = f"{failed_count} of {len(saga_ids)} saga(s) failed"
    elif overall_status == "failed":
        if len(saga_ids) == 1:
            response_data["message"] = "Saga execution failed"
        else:
            response_data["message"] = f"All {len(saga_ids)} saga(s) failed"

    return JsonResponse(response_data)
