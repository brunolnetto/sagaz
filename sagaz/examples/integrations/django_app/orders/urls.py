"""
URL patterns for orders app.

Trigger flow:
- POST /webhooks/<source>/ → fires event → triggers saga with @trigger(source=...)
"""

from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from sagaz.integrations.django import sagaz_webhook_view

from . import views

urlpatterns = [
    # Health check
    path("health/", views.health_check, name="health"),

    # Saga diagram
    path("orders/<str:order_id>/diagram/", views.OrderDiagramView.as_view(), name="order-diagram"),

    # Webhook trigger endpoint
    # POST /webhooks/order_created → triggers OrderSaga
    path("webhooks/<str:source>/", csrf_exempt(sagaz_webhook_view), name="webhooks"),
]
