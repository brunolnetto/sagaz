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
)
from sagaz.integrations._django_webhooks import (
    _build_webhook_status_response,
    _check_existing_saga_status,
    _ensure_listener_registered,
    _saga_to_webhook,
    _webhook_status_not_found_response,
    _webhook_tracking,
    get_webhook_status,
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


def get_sagaz_config() -> dict[str, Any]:
    """
    Get Sagaz configuration from Django settings.

    Returns:
        Configuration dictionary from django.conf.settings.SAGAZ
    """
    try:
        from django.conf import settings

        return getattr(settings, "SAGAZ", {})
    except ImportError:
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
    except ImportError as exc:
        msg = "Django is required. Install with: pip install django"
        raise ImportError(msg) from exc

    _ensure_listener_registered()

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    correlation_id = request.headers.get("X-Correlation-ID") or generate_correlation_id()

    is_valid, error_response = _validate_idempotency_requirements(source, payload)
    if not is_valid:
        return error_response

    _webhook_tracking[correlation_id] = {"status": "queued", "saga_ids": [], "source": source}

    def process_in_thread():
        from sagaz.core.triggers import fire_event

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            _webhook_tracking[correlation_id]["status"] = "processing"
            saga_ids = loop.run_until_complete(fire_event(source, payload))
            _webhook_tracking[correlation_id]["saga_ids"] = saga_ids

            for saga_id in saga_ids:
                _saga_to_webhook[saga_id] = correlation_id

            _check_existing_saga_status(loop, saga_ids, correlation_id)

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
    )


def _validate_idempotency_requirements(source: str, payload: dict) -> tuple[bool, dict | None]:
    """Validate idempotency requirements for triggers.

    Returns:
        Tuple of (is_valid, error_response)
    """
    try:
        from sagaz.core.exceptions import IdempotencyKeyMissingInPayloadError
        from sagaz.core.triggers.registry import TriggerRegistry

        triggers = TriggerRegistry.get_triggers(source)
        for trigger in triggers:
            metadata = trigger.metadata
            if metadata.idempotency_key:
                key_name = (
                    metadata.idempotency_key if isinstance(metadata.idempotency_key, str) else None
                )
                if key_name and isinstance(payload, dict) and key_name not in payload:
                    raise IdempotencyKeyMissingInPayloadError(
                        saga_name=trigger.saga_class.__name__,
                        source=source,
                        key_name=key_name,
                        payload_keys=list(payload.keys()) if isinstance(payload, dict) else [],
                    )
    except IdempotencyKeyMissingInPayloadError as e:
        from django.http import JsonResponse

        return False, JsonResponse(
            {
                "status": "rejected",
                "source": source,
                "error": "missing_idempotency_key",
                "message": f"Required field '{e.key_name}' is missing from payload",
                "details": {
                    "saga": e.saga_name,
                    "required_field": e.key_name,
                    "payload_keys": e.payload_keys,
                },
                "help": f"Include '{e.key_name}' in your request payload to ensure idempotent processing",
            },
            status=400,
        )
    return True, None


def sagaz_webhook_status_view(request, source: str, correlation_id: str):
    """Django view for checking webhook event status."""
    try:
        from django.http import JsonResponse
    except ImportError as exc:
        msg = "Django is required. Install with: pip install django"
        raise ImportError(msg) from exc

    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    status = get_webhook_status(correlation_id)

    if not status:
        return _webhook_status_not_found_response(correlation_id, source)

    response_data = _build_webhook_status_response(status, correlation_id, source)
    return JsonResponse(response_data)
