#!/usr/bin/env python3
"""
End-to-End Sagaz Demo with Broker and Consumer

This demo shows the COMPLETE Sagaz flow:
1. Sagas execute with OutboxSagaListener → events go to PostgreSQL outbox
2. OutboxWorker processes events → publishes to Redis Streams
3. Consumer reads from Redis Streams → processes domain events

This is the production-ready pattern for reliable event delivery.

Prerequisites:
    - Docker services running (sagaz dev)
    - PostgreSQL on port 5433
    - Redis on port 6379

Usage:
    python scripts/e2e_demo.py
"""

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.e2e_demo")

# ============================================================================
# Imports from the actual Sagaz library
# ============================================================================

from sagaz import Saga, action, compensate, SagaStepError
from sagaz.listeners import (
    MetricsSagaListener,
    LoggingSagaListener,
    OutboxSagaListener,
)
from sagaz.monitoring.prometheus import PrometheusMetrics, start_metrics_server
from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig
from sagaz.outbox.worker import OutboxWorker
from sagaz.outbox.types import OutboxConfig

# ============================================================================
# Configuration
# ============================================================================

POSTGRES_URL = "postgresql://postgres:postgres@localhost:5433/sagaz"
REDIS_URL = "redis://localhost:6379/0"
REDIS_STREAM = "sagaz.events"
METRICS_PORT = 8000

# Global instances
prometheus_metrics = PrometheusMetrics()
outbox_storage = None
redis_broker = None
outbox_worker = None
running = True


# ============================================================================
# Define Sagaz sagas with Outbox publishing
# ============================================================================

class OrderProcessingSaga(Saga):
    """
    Order processing saga that publishes events via the Outbox pattern.
    
    Events are:
    1. Stored in PostgreSQL outbox table (transactionally safe)
    2. Processed by OutboxWorker
    3. Published to Redis Streams
    4. Consumed by downstream services
    """
    
    saga_name = "order-processing"
    
    def __init__(self, outbox_storage):
        # Set up listeners before parent init
        OrderProcessingSaga.listeners = [
            LoggingSagaListener(),
            MetricsSagaListener(metrics=prometheus_metrics),
            OutboxSagaListener(storage=outbox_storage, publish_step_events=True),
        ]
        super().__init__()
    
    @action("validate_order")
    async def validate_order(self, ctx):
        """Validate the order data."""
        import random
        await asyncio.sleep(random.uniform(0.01, 0.05))
        order_id = f"ORD-{random.randint(1000, 9999)}"
        return {"order_id": order_id, "validated": True}
    
    @action("reserve_inventory", depends_on=["validate_order"])
    async def reserve_inventory(self, ctx):
        """Reserve items in inventory."""
        import random
        await asyncio.sleep(random.uniform(0.02, 0.08))
        return {"inventory_reserved": True, "items": ctx.get("item_count", 3)}
    
    @compensate("reserve_inventory")
    async def release_inventory(self, ctx):
        """Release reserved inventory on failure."""
        import random
        await asyncio.sleep(random.uniform(0.01, 0.03))
        logger.info(f"  🔄 COMPENSATION: Released inventory for {ctx.get('order_id')}")
    
    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx):
        """Charge customer payment."""
        import random
        await asyncio.sleep(random.uniform(0.05, 0.15))
        # Simulate occasional payment failures
        if random.random() < 0.2:  # 20% failure rate for demo
            raise SagaStepError("Payment declined by processor")
        return {"payment_id": f"PAY-{random.randint(1000, 9999)}", "amount": 99.99}
    
    @compensate("charge_payment")
    async def refund_payment(self, ctx):
        """Refund the payment on failure."""
        import random
        await asyncio.sleep(random.uniform(0.02, 0.05))
        logger.info(f"  🔄 COMPENSATION: Refunded payment {ctx.get('payment_id')}")
    
    @action("ship_order", depends_on=["charge_payment"])
    async def ship_order(self, ctx):
        """Initiate order shipment."""
        import random
        await asyncio.sleep(random.uniform(0.03, 0.1))
        return {"tracking_id": f"TRACK-{random.randint(10000, 99999)}"}


# ============================================================================
# Outbox Worker - processes events and publishes to Redis
# ============================================================================

async def run_outbox_worker():
    """Background task that processes the outbox and publishes to Redis."""
    global outbox_worker
    
    config = OutboxConfig(
        batch_size=10,
        poll_interval_seconds=1.0,
        max_retries=3,
    )
    
    outbox_worker = OutboxWorker(
        storage=outbox_storage,
        broker=redis_broker,
        config=config,
        worker_id="demo-worker-1"
    )
    
    logger.info("📤 Outbox Worker started - processing events...")
    
    while running:
        try:
            processed = await outbox_worker.process_batch()
            if processed > 0:
                logger.info(f"📤 Outbox Worker: Published {processed} events to Redis")
        except Exception as e:
            logger.error(f"Outbox Worker error: {e}")
        
        await asyncio.sleep(1.0)


# ============================================================================
# Consumer - reads events from Redis Streams
# ============================================================================

