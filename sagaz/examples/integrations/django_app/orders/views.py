"""
Django views for order operations.

The main entry point is the webhook at /webhooks/<source>/
which triggers sagas registered with @trigger(source=...).
"""

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .sagas import OrderSaga


def health_check(request):
    """Health check endpoint."""
    return JsonResponse({"status": "healthy"})


@method_decorator(csrf_exempt, name='dispatch')
class OrderDiagramView(View):
    """Get saga diagram."""
    
    def get(self, request, order_id):
        saga = OrderSaga()
        return JsonResponse({
            "order_id": order_id,
            "diagram": saga.to_mermaid(),
            "format": "mermaid",
        })
