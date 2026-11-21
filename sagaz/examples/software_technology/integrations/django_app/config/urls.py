"""URL configuration for the Django example."""

from django.urls import include, path

urlpatterns = [
    path("", include("orders.urls")),
]
