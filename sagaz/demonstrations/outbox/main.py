#!/usr/bin/env python3
"""
Outbox Pattern Demo — reliable event delivery via PostgreSQL + Redis

This demo shows the full Sagaz outbox pattern:
1. OrderSaga executes and writes events to a PostgreSQL outbox table
2. OutboxWorker polls the table and publishes events to Redis Streams
3. A simple consumer reads from Redis Streams and prints the events

Prerequisites:
    PostgreSQL and Redis must be reachable. Set POSTGRES_URL and REDIS_URL
    environment variables or ensure the defaults are accessible:
      - PostgreSQL: postgresql://test:test@localhost:5432/test
      - Redis:      redis://localhost:6379/0

Usage:
    sagaz demo run outbox
    python -m sagaz.demonstrations.outbox.main
"""

import asyncio
import json
import logging
import os

from sagaz import Saga, action, compensate
from sagaz.listeners import OutboxSagaListener
from sagaz.core.outbox.brokers.redis import RedisBroker, RedisBrokerConfig
from sagaz.core.outbox.types import OutboxConfig
from sagaz.core.outbox.worker import OutboxWorker
from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.outbox")

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://test:test@localhost:5432/test")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_STREAM = "sagaz.outbox.demo"


# ============================================================================
# Saga definition
# ============================================================================


class OrderSaga(Saga):
    """Simple order saga that emits outbox events at each step."""

    saga_name = "order-saga"

    def __init__(self, outbox_storage):
        OrderSaga.listeners = [
            OutboxSagaListener(storage=outbox_storage, publish_step_events=True),
        ]
        super().__init__()

    @action("validate_order")
    async def validate_order(self, ctx):
        order_id = ctx.get("order_id", "ORD-001")
        logger.info(f"  Validating order {order_id}")
        await asyncio.sleep(0.05)
        return {"order_id": order_id, "validated": True}

    @action("reserve_inventory", depends_on=["validate_order"])
    async def reserve_inventory(self, ctx):
        logger.info("  Reserving inventory")
        await asyncio.sleep(0.05)
        return {"reserved": True, "sku": "ITEM-42"}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx):
        logger.info("  COMPENSATION: Releasing inventory")
        await asyncio.sleep(0.02)

    @action("confirm_order", depends_on=["reserve_inventory"])
    async def confirm_order(self, ctx):
        logger.info("  Confirming order")
        await asyncio.sleep(0.05)
        return {"confirmed": True}


# ============================================================================
# Entry point
# ============================================================================


async def _run():
    """Run the outbox pattern demonstration."""
    print("\n" + "=" * 70)
    print("🚀 SAGAZ OUTBOX PATTERN DEMO")
    print("=" * 70)
    print(f"\n  PostgreSQL: {POSTGRES_URL}")
    print(f"  Redis:      {REDIS_URL} → stream: {REDIS_STREAM}")
    print("=" * 70 + "\n")

    # 1. Connect storage and broker
    print("Step 1 — connecting storage and broker...")
    outbox_storage = PostgreSQLOutboxStorage(connection_string=POSTGRES_URL)
    await outbox_storage.initialize()

    redis_broker = RedisBroker(
        RedisBrokerConfig(
            url=REDIS_URL,
            stream_name=REDIS_STREAM,
            consumer_group="demo-consumers",
            consumer_name="consumer-1",
        )
    )
    await redis_broker.connect()
    await redis_broker.ensure_consumer_group()
    logger.info("  ✅ Storage and broker connected")

    # 2. Execute saga
    print("\nStep 2 — executing OrderSaga...")
    saga = OrderSaga(outbox_storage)
    result = await saga.run({"order_id": "ORD-DEMO-001", "customer_id": "CUST-42"})
    logger.info(f"  ✅ Saga completed: {result}")

    # 3. Show pending outbox events
    print("\nStep 3 — pending outbox events (before worker runs)...")
    pending = await outbox_storage.get_pending_events(limit=20)
    logger.info(f"  Pending events: {len(pending)}")
    for evt in pending:
        logger.info(f"    • topic={evt.topic}  status={evt.status}")

    # 4. Run OutboxWorker to publish events
    print("\nStep 4 — running OutboxWorker to publish to Redis...")
    config = OutboxConfig(batch_size=20, poll_interval_seconds=0.5, max_retries=3)
    worker = OutboxWorker(
        storage=outbox_storage, broker=redis_broker, config=config, worker_id="demo-worker"
    )
    published = await worker.process_batch()
    logger.info(f"  ✅ Published {published} events to Redis stream '{REDIS_STREAM}'")

    # 5. Consume events from Redis
    print("\nStep 5 — consuming events from Redis stream...")
    messages = await redis_broker.read_messages(count=50, block_ms=1000)
    consumed = 0
    for _stream_name, stream_messages in messages:
        for msg_id, fields in stream_messages:
            topic = fields.get(b"topic", b"unknown").decode()
            payload_bytes = fields.get(b"payload", b"{}")
            try:
                payload = json.loads(payload_bytes.decode())
            except Exception:
                payload = {}
            consumed += 1
            logger.info(f"  📥 [{consumed}] topic={topic}")
            logger.info(f"       payload={json.dumps(payload)[:120]}")
            await redis_broker.acknowledge(msg_id.decode())

    logger.info(f"  ✅ Consumed {consumed} events")

    # Cleanup
    await redis_broker.close()
    if hasattr(outbox_storage, "_pool") and outbox_storage._pool:
        await outbox_storage._pool.close()

    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)
    print(f"  Sagas executed:    1")
    print(f"  Events published:  {published}")
    print(f"  Events consumed:   {consumed}")
    print("=" * 70 + "\n")


def main():
    """Main entry point for sagaz demo run outbox."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
