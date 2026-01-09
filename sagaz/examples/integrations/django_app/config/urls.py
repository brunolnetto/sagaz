"""URL configuration for the Django example."""

from django.urls import path, include

urlpatterns = [
    path('', include('orders.urls')),
]
