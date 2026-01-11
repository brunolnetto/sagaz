"""
Django views for order operations.

The main entry point is the webhook at /webhooks/<source>/
which triggers sagas registered with @trigger(source=...).
"""

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from sagaz.integrations.django import get_webhook_status

from .sagas import OrderSaga


def health_check(request):
    """Health check endpoint."""
    return JsonResponse({"status": "healthy"})


@method_decorator(csrf_exempt, name="dispatch")
class OrderDiagramView(View):
    """Get saga diagram."""

    def get(self, request, order_id):
        saga = OrderSaga()
        return JsonResponse(
            {
                "order_id": order_id,
                "diagram": saga.to_mermaid(),
                "format": "mermaid",
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class WebhookStatusView(View):
    """
    Check status of event processing.

    Returns the status of a webhook event using its correlation ID.
    The webhook view tracks events in memory for demo purposes.

    In production, you would:
    - Store correlation_id -> saga_id mappings in Redis/PostgreSQL
    - Query saga storage for detailed execution status
    - Implement proper cleanup of old tracking data
    """

    def get(self, request, source, correlation_id):
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
            completed_count = sum(1 for s in saga_statuses.values() if s in ("completed", "failed"))
            if completed_count == len(saga_ids):
                # All sagas finished - determine overall outcome
                failed_count = sum(1 for s in saga_statuses.values() if s == "failed")
                overall_status = "completed_with_failures" if failed_count > 0 else "completed"

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
            failed_sagas = [sid for sid, s in saga_statuses.items() if s == "failed"]
            response_data["message"] = f"{len(failed_sagas)} of {len(saga_ids)} saga(s) failed"
        elif overall_status == "failed":
            response_data["message"] = "Event processing failed"

        return JsonResponse(response_data)
