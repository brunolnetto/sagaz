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

        return JsonResponse(response_data)
