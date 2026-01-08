"""
Flask Integration Example

Demonstrates how to integrate Sagaz with Flask:

- `@trigger` decorator for event-driven sagas
- `SagaFlask.register_webhook_blueprint()` for webhook endpoints
- Correlation ID propagation

Trigger flow:
1. Define @trigger on your saga with source="event_type"
2. Register webhook blueprint
3. POST /webhooks/event_type → fires event → triggers matching sagas

Run with: python main.py
"""

import asyncio
from typing import Any

from flask import Flask, jsonify

from sagaz import Saga, SagaConfig, action, compensate, configure
from sagaz.storage import InMemorySagaStorage

# Import trigger decorator
from sagaz.triggers import trigger

# Import Flask integration
from sagaz.integrations.flask import SagaFlask

# =============================================================================
# Configuration
# =============================================================================

config = SagaConfig(
    storage=InMemorySagaStorage(),
    metrics=True,
    logging=True,
)

configure(config)


# =============================================================================
# Saga Definition with Trigger
# =============================================================================

class OrderSaga(Saga):
    """
    E-commerce order processing saga.
    
    Triggered via:
    - POST /webhooks/order_created
    """
    
    saga_name = "flask-order"
    
    @trigger(
        source="order_created",
        idempotency_key="order_id",
        max_concurrent=5
    )
    def handle_order_created(self, event: dict) -> dict | None:
        """Transform webhook payload into saga context."""
        if not event.get("order_id"):
            return None
        
        return {
            "order_id": event["order_id"],
            "user_id": event.get("user_id", "unknown"),
            "items": event.get("items", []),
            "amount": float(event.get("amount", 0)),
        }

    @action("reserve_inventory")
    async def reserve_inventory(self, ctx: dict) -> dict[str, Any]:
        print(f"[{ctx['order_id']}] Reserving inventory...")
        await asyncio.sleep(0.1)
        return {"reservation_id": f"RES-{ctx['order_id']}"}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: dict) -> None:
        print(f"Releasing reservation: {ctx.get('reservation_id')}")

    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx: dict) -> dict[str, Any]:
        print(f"[{ctx['order_id']}] Charging ${ctx.get('amount', 0)}...")
        await asyncio.sleep(0.2)
        if ctx.get("amount", 0) > 1000:
            raise ValueError("Payment declined")
        return {"transaction_id": f"TXN-{ctx['order_id']}"}

    @compensate("charge_payment")
    async def refund_payment(self, ctx: dict) -> None:
        print(f"Refunding: {ctx.get('transaction_id')}")

    @action("ship_order", depends_on=["charge_payment"])
    async def ship_order(self, ctx: dict) -> dict[str, Any]:
        print(f"[{ctx['order_id']}] Shipping...")
        return {"tracking": f"TRACK-{ctx['order_id']}"}


# =============================================================================
# Flask Application
# =============================================================================

app = Flask(__name__)

# Initialize Sagaz extension
sagaz = SagaFlask(app)

# Register webhook endpoint: POST /webhooks/{source}
sagaz.register_webhook_blueprint("/webhooks")


@app.route("/health")
def health_check():
    return jsonify({"status": "healthy"})


@app.route("/orders/<order_id>/diagram")
def get_order_diagram(order_id: str):
    saga = OrderSaga()
    return jsonify({
        "order_id": order_id,
        "diagram": saga.to_mermaid(),
        "format": "mermaid",
    })


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    print("🚀 Sagaz Flask Example")
    print("=" * 60)
    print()
    print("📡 Trigger endpoint:")
    print("   POST /webhooks/order_created")
    print()
    print("🔗 Example:")
    print('   curl -X POST http://localhost:5000/webhooks/order_created \\')
    print('     -H "Content-Type: application/json" \\')
    print('     -d \'{"order_id": "ORD-123", "user_id": "USR-1", "amount": 99.99}\'')
    print()
    
    app.run(host="0.0.0.0", port=5000, debug=True)
