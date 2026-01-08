"""
Django integration for Sagaz.

Provides:
- Django app configuration
- Middleware for correlation ID propagation
- Webhook view for event triggers (async, fire-and-forget)
"""

import json
import threading
from typing import Any

from sagaz.logger import get_logger
from sagaz.integrations._base import (
    SagaContextManager,
    generate_correlation_id,
    get_correlation_id,
)

logger = get_logger(__name__)

__all__ = [
    "get_logger",
    "SagaContextManager",
    "sagaz_webhook_view",
]


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
    import asyncio
    
    try:
        from django.http import JsonResponse
    except ImportError:  # pragma: no cover
        raise ImportError("Django is required. Install with: pip install django")
    
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    
    # Fire event in background thread (fire-and-forget)
    def process_in_thread():
        from sagaz.triggers import fire_event
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            saga_ids = loop.run_until_complete(fire_event(source, payload))
            logger.debug(f"Webhook {source} triggered sagas: {saga_ids}")
        except Exception as e:
            logger.error(f"Webhook {source} processing error: {e}")
        finally:
            loop.close()
    
    thread = threading.Thread(target=process_in_thread, daemon=True)
    thread.start()
    
    return JsonResponse({
        "status": "accepted",
        "source": source,
        "message": "Event queued for processing"
    }, status=202)  # Accepted
