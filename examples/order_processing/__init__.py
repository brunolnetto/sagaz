"""
Order Processing Example

Complete e-commerce order processing saga with:
- Inventory reservation
- Payment processing
- Shipment creation
- Email confirmation
"""

from . import actions, compensations
from .main import OrderProcessingSaga

__all__ = ["OrderProcessingSaga", "actions", "compensations"]
