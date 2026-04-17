#!/usr/bin/env python3
"""
Prometheus Metrics Demo — run real Sagaz sagas with Prometheus instrumentation

This demo starts a Prometheus metrics server on port 8000 and runs
actual Sagaz sagas with PrometheusMetrics, generating real metrics
that can be scraped and visualised in Grafana.

Check after starting:
    http://localhost:8000/metrics   — raw Prometheus metrics
    http://localhost:3000           — Grafana dashboards

Usage:
    sagaz demo run prometheus
    python -m sagaz.demonstrations.prometheus.main
"""

import asyncio
import logging
import random

from sagaz import Saga, SagaStepError, action, compensate
from sagaz.listeners import LoggingSagaListener, MetricsSagaListener
from sagaz.observability.monitoring.prometheus import PrometheusMetrics, start_metrics_server

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.prometheus")

prometheus_metrics = PrometheusMetrics()


# ============================================================================
# Saga definitions
# ============================================================================


class OrderProcessingSaga(Saga):
    """Order processing saga with inventory, payment, and shipping."""

    saga_name = "order-processing"
    listeners = [LoggingSagaListener(), MetricsSagaListener(metrics=prometheus_metrics)]

    @action("validate_order")
    async def validate_order(self, ctx):
        await asyncio.sleep(random.uniform(0.01, 0.05))
        order_id = f"ORD-{random.randint(1000, 9999)}"
        return {"order_id": order_id, "validated": True}

    @action("reserve_inventory", depends_on=["validate_order"])
    async def reserve_inventory(self, ctx):
        await asyncio.sleep(random.uniform(0.02, 0.08))
        return {"inventory_reserved": True, "items": 3}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx):
        await asyncio.sleep(random.uniform(0.01, 0.03))
        logger.info(f"Released inventory for order {ctx.get('order_id')}")

    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx):
        await asyncio.sleep(random.uniform(0.05, 0.15))
        if random.random() < 0.15:
            msg = "Payment declined by processor"
            raise SagaStepError(msg)
        return {"payment_id": f"PAY-{random.randint(1000, 9999)}", "amount": 99.99}

    @compensate("charge_payment")
    async def refund_payment(self, ctx):
        await asyncio.sleep(random.uniform(0.02, 0.05))
        logger.info(f"Refunded payment {ctx.get('payment_id')}")

    @action("ship_order", depends_on=["charge_payment"])
    async def ship_order(self, ctx):
        await asyncio.sleep(random.uniform(0.03, 0.1))
        return {"tracking_id": f"TRACK-{random.randint(10000, 99999)}"}


class PaymentRefundSaga(Saga):
    """Saga for processing payment refunds."""

    saga_name = "payment-refund"
    listeners = [LoggingSagaListener(), MetricsSagaListener(metrics=prometheus_metrics)]

    @action("validate_refund_request")
    async def validate_refund(self, ctx):
        await asyncio.sleep(random.uniform(0.01, 0.03))
        return {"refund_validated": True}

    @action("process_refund", depends_on=["validate_refund_request"])
    async def process_refund(self, ctx):
        await asyncio.sleep(random.uniform(0.05, 0.12))
        if random.random() < 0.05:
            msg = "Refund processing failed"
            raise SagaStepError(msg)
        return {"refund_id": f"REF-{random.randint(1000, 9999)}"}

    @action("notify_customer", depends_on=["process_refund"])
    async def notify_customer(self, ctx):
        await asyncio.sleep(random.uniform(0.01, 0.02))
        return {"notification_sent": True}


class UserOnboardingSaga(Saga):
    """Saga for onboarding new users."""

    saga_name = "user-onboarding"
    listeners = [LoggingSagaListener(), MetricsSagaListener(metrics=prometheus_metrics)]

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
        if random.random() < 0.08:
            msg = "Email service unavailable"
            raise SagaStepError(msg)
        return {"email_sent": True}


# ============================================================================
# Demo loop
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
    print("Using real Sagaz sagas with PrometheusMetrics backend")
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
            await saga.run(initial_context.copy())
            logger.info(f"[{iteration}] ✅ {saga.saga_name} completed successfully")
        except Exception as e:
            logger.warning(f"[{iteration}] ❌ {saga.saga_name} failed: {e}")
        await asyncio.sleep(random.uniform(1.5, 4.0))


# ============================================================================
# Entry point
# ============================================================================


def main():
    """Main entry point for sagaz demo run prometheus."""
    logger.info("Starting Prometheus metrics server on port 8000...")
    start_metrics_server(8000)
    try:
        asyncio.run(run_demo_loop())
    except KeyboardInterrupt:
        print("\n👋 Demo stopped")


if __name__ == "__main__":
    main()
