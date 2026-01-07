"""
Flask Integration Example

Demonstrates how to integrate Sagaz with Flask:
- Extension pattern for initialization
- Sync wrapper for async sagas
- Request context integration
- Simple blueprint structure

Run with: flask run --reload
"""

import asyncio
import uuid
from functools import wraps
from typing import Any

from flask import Flask, g, jsonify, request

from sagaz import Saga, SagaConfig, action, compensate, configure, get_config

# =============================================================================
# Configuration
# =============================================================================

config = SagaConfig(
    metrics=True,
    logging=True,
)


# =============================================================================
# Saga Definition
# =============================================================================

class OrderSaga(Saga):
    """E-commerce order processing saga."""
    
    saga_name = "flask-order"

    @action("reserve_inventory")
    async def reserve_inventory(self, ctx: dict) -> dict[str, Any]:
        """Reserve inventory for items."""
        order_id = ctx.get("order_id")
        print(f"[{order_id}] Reserving inventory...")
        await asyncio.sleep(0.1)
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
# Flask Extension
# =============================================================================

class SagazExtension:
    """
    Flask extension for Sagaz integration.
    
    Usage:
        app = Flask(__name__)
        sagaz = SagazExtension(app)
        
        # In routes:
        saga = sagaz.create_saga(OrderSaga)
        result = sagaz.run_sync(saga, context)
    """
    
    def __init__(self, app: Flask = None, **config_kwargs):
        self.config: SagaConfig = None
        self._config_kwargs = config_kwargs
        self._event_loop = None
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app: Flask):
        """Initialize the extension with a Flask app."""
        # Merge any config from app.config
        storage_url = app.config.get("SAGAZ_STORAGE_URL", "memory://")
        broker_url = app.config.get("SAGAZ_BROKER_URL")
        
        self.config = SagaConfig(
            **self._config_kwargs,
        )
        configure(self.config)
        
        # Create event loop for async operations
        self._event_loop = asyncio.new_event_loop()
        
        # Register extension
        if not hasattr(app, "extensions"):
            app.extensions = {}
        app.extensions["sagaz"] = self
        
        # Register teardown
        @app.teardown_appcontext
        def cleanup(exception):
            pass  # Per-request cleanup if needed
        
        print("✅ Sagaz Flask extension initialized")
    
    def create_saga(self, saga_class: type) -> Saga:
        """Create a saga instance with current config."""
        return saga_class(config=self.config)
    
    def run_sync(self, saga: Saga, context: dict) -> dict:
        """
        Run a saga synchronously.
        
        Wraps the async saga.run() for sync Flask routes.
        
        WARNING: This blocks the request thread. Keep sagas short,
        or use Celery for long-running work.
        """
        return self._event_loop.run_until_complete(saga.run(context))
    
    def get_correlation_id(self) -> str:
        """Get or generate a correlation ID for the current request."""
        if not hasattr(g, "correlation_id"):
            g.correlation_id = request.headers.get(
                "X-Correlation-ID",
                str(uuid.uuid4())
            )
        return g.correlation_id


def require_correlation_id(f):
    """Decorator to ensure correlation ID is available in g."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        sagaz_ext = app.extensions.get("sagaz")
        if sagaz_ext:
            g.correlation_id = sagaz_ext.get_correlation_id()
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# Flask Application
# =============================================================================

app = Flask(__name__)
app.config["SAGAZ_STORAGE_URL"] = "memory://"

# Initialize Sagaz extension
sagaz = SagazExtension(app, metrics=True, logging=True)


# =============================================================================
# API Endpoints
# =============================================================================

@app.route("/health")
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "sagaz-flask-example"})


@app.route("/orders", methods=["POST"])
@require_correlation_id
def create_order():
    """
    Create an order synchronously.
    
    The saga runs within the request lifecycle.
    """
    data = request.get_json()
    
    context = {
        "order_id": data.get("order_id"),
        "user_id": data.get("user_id"),
        "items": data.get("items", []),
        "amount": data.get("amount", 0),
        "correlation_id": g.correlation_id,
    }
    
    saga = sagaz.create_saga(OrderSaga)
    
    try:
        result = sagaz.run_sync(saga, context)
        return jsonify({
            "saga_id": result.get("saga_id", ""),
            "order_id": data.get("order_id"),
            "status": "completed" if result.get("saga_id") else "failed",
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "order_id": data.get("order_id"),
        }), 500


@app.route("/orders/<order_id>/diagram")
def get_order_diagram(order_id: str):
    """Get Mermaid diagram for the order saga."""
    saga = sagaz.create_saga(OrderSaga)
    diagram = saga.to_mermaid()
    return jsonify({
        "order_id": order_id,
        "diagram": diagram,
        "format": "mermaid",
    })


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    print("Starting Sagaz Flask Example...")
    print("API available at: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
