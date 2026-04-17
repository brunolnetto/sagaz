#!/usr/bin/env python3
"""
Metrics Demo — saga execution with simulated Prometheus metrics

This demo simulates saga execution and records timing data into
Prometheus counters, histograms, and gauges without requiring a
running saga engine.  Useful for understanding how metrics are
structured before connecting to a live environment.

Check after starting:
    http://localhost:8000/metrics   — raw Prometheus metrics
    http://localhost:3000           — Grafana dashboards

Usage:
    sagaz demo run metrics
    python -m sagaz.demonstrations.metrics.main
"""

import asyncio
import logging

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sagaz.demo.metrics")

# ============================================================================
# Prometheus metric definitions
# ============================================================================

SAGA_TOTAL = Counter(
    "saga_execution_total",
    "Total saga executions",
    ["saga_name", "status"],
)

SAGA_COMPENSATIONS = Counter(
    "saga_compensations_total",
    "Total saga compensations",
    ["saga_name"],
)

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

OUTBOX_EVENTS = Counter(
    "outbox_events_total",
    "Total outbox events",
    ["event_type", "status"],
)

ACTIVE_SAGAS = Gauge(
    "saga_active_count",
    "Number of currently running sagas",
    ["saga_name"],
)


# ============================================================================
# Simulation helpers
# ============================================================================


async def simulate_saga_execution(saga_name: str, steps: list[str], should_fail: bool = False):
    """Simulate a saga execution and record metrics."""
    import random
    import time

    start_time = time.time()
    ACTIVE_SAGAS.labels(saga_name=saga_name).inc()

    try:
        for step in steps:
            step_start = time.time()
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
        SAGA_COMPENSATIONS.labels(saga_name=saga_name).inc()
        OUTBOX_EVENTS.labels(event_type=f"{saga_name}.failed", status="sent").inc()
        logger.warning(f"❌ Saga '{saga_name}' failed: {e} (compensation triggered)")

    finally:
        duration = time.time() - start_time
        SAGA_DURATION.labels(saga_name=saga_name).observe(duration)
        ACTIVE_SAGAS.labels(saga_name=saga_name).dec()


# ============================================================================
# Demo loop
# ============================================================================


async def run_demo_loop():
    """Continuously run simulated sagas to generate metrics."""
    import random

    sagas = [
        ("OrderProcessing", ["validate", "reserve_inventory", "charge_payment", "ship"]),
        ("PaymentRefund", ["validate_refund", "process_refund", "notify"]),
        ("UserOnboarding", ["create_account", "send_welcome", "setup_defaults"]),
    ]

    logger.info("🚀 Starting metrics demo — Prometheus metrics at http://localhost:8000/metrics")
    logger.info("📊 View dashboards at http://localhost:3000")
    logger.info("Press Ctrl+C to stop\n")

    iteration = 0
    while True:
        iteration += 1
        saga_name, steps = random.choice(sagas)
        should_fail = random.random() < 0.1  # 10% failure rate

        logger.info(f"[{iteration}] Running saga: {saga_name}")
        await simulate_saga_execution(saga_name, steps, should_fail)
        await asyncio.sleep(random.uniform(1, 3))


# ============================================================================
# Entry point
# ============================================================================


def main():
    """Main entry point for sagaz demo run metrics."""
    logger.info("Starting Prometheus metrics server on port 8000...")
    start_http_server(8000)
    try:
        asyncio.run(run_demo_loop())
    except KeyboardInterrupt:
        logger.info("\n👋 Demo stopped")


if __name__ == "__main__":
    main()
