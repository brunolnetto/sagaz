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
        from sagaz.triggers import fire_event

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
        from sagaz.triggers.registry import TriggerRegistry

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


def _update_saga_status(correlation_id: str, saga_id: str, status_val, state: dict):
    """Update webhook tracking with saga status."""
    if "saga_statuses" not in _webhook_tracking[correlation_id]:
        _webhook_tracking[correlation_id]["saga_statuses"] = {}

    from sagaz.core.types import SagaStatus

    if status_val == SagaStatus.COMPLETED:
        _webhook_tracking[correlation_id]["saga_statuses"][saga_id] = "completed"
    elif status_val in (SagaStatus.FAILED, SagaStatus.ROLLED_BACK):
        _webhook_tracking[correlation_id]["saga_statuses"][saga_id] = "failed"
        if state.get("error"):
            if "saga_errors" not in _webhook_tracking[correlation_id]:
                _webhook_tracking[correlation_id]["saga_errors"] = {}
            _webhook_tracking[correlation_id]["saga_errors"][saga_id] = state["error"]


def _check_existing_saga_status(loop, saga_ids: list[str], correlation_id: str):
    """Check if sagas already exist and populate their statuses."""
    from sagaz.core.config import get_config

    config = get_config()
    if not config.storage or not saga_ids:
        return

    for saga_id in saga_ids:
        try:
            state = loop.run_until_complete(config.storage.load_saga_state(saga_id))
            if not state:
                continue

            status_val = state.get("status")
            _update_saga_status(correlation_id, saga_id, status_val, state)
        except Exception:
            pass


def sagaz_webhook_status_view(request, source: str, correlation_id: str):
    """Django view for checking webhook event status."""
    try:
        from django.http import JsonResponse
    except ImportError:  # pragma: no cover
        msg = "Django is required. Install with: pip install django"
        raise ImportError(msg)

    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    status = get_webhook_status(correlation_id)

    if not status:
        return _webhook_status_not_found_response(correlation_id, source)

    response_data = _build_webhook_status_response(status, correlation_id, source)
    return JsonResponse(response_data)


def _webhook_status_not_found_response(correlation_id: str, source: str):
    """Build 404 response for webhook status not found."""
    from django.http import JsonResponse

    return JsonResponse(
        {
            "correlation_id": correlation_id,
            "source": source,
            "status": "not_found",
            "message": "No webhook event found with this correlation ID",
        },
        status=404,
    )


def _compute_overall_status(status: dict) -> str:
    """Compute overall status from individual saga statuses."""
    saga_statuses = status.get("saga_statuses", {})
    saga_ids = status.get("saga_ids", [])
    overall_status = status["status"]

    if overall_status != "triggered" or not saga_ids:
        return overall_status

    finished_count = sum(1 for s in saga_statuses.values() if s in ("completed", "failed"))
    if finished_count < len(saga_ids):
        return overall_status

    failed_count = sum(1 for s in saga_statuses.values() if s == "failed")
    if failed_count == len(saga_ids):
        return "failed"
    if failed_count > 0:
        return "completed_with_failures"
    return "completed"


def _build_webhook_status_response(status: dict, correlation_id: str, source: str) -> dict:
    """Build webhook status response data."""
    overall_status = _compute_overall_status(status)
    saga_ids = status.get("saga_ids", [])
    saga_statuses = status.get("saga_statuses", {})

    response_data = {
        "correlation_id": correlation_id,
        "source": source,
        "status": overall_status,
        "saga_ids": saga_ids,
    }

    if saga_statuses:
        response_data["saga_statuses"] = saga_statuses
    if "saga_errors" in status:
        response_data["saga_errors"] = status["saga_errors"]
    if "error" in status:
        response_data["error"] = status["error"]

    response_data["message"] = _get_status_message(overall_status, saga_ids, saga_statuses)

    return response_data


def _get_status_message(overall_status: str, saga_ids: list, saga_statuses: dict) -> str:
    """Get helpful message based on status."""
    if overall_status == "queued":
        return "Event is queued for processing"
    if overall_status == "processing":
        return "Event is currently being processed"
    if overall_status == "triggered":
        return f"Event triggered {len(saga_ids)} saga(s), waiting for completion"
    if overall_status == "completed":
        return f"All {len(saga_ids)} saga(s) completed successfully"
    if overall_status == "completed_with_failures":
        failed_count = sum(1 for s in saga_statuses.values() if s == "failed")
        return f"{failed_count} of {len(saga_ids)} saga(s) failed"
    if overall_status == "failed":
        if len(saga_ids) == 1:
            return "Saga execution failed"
        return f"All {len(saga_ids)} saga(s) failed"
    return ""
