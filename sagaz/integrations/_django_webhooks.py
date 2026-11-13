"""
Webhook status tracking for the Django integration.

Holds the in-memory webhook/saga status maps, the listener that updates them,
and the helpers that build webhook status responses.
"""

from typing import Any

from sagaz.core.listeners import SagaListener
from sagaz.core.logger import get_logger

# Log under the public integration module name, as before the split.
logger = get_logger("sagaz.integrations.django")


# Global tracking for webhook status (in-memory for demo)
_webhook_tracking: dict[str, dict[str, Any]] = {}
_saga_to_webhook: dict[str, str] = {}  # saga_id -> correlation_id mapping


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
    from sagaz.core.config import get_config

    # Add webhook status listener to config
    config = get_config()
    if _WebhookStatusListener not in [type(listener) for listener in config.listeners]:
        config._listeners.append(_WebhookStatusListener())
        logger.info("Sagaz Django initialized with webhook status tracking")


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
            logger.debug(f"Failed to load existing saga status for {saga_id}", exc_info=True)


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
    overall_status: str = str(status["status"])

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
