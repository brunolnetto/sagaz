"""
FastAPI Integration Example

Demonstrates how to integrate Sagaz with FastAPI:
- Lifespan management for storage initialization/cleanup
- Dependency injection for saga instances
- Background saga execution
- Correlation ID middleware

Run with: uvicorn main:app --reload
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from sagaz import Saga, SagaConfig, action, compensate, configure, get_config

# =============================================================================
# Configuration
# =============================================================================

# In production, use SagaConfig.from_env() or load from settings
config = SagaConfig(
    metrics=True,
    logging=True,
)


# =============================================================================
# Saga Definition
# =============================================================================

class OrderSaga(Saga):
    """E-commerce order processing saga."""
    
    saga_name = "fastapi-order"

    @action("reserve_inventory")
    async def reserve_inventory(self, ctx: dict) -> dict[str, Any]:
        """Reserve inventory for items."""
        order_id = ctx.get("order_id")
        print(f"[{order_id}] Reserving inventory...")
        await asyncio.sleep(0.1)  # Simulate DB call
        return {"reservation_id": f"RES-{order_id}"}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: dict) -> None:
        """Release reserved inventory."""
        reservation_id = ctx.get("reservation_id")
        print(f"Releasing reservation: {reservation_id}")
        await asyncio.sleep(0.05)

    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx: dict) -> dict[str, Any]:
        """Charge customer payment."""
        order_id = ctx.get("order_id")
        amount = ctx.get("amount", 0)
        print(f"[{order_id}] Charging ${amount}...")
        await asyncio.sleep(0.2)
        
        # Simulate payment failure for large amounts
        if amount > 1000:
            raise ValueError(f"Payment declined: ${amount} exceeds limit")
        
        return {"transaction_id": f"TXN-{order_id}"}

    @compensate("charge_payment")
    async def refund_payment(self, ctx: dict) -> None:
        """Refund customer payment."""
        transaction_id = ctx.get("transaction_id")
        print(f"Refunding transaction: {transaction_id}")
        await asyncio.sleep(0.1)

    @action("ship_order", depends_on=["charge_payment"])
    async def ship_order(self, ctx: dict) -> dict[str, Any]:
        """Create shipment."""
        order_id = ctx.get("order_id")
        print(f"[{order_id}] Creating shipment...")
        await asyncio.sleep(0.1)
        return {"shipment_id": f"SHIP-{order_id}", "tracking": f"TRACK-{order_id}"}


# =============================================================================
# FastAPI Integration Helpers
# =============================================================================

@asynccontextmanager
async def sagaz_lifespan(app: FastAPI):
    """
    Lifespan context manager for Sagaz.
    
    Initializes storage on startup and closes connections on shutdown.
    """
    # Startup
    configure(config)
    print("✅ Sagaz initialized")
    
    # If using StorageManager with pools:
    # if config.storage_manager:
    #     await config.storage_manager.initialize()
    
    yield
    
    # Shutdown
    # if config.storage_manager:
    #     await config.storage_manager.close()
    print("✅ Sagaz shutdown complete")


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware to propagate correlation IDs across requests."""
    
    async def dispatch(self, request: Request, call_next):
        # Get or generate correlation ID
        correlation_id = request.headers.get(
            "X-Correlation-ID",
            str(uuid.uuid4())
        )
        
        # Store in request state for later access
        request.state.correlation_id = correlation_id
        
        response = await call_next(request)
        
        # Include in response headers
        response.headers["X-Correlation-ID"] = correlation_id
        return response


def get_saga_config() -> SagaConfig:
    """Dependency that returns the current SagaConfig."""
    return get_config()


def create_saga(saga_class: type):
    """
    Factory for saga dependency injection.
    
    Usage:
        @app.post("/orders")
        async def create_order(saga: OrderSaga = Depends(create_saga(OrderSaga))):
            ...
    """
    def factory(config: SagaConfig = Depends(get_saga_config)) -> Saga:
        return saga_class(config=config)
    return factory


async def run_saga_in_background(
    background_tasks: BackgroundTasks,
    saga: Saga,
    context: dict,
) -> str:
    """
    Schedule saga to run as a background task.
    
    Returns saga_id immediately. Saga executes after response is sent.
    
    Note: For production reliability, use the Outbox Worker pattern instead.
    """
    saga_id = str(uuid.uuid4())
    
    async def run_wrapper():
        try:
            await saga.run({**context, "_saga_id": saga_id})
            print(f"✅ Background saga {saga_id} completed")
        except Exception as e:
            print(f"❌ Background saga {saga_id} failed: {e}")
    
    background_tasks.add_task(asyncio.create_task, run_wrapper())
    return saga_id


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Sagaz FastAPI Example",
    description="Demonstrates Sagaz integration with FastAPI",
    version="1.0.0",
    lifespan=sagaz_lifespan,
)

# Add correlation ID middleware
app.add_middleware(CorrelationMiddleware)


# =============================================================================
# API Models
# =============================================================================

class OrderRequest(BaseModel):
    """Request model for creating an order."""
    order_id: str
    user_id: str
    items: list[dict]
    amount: float


class OrderResponse(BaseModel):
    """Response model for order operations."""
    saga_id: str
    order_id: str
    status: str


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "sagaz-fastapi-example"}


@app.post("/orders", response_model=OrderResponse)
async def create_order(
    order: OrderRequest,
    saga: OrderSaga = Depends(create_saga(OrderSaga)),
    x_correlation_id: str = Header(None),
):
    """
    Create an order synchronously.
    
    The saga runs within the request lifecycle. Use /orders/async for
    fire-and-forget execution.
    """
    context = {
        "order_id": order.order_id,
        "user_id": order.user_id,
        "items": order.items,
        "amount": order.amount,
        "correlation_id": x_correlation_id,
    }
    
    try:
        result = await saga.run(context)
        return OrderResponse(
            saga_id=result.get("saga_id", ""),
            order_id=order.order_id,
            status="completed" if result.get("saga_id") else "failed",
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "order_id": order.order_id},
        )


@app.post("/orders/async")
async def create_order_async(
    order: OrderRequest,
    background_tasks: BackgroundTasks,
    saga: OrderSaga = Depends(create_saga(OrderSaga)),
):
    """
    Create an order asynchronously (fire-and-forget).
    
    Returns immediately with saga_id. Check status via /orders/{saga_id}/status.
    """
    context = {
        "order_id": order.order_id,
        "user_id": order.user_id,
        "items": order.items,
        "amount": order.amount,
    }
    
    saga_id = await run_saga_in_background(background_tasks, saga, context)
    
    return {
        "saga_id": saga_id,
        "order_id": order.order_id,
        "status": "accepted",
        "message": "Order processing started in background",
    }


@app.get("/orders/{order_id}/diagram")
async def get_order_diagram(
    order_id: str,
    saga: OrderSaga = Depends(create_saga(OrderSaga)),
):
    """
    Get Mermaid diagram for the order saga.
    
    Returns the saga's execution flow as a Mermaid diagram.
    """
    diagram = saga.to_mermaid()
    return {
        "order_id": order_id,
        "diagram": diagram,
        "format": "mermaid",
    }


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("Starting Sagaz FastAPI Example...")
    print("API docs available at: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
