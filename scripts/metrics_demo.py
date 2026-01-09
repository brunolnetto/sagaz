#!/usr/bin/env python3
"""
Demo application that runs sagas with Prometheus metrics.

This will expose metrics on port 8000 that Prometheus can scrape.

Usage:
    python scripts/metrics_demo.py

Then check:
    - http://localhost:8000/metrics - Raw Prometheus metrics
    - http://localhost:3000 - Grafana dashboards
"""

import asyncio
import logging

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sagaz.metrics_demo")

# Define Prometheus metrics - names must match dashboard queries
SAGA_TOTAL = Counter(
    "saga_execution_total",  # Note: singular to match dashboard
    "Total saga executions",
    ["saga_name", "status"],
)

SAGA_COMPENSATIONS = Counter("saga_compensations_total", "Total saga compensations", ["saga_name"])

SAGA_DURATION = Histogram(
    "saga_execution_duration_seconds",
    "Saga execution duration in seconds",
    ["saga_name"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

STEP_DURATION = Histogram(
    "saga_step_duration_seconds",
    "Saga step execution duration in seconds",
    ["saga_name", "step_name"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

OUTBOX_EVENTS = Counter("outbox_events_total", "Total outbox events", ["event_type", "status"])

ACTIVE_SAGAS = Gauge("saga_active_count", "Number of currently running sagas", ["saga_name"])


async def simulate_saga_execution(saga_name: str, steps: list[str], should_fail: bool = False):
    """Simulate a saga execution with timing."""
    import random
    import time

    start_time = time.time()
    ACTIVE_SAGAS.labels(saga_name=saga_name).inc()

    try:
        for step in steps:
            step_start = time.time()
            # Simulate step execution
            await asyncio.sleep(random.uniform(0.01, 0.1))
            step_duration = time.time() - step_start
            STEP_DURATION.labels(saga_name=saga_name, step_name=step).observe(step_duration)
            logger.info(f"  Step '{step}' completed in {step_duration:.3f}s")

        if should_fail:
            msg = "Simulated failure"
            raise Exception(msg)

        SAGA_TOTAL.labels(saga_name=saga_name, status="completed").inc()
        OUTBOX_EVENTS.labels(event_type=f"{saga_name}.completed", status="sent").inc()
        logger.info(f"✅ Saga '{saga_name}' completed successfully")

    except Exception as e:
        SAGA_TOTAL.labels(saga_name=saga_name, status="failed").inc()
        SAGA_COMPENSATIONS.labels(saga_name=saga_name).inc()  # Track compensation
        OUTBOX_EVENTS.labels(event_type=f"{saga_name}.failed", status="sent").inc()
        logger.warning(f"❌ Saga '{saga_name}' failed: {e} (compensation triggered)")

    finally:
        duration = time.time() - start_time
        SAGA_DURATION.labels(saga_name=saga_name).observe(duration)
        ACTIVE_SAGAS.labels(saga_name=saga_name).dec()


async def run_demo_loop():
    """Continuously run demo sagas to generate metrics."""
    import random

    sagas = [
        ("OrderProcessing", ["validate", "reserve_inventory", "charge_payment", "ship"]),
        ("PaymentRefund", ["validate_refund", "process_refund", "notify"]),
        ("UserOnboarding", ["create_account", "send_welcome", "setup_defaults"]),
    ]

    logger.info("🚀 Starting metrics demo - Prometheus metrics at http://localhost:8000/metrics")
    logger.info("📊 View dashboards at http://localhost:3000")
    logger.info("Press Ctrl+C to stop\n")

    iteration = 0
    while True:
        iteration += 1
        saga_name, steps = random.choice(sagas)
        should_fail = random.random() < 0.1  # 10% failure rate

        logger.info(f"[{iteration}] Running saga: {saga_name}")
        await simulate_saga_execution(saga_name, steps, should_fail)

        # Wait between sagas
        await asyncio.sleep(random.uniform(1, 3))


def main():
    """Main entry point."""
    # Start Prometheus HTTP server on port 8000
    logger.info("Starting Prometheus metrics server on port 8000...")
    start_http_server(8000)

    # Run the demo loop
    try:
        asyncio.run(run_demo_loop())
    except KeyboardInterrupt:
        logger.info("\n👋 Demo stopped")


if __name__ == "__main__":
    main()
