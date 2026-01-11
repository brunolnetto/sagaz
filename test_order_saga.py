"""
Simple Order Processing Saga for testing dry-run mode.

Uses declarative API with @action and @compensate decorators.
"""
from sagaz import Saga, action, compensate


class OrderProcessingSaga(Saga):
    """Order processing saga with payment, inventory, and shipping."""
    
    saga_name = "order-processing"
    
    @action("create_order")
    async def create_order(self, ctx):
        """Create order in database."""
        order_id = ctx.get("order_id", "ORDER-001")
        return {"order_id": order_id, "status": "created"}
    
    @compensate("create_order")
    async def cancel_order(self, ctx):
        """Cancel order."""
        pass
    
    @action("reserve_inventory", depends_on={"create_order"})
    async def reserve_inventory(self, ctx):
        """Reserve inventory for order items."""
        return {"inventory_reserved": True}
    
    @compensate("reserve_inventory")
    async def release_inventory(self, ctx):
        """Release reserved inventory."""
        pass
    
    @action("charge_payment", depends_on={"reserve_inventory"})
    async def charge_payment(self, ctx):
        """Charge customer payment."""
        amount = ctx.get("amount", 100.0)
        return {"payment_id": "PAY-123", "amount": amount}
    
    @compensate("charge_payment")
    async def refund_payment(self, ctx):
        """Refund payment."""
        pass
    
    @action("ship_order", depends_on={"charge_payment"})
    async def ship_order(self, ctx):
        """Ship the order."""
        return {"tracking_number": "TRACK-456"}
    
    @action("send_confirmation", depends_on={"ship_order"})
    async def send_confirmation(self, ctx):
        """Send order confirmation email."""
        return {"email_sent": True}


# Add metadata for cost estimation
OrderProcessingSaga.create_order.__sagaz_metadata__ = {
    "estimated_duration_ms": 50,
    "api_calls": {"database": 2},
}

OrderProcessingSaga.reserve_inventory.__sagaz_metadata__ = {
    "estimated_duration_ms": 100,
    "api_calls": {"inventory_api": 3},
}

OrderProcessingSaga.charge_payment.__sagaz_metadata__ = {
    "estimated_duration_ms": 200,
    "api_calls": {"payment_gateway": 1, "fraud_check": 1},
}

OrderProcessingSaga.ship_order.__sagaz_metadata__ = {
    "estimated_duration_ms": 150,
    "api_calls": {"shipping_api": 2},
}

OrderProcessingSaga.send_confirmation.__sagaz_metadata__ = {
    "estimated_duration_ms": 50,
    "api_calls": {"email_service": 1},
}


if __name__ == "__main__":
    import asyncio
    
    async def main():
        saga = OrderProcessingSaga()
        context = {
            "order_id": "ORDER-12345",
            "amount": 99.99,
            "items": [{"sku": "ITEM-1", "qty": 2}],
        }
        
        result = await saga.run(context)
        print(f"Saga result: {result.status}")
        print(f"Context: {result.context}")
    
    asyncio.run(main())
