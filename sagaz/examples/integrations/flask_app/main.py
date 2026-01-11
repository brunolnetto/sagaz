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
import uuid
from typing import Any

from flask import Flask, jsonify, request

from sagaz import Saga, SagaConfig, action, compensate, configure

# Import Flask integration
from sagaz.integrations.flask import SagaFlask
from sagaz.storage import InMemorySagaStorage

# Import trigger decorator
from sagaz.triggers import trigger

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

    @trigger(source="order_created", idempotency_key="order_id", max_concurrent=5)
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
        await asyncio.sleep(0.1)
        return {"reservation_id": f"RES-{ctx['order_id']}"}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: dict) -> None:
        pass

    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx: dict) -> dict[str, Any]:
        await asyncio.sleep(0.2)
        if ctx.get("amount", 0) > 1000:
            msg = "Payment declined"
            raise ValueError(msg)
        return {"transaction_id": f"TXN-{ctx['order_id']}"}

    @compensate("charge_payment")
    async def refund_payment(self, ctx: dict) -> None:
        pass

    @action("ship_order", depends_on=["charge_payment"])
    async def ship_order(self, ctx: dict) -> dict[str, Any]:
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


@app.route("/orders/validate", methods=["POST"])
def validate_order():
    """
    Validate if an order can be processed.

    This demonstrates idempotency checking before webhook submission.
    Checks if order_id is already being processed or completed.
    """
    data = request.get_json()
    if not data or "order_id" not in data:
        return jsonify({"error": "order_id is required"}), 400

    order_id = data["order_id"]

    # Derive deterministic saga_id from order_id (same as trigger does)
    saga_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, order_id))

    # Check if saga exists in storage
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        state = loop.run_until_complete(config.storage.load_saga_state(saga_id))
    finally:
        loop.close()

    if state:
        from sagaz.core.types import SagaStatus

        status = state.get("status")
        if status == SagaStatus.COMPLETED:
            return jsonify(
                {
                    "valid": False,
                    "order_id": order_id,
                    "saga_id": saga_id,
                    "reason": "Order already processed successfully",
                    "saga_status": "completed",
                    "advice": "This order has been completed. Use a different order_id.",
                }
            ), 409  # Conflict
        if status == SagaStatus.EXECUTING:
            return jsonify(
                {
                    "valid": False,
                    "order_id": order_id,
                    "saga_id": saga_id,
                    "reason": "Order is currently being processed",
                    "saga_status": "executing",
                    "advice": "Wait for this order to complete before resubmitting.",
                }
            ), 409  # Conflict
        if status in (SagaStatus.FAILED, SagaStatus.ROLLED_BACK):
            return jsonify(
                {
                    "valid": True,
                    "order_id": order_id,
                    "saga_id": saga_id,
                    "message": "Order previously failed, can be retried",
                    "saga_status": status.value,
                    "advice": "This order can be resubmitted via webhook.",
                }
            )

    return jsonify(
        {
            "valid": True,
            "order_id": order_id,
            "message": "Order can be processed",
            "saga_id": saga_id,
            "advice": "Submit order via POST /webhooks/order_created",
        }
    )


@app.route("/orders/<order_id>/diagram")
def get_order_diagram(order_id: str):
    saga = OrderSaga()
    return jsonify(
        {
            "order_id": order_id,
            "diagram": saga.to_mermaid(),
            "format": "mermaid",
        }
    )


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
