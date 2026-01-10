"""
Django views for order operations.

The main entry point is the webhook at /webhooks/<source>/
which triggers sagas registered with @trigger(source=...).
"""

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

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

    This is a simplified status endpoint. In production, you would:
    - Store saga_ids with correlation_ids in Redis/DB
    - Query saga storage for actual status
    - Return detailed execution results
    """

    def get(self, request, source, correlation_id):
        return JsonResponse(
            {
                "correlation_id": correlation_id,
                "source": source,
                "status": "processing",
                "message": "Event is being processed. Check saga storage for execution details.",
                "documentation": "Use the storage backend to query saga status by saga_id",
            }
        )