async def run_consumer():
    """Background task that consumes events from Redis Streams."""
    
    await redis_broker.ensure_consumer_group()
    
    logger.info("📥 Consumer started - listening for events...")
    
    events_consumed = 0
    while running:
        try:
            # Read messages from Redis stream
            messages = await redis_broker.read_messages(count=10, block_ms=1000)
            
            for stream_name, stream_messages in messages:
                for msg_id, fields in stream_messages:
                    # Parse the event
                    topic = fields.get(b"topic", b"unknown").decode()
                    payload_bytes = fields.get(b"payload", b"{}")
                    
                    try:
                        payload = json.loads(payload_bytes.decode())
                    except:
                        payload = {"raw": payload_bytes.decode()}
                    
                    events_consumed += 1
                    logger.info(f"📥 Consumer received [{events_consumed}]: {topic}")
                    logger.info(f"    Payload: {json.dumps(payload, indent=2)[:200]}")
                    
                    # Acknowledge the message
                    await redis_broker.acknowledge(msg_id.decode())
                    
        except Exception as e:
            if "NOGROUP" in str(e):
                await redis_broker.ensure_consumer_group()
            else:
                logger.debug(f"Consumer read: {e}")
        
        await asyncio.sleep(0.1)


# ============================================================================
# Saga execution loop
# ============================================================================

async def run_saga_loop():
    """Run sagas periodically to generate events."""
    import random
    
    iteration = 0
    while running:
        iteration += 1
        
        saga = OrderProcessingSaga(outbox_storage)
        initial_context = {
            "customer_id": f"CUST-{random.randint(100, 999)}",
            "item_count": random.randint(1, 5),
        }
        
        logger.info(f"\n[Saga {iteration}] Starting order-processing saga...")
        
        try:
            result = await saga.run(initial_context)
            logger.info(f"[Saga {iteration}] ✅ Completed successfully!")
            logger.info(f"    Order: {result.get('order_id')}, Tracking: {result.get('tracking_id')}")
        except Exception as e:
            logger.warning(f"[Saga {iteration}] ❌ Failed: {e}")
        
        # Wait between sagas (reduced for demo - increase throughput)
        await asyncio.sleep(random.uniform(0.5, 1.5))


# ============================================================================
# Main
# ============================================================================

async def initialize():
    """Initialize all components."""
    global outbox_storage, redis_broker
    
    logger.info("🔧 Initializing components...")
    
    # Initialize PostgreSQL outbox storage
    outbox_storage = PostgreSQLOutboxStorage(connection_string=POSTGRES_URL)
    await outbox_storage.initialize()
    logger.info("  ✅ PostgreSQL outbox storage initialized")
    
    # Initialize Redis broker
    redis_broker = RedisBroker(RedisBrokerConfig(
        url=REDIS_URL,
        stream_name=REDIS_STREAM,
        consumer_group="sagaz-demo-consumers",
        consumer_name="consumer-1",
    ))
    await redis_broker.connect()
    logger.info("  ✅ Redis broker connected")
    
    # Start Prometheus metrics server
    start_metrics_server(METRICS_PORT)
    logger.info(f"  ✅ Prometheus metrics on port {METRICS_PORT}")


async def shutdown():
    """Clean shutdown of all components."""
    global running
    running = False
    
    logger.info("\n🛑 Shutting down...")
    
    if redis_broker:
        await redis_broker.close()
        logger.info("  ✅ Redis broker closed")
    
    if outbox_storage and hasattr(outbox_storage, '_pool') and outbox_storage._pool:
        await outbox_storage._pool.close()
        logger.info("  ✅ PostgreSQL storage closed")


async def main():
    """Main entry point."""
    global running
    
    print("\n" + "=" * 70)
    print("🚀 SAGAZ END-TO-END DEMO")
    print("=" * 70)
    print("""
This demo shows the complete Sagaz architecture:

  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
  │     SAGA        │────▶│  PostgreSQL     │────▶│  Outbox Worker  │
  │  (with Outbox   │     │  Outbox Table   │     │                 │
  │   Listener)     │     └─────────────────┘     └────────┬────────┘
  └─────────────────┘                                      │
                                                           ▼
                                             ┌─────────────────┐
                                             │  Redis Streams  │
                                             │   (Broker)      │
                                             └────────┬────────┘
                                                      │
                                                      ▼
                                             ┌─────────────────┐
                                             │    Consumer     │
                                             │  (Your Service) │
                                             └─────────────────┘
""")
    print(f"📊 Prometheus metrics: http://localhost:{METRICS_PORT}/metrics")
    print(f"📈 Grafana dashboard:  http://localhost:3000")
    print(f"🗄️  PostgreSQL:        localhost:5433")
    print(f"📨 Redis Streams:      localhost:6379 → {REDIS_STREAM}")
    print("\nPress Ctrl+C to stop")
    print("=" * 70 + "\n")
    
    # Handle shutdown signal
    def signal_handler(sig, frame):
        asyncio.create_task(shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        await initialize()
        
        # Start all background tasks
        await asyncio.gather(
            run_saga_loop(),
            run_outbox_worker(),
            run_consumer(),
        )
        
    except KeyboardInterrupt:
        pass
    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())
