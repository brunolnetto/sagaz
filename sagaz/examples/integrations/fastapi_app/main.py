"""
FastAPI Integration Example

Demonstrates how to integrate Sagaz with FastAPI:

- `@trigger` decorator for event-driven sagas
- `create_webhook_router()` for webhook endpoints (fire-and-forget)
- Composable lifespan hooks

The trigger pattern:
1. Define @trigger on your saga with source="event_type"
2. Include create_webhook_router() in your app
3. POST /webhooks/event_type → fires event → triggers matching sagas

Run with: uvicorn main:app --reload
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sagaz import Saga, SagaConfig, action, compensate, configure

# Import integration helpers
from sagaz.integrations.fastapi import (
    create_webhook_router,
    sagaz_shutdown,
    sagaz_startup,
)
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
    - POST /webhooks/order_created → fires "order_created" event

    The @trigger decorator defines:
    - source: which event type triggers this saga
    - idempotency_key: field in payload for deduplication
    - max_concurrent: limit parallel executions
    """

    saga_name = "fastapi-order"

    @trigger(
        source="order_created",  # POST /webhooks/order_created triggers this
        idempotency_key="order_id",
        max_concurrent=10,
    )
    def handle_order_created(self, event: dict) -> dict | None:
        """
        Transform incoming webhook payload into saga context.

        Return dict → saga runs with this context
        Return None → saga skipped (invalid event)
        """
        if not event.get("order_id"):
            return None

        return {
            "order_id": event["order_id"],
            "user_id": event.get("user_id", "unknown"),
            "items": event.get("items", []),
            "amount": float(event.get("amount", 0)),
        }

    # =========================================================================
    # Saga Steps
    # =========================================================================

    @action("reserve_inventory")
    async def reserve_inventory(self, ctx: dict) -> dict[str, Any]:
        """Reserve inventory for items."""
        order_id = ctx.get("order_id")
        await asyncio.sleep(0.1)
        return {"reservation_id": f"RES-{order_id}"}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: dict) -> None:
        """Release reserved inventory on failure."""
        ctx.get("reservation_id")

    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx: dict) -> dict[str, Any]:
        """Charge customer payment."""
        order_id = ctx.get("order_id")
        amount = ctx.get("amount", 0)
        await asyncio.sleep(0.2)

        if amount > 1000:
            msg = f"Payment declined: ${amount} exceeds limit"
            raise ValueError(msg)

        return {"transaction_id": f"TXN-{order_id}"}

    @compensate("charge_payment")
    async def refund_payment(self, ctx: dict) -> None:
        """Refund on failure."""

    @action("ship_order", depends_on=["charge_payment"])
    async def ship_order(self, ctx: dict) -> dict[str, Any]:
        """Create shipment."""
        order_id = ctx.get("order_id")
        return {"shipment_id": f"SHIP-{order_id}", "tracking": f"TRACK-{order_id}"}


# =============================================================================
# FastAPI Application
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Composable lifespan with Sagaz hooks."""
    await sagaz_startup()
    yield
    await sagaz_shutdown()


app = FastAPI(
    title="Sagaz FastAPI Example",
    description="Order processing via webhook triggers",
    version="1.0.0",
    lifespan=lifespan,
)

# This creates POST /webhooks/{source} endpoint
# POST /webhooks/order_created → triggers OrderSaga
app.include_router(create_webhook_router("/webhooks"), tags=["webhooks"])


# =============================================================================
# Additional Endpoints (optional)
# =============================================================================


@app.get("/health")
async def health_check():
    """Health check."""
    return {"status": "healthy"}


@app.get("/orders/{order_id}/diagram")
async def get_order_diagram(order_id: str):
    """Get Mermaid diagram for the order saga."""
    saga = OrderSaga()
    return {
        "order_id": order_id,
        "diagram": saga.to_mermaid(),
        "format": "mermaid",
    }


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
