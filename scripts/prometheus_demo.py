#!/usr/bin/env python3
"""
Demo application using REAL Sagaz sagas with Prometheus metrics.

This demo:
1. Starts a Prometheus metrics server on port 8000
2. Runs actual Sagaz sagas with PrometheusMetrics
3. Generates real metrics for Grafana dashboards

Usage:
    python scripts/prometheus_demo.py

Then check:
    - http://localhost:8000/metrics - Raw Prometheus metrics
    - http://localhost:3000 - Grafana dashboards
"""

import asyncio
import logging
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo")

# Import from the actual Sagaz library
from sagaz import Saga, action, compensate, SagaStepError
from sagaz.listeners import MetricsSagaListener, LoggingSagaListener
from sagaz.monitoring.prometheus import PrometheusMetrics, start_metrics_server


# Create a global Prometheus metrics instance
prometheus_metrics = PrometheusMetrics()


# ============================================================================
# Define real Sagaz sagas using the declarative API
# ============================================================================

class OrderProcessingSaga(Saga):
    """Order processing saga with inventory, payment, and shipping."""
    
    saga_name = "order-processing"
    listeners = [
        LoggingSagaListener(),
        MetricsSagaListener(metrics=prometheus_metrics)
    ]
    
    @action("validate_order")
    async def validate_order(self, ctx):
        """Validate the order data."""
        await asyncio.sleep(random.uniform(0.01, 0.05))
        order_id = f"ORD-{random.randint(1000, 9999)}"
        return {"order_id": order_id, "validated": True}
    
    @action("reserve_inventory", depends_on=["validate_order"])
    async def reserve_inventory(self, ctx):
        """Reserve items in inventory."""
        await asyncio.sleep(random.uniform(0.02, 0.08))
        return {"inventory_reserved": True, "items": 3}
    
    @compensate("reserve_inventory")
    async def release_inventory(self, ctx):
        """Release reserved inventory on failure."""
        await asyncio.sleep(random.uniform(0.01, 0.03))
        logger.info(f"Released inventory for order {ctx.get('order_id')}")
    
    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx):
        """Charge customer payment."""
        await asyncio.sleep(random.uniform(0.05, 0.15))
        # Simulate occasional payment failures
        if random.random() < 0.15:  # 15% failure rate
            raise SagaStepError("Payment declined by processor")
        return {"payment_id": f"PAY-{random.randint(1000, 9999)}", "amount": 99.99}
    
    @compensate("charge_payment")
    async def refund_payment(self, ctx):
        """Refund the payment on failure."""
        await asyncio.sleep(random.uniform(0.02, 0.05))
        logger.info(f"Refunded payment {ctx.get('payment_id')}")
    
    @action("ship_order", depends_on=["charge_payment"])
    async def ship_order(self, ctx):
        """Initiate order shipment."""
        await asyncio.sleep(random.uniform(0.03, 0.1))
        return {"tracking_id": f"TRACK-{random.randint(10000, 99999)}"}


class PaymentRefundSaga(Saga):
    """Saga for processing refunds."""
    
    saga_name = "payment-refund"
    listeners = [
        LoggingSagaListener(),
        MetricsSagaListener(metrics=prometheus_metrics)
    ]
    
    @action("validate_refund_request")
    async def validate_refund(self, ctx):
        await asyncio.sleep(random.uniform(0.01, 0.03))
        return {"refund_validated": True}
    
    @action("process_refund", depends_on=["validate_refund_request"])
    async def process_refund(self, ctx):
        await asyncio.sleep(random.uniform(0.05, 0.12))
        # Simulate rare failures
        if random.random() < 0.05:  # 5% failure rate
            raise SagaStepError("Refund processing failed")
        return {"refund_id": f"REF-{random.randint(1000, 9999)}"}
    
    @action("notify_customer", depends_on=["process_refund"])
    async def notify_customer(self, ctx):
        await asyncio.sleep(random.uniform(0.01, 0.02))
        return {"notification_sent": True}


class UserOnboardingSaga(Saga):
    """Saga for onboarding new users."""
    
    saga_name = "user-onboarding"
    listeners = [
        LoggingSagaListener(),
        MetricsSagaListener(metrics=prometheus_metrics)
    ]
    
    @action("create_user_account")
    async def create_account(self, ctx):
        await asyncio.sleep(random.uniform(0.02, 0.06))
        return {"user_id": f"USR-{random.randint(10000, 99999)}"}
    
    @compensate("create_user_account")
    async def delete_account(self, ctx):
        await asyncio.sleep(random.uniform(0.01, 0.02))
        logger.info(f"Deleted user account {ctx.get('user_id')}")
    
    @action("setup_default_settings", depends_on=["create_user_account"])
    async def setup_defaults(self, ctx):
        await asyncio.sleep(random.uniform(0.01, 0.03))
        return {"settings_applied": True}
    
    @action("send_welcome_email", depends_on=["setup_default_settings"])
    async def send_welcome(self, ctx):
        await asyncio.sleep(random.uniform(0.02, 0.05))
        # Simulate rare failures
        if random.random() < 0.08:  # 8% failure rate
            raise SagaStepError("Email service unavailable")
        return {"email_sent": True}


# ============================================================================
# Main demo loop
# ============================================================================

async def run_demo_loop():
    """Continuously run saga demos to generate metrics."""
    
    sagas = [
        (OrderProcessingSaga, {"customer_id": "CUST-001", "items": ["item1", "item2"]}),
        (PaymentRefundSaga, {"order_id": "ORD-9999", "amount": 49.99}),
        (UserOnboardingSaga, {"email": "user@example.com"}),
    ]
    
    print("\n" + "=" * 70)
    print("🚀 SAGAZ PROMETHEUS METRICS DEMO")
    print("=" * 70)
    print("Using REAL Sagaz library with PrometheusMetrics backend")
    print()
    print("📊 Metrics endpoint: http://localhost:8000/metrics")
    print("📈 Grafana dashboard: http://localhost:3000")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 70 + "\n")
    
    iteration = 0
    while True:
        iteration += 1
        saga_class, initial_context = random.choice(sagas)
        
        saga = saga_class()
        logger.info(f"[{iteration}] Running {saga.saga_name}...")
        
        try:
            result = await saga.run(initial_context.copy())
            logger.info(f"[{iteration}] ✅ {saga.saga_name} completed successfully")
        except Exception as e:
            logger.warning(f"[{iteration}] ❌ {saga.saga_name} failed: {e}")
        
        # Wait between sagas
        await asyncio.sleep(random.uniform(1.5, 4.0))


def main():
    """Main entry point."""
    # Start Prometheus HTTP server on port 8000
    logger.info("Starting Prometheus metrics server on port 8000...")
    start_metrics_server(8000)
    
    # Run the demo loop
    try:
        asyncio.run(run_demo_loop())
    except KeyboardInterrupt:
        print("\n👋 Demo stopped")


if __name__ == "__main__":
    main()
