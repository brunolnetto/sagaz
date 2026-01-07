"""
Django views for order operations.

Demonstrates sync views with async saga execution.
"""

import asyncio
import json
import uuid

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from sagaz import get_config

from .sagas import OrderSaga


def get_or_create_event_loop():
    """Get or create an event loop for sync context."""
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def run_saga_sync(saga, context):
    """Run an async saga synchronously."""
    loop = get_or_create_event_loop()
    return loop.run_until_complete(saga.run(context))


def health_check(request):
    """Health check endpoint."""
    return JsonResponse({
        "status": "healthy",
        "service": "sagaz-django-example",
    })


@method_decorator(csrf_exempt, name='dispatch')
class OrderView(View):
    """View for order operations."""
    
    def get(self, request, order_id=None):
        """Get order diagram."""
        if order_id:
            saga = OrderSaga(config=get_config())
            diagram = saga.to_mermaid()
            return JsonResponse({
                "order_id": order_id,
                "diagram": diagram,
                "format": "mermaid",
            })
        
        return JsonResponse({"error": "order_id required"}, status=400)
    
    def post(self, request):
        """Create a new order."""
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        
        # Get correlation ID from header
        correlation_id = request.headers.get(
            "X-Correlation-ID",
            str(uuid.uuid4())
        )
        
        context = {
            "order_id": data.get("order_id"),
            "user_id": data.get("user_id"),
            "items": data.get("items", []),
            "amount": data.get("amount", 0),
            "correlation_id": correlation_id,
        }
        
        saga = OrderSaga(config=get_config())
        
        try:
            result = run_saga_sync(saga, context)
            
            response = JsonResponse({
                "saga_id": result.get("saga_id", ""),
                "order_id": data.get("order_id"),
                "status": "completed" if result.get("saga_id") else "failed",
            })
            response["X-Correlation-ID"] = correlation_id
            return response
            
        except Exception as e:
            return JsonResponse({
                "error": str(e),
                "order_id": data.get("order_id"),
            }, status=500)
