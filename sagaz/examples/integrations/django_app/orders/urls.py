"""
URL patterns for orders app.

Trigger flow:
- POST /webhooks/<source>/ → fires event → triggers saga with @trigger(source=...)
- GET /webhooks/<source>/status/<correlation_id>/ → check event processing status
"""

from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from sagaz.integrations.django import sagaz_webhook_view

from . import views

urlpatterns = [
    # Health check (supports both with and without trailing slash)
    path("health", views.health_check, name="health"),
    path("health/", views.health_check, name="health-slash"),
    # Saga diagram
    path("orders/<str:order_id>/diagram", views.OrderDiagramView.as_view(), name="order-diagram"),
    path(
        "orders/<str:order_id>/diagram/",
        views.OrderDiagramView.as_view(),
        name="order-diagram-slash",
    ),
    # Webhook trigger endpoint (supports both with and without trailing slash)
    # POST /webhooks/order_created → triggers OrderSaga
    path("webhooks/<str:source>", csrf_exempt(sagaz_webhook_view), name="webhooks"),
    path("webhooks/<str:source>/", csrf_exempt(sagaz_webhook_view), name="webhooks-slash"),
    # Webhook status check (supports both with and without trailing slash)
    path(
        "webhooks/<str:source>/status/<str:correlation_id>",
        views.WebhookStatusView.as_view(),
        name="webhook-status",
    ),
    path(
        "webhooks/<str:source>/status/<str:correlation_id>/",
        views.WebhookStatusView.as_view(),
        name="webhook-status-slash",
    ),
]
