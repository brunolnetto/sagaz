"""URL patterns for orders app."""

from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.health_check, name='health'),
    path('orders/', views.OrderView.as_view(), name='orders'),
    path('orders/<str:order_id>/diagram/', views.OrderView.as_view(), name='order-diagram'),
]
