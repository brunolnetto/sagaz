"""
Outbox Pattern Demo

Self-contained demonstration of the Sagaz outbox pattern with:
1. A saga that writes outbox events during execution
2. PostgreSQL outbox storage
3. Redis broker publishing
4. An outbox worker that processes the queue

All services (PostgreSQL, Redis) are provisioned and torn down
automatically via testcontainers — no external Docker setup required.

Usage:
    python examples/outbox/outbox_demo.py

Prerequisites:
    - Docker daemon running
    - pip install testcontainers[postgres,redis]
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

# Allow importing _service_manager from the scripts directory when run directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _service_manager import ServiceManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("sagaz.outbox_demo")


# ============================================================================
# Saga definition
# ============================================================================


async def _demo_saga_run(pg_url: str, redis_url: str) -> None:
    """Run the outbox demo against already-started containers."""
    from sagaz import Saga, action
    from sagaz.core.outbox.brokers.redis import RedisBroker, RedisBrokerConfig
    from sagaz.core.outbox.types import OutboxConfig, OutboxEvent
    from sagaz.core.outbox.worker import OutboxWorker
    from sagaz.core.storage.backends.postgresql.outbox import (
        ASYNCPG_AVAILABLE,
        PostgreSQLOutboxStorage,
    )

    if not ASYNCPG_AVAILABLE:
        logger.error("asyncpg not installed. Run: pip install asyncpg")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 1. Set up storage and broker
    # ------------------------------------------------------------------
    storage = PostgreSQLOutboxStorage(connection_string=pg_url)
    await storage.initialize()
    logger.info("PostgreSQL outbox storage initialised")

    broker_cfg = RedisBrokerConfig(url=redis_url, stream_name="sagaz_outbox_demo")
    broker = RedisBroker(broker_cfg)
    await broker.connect()
    logger.info("Redis broker connected")

    # ------------------------------------------------------------------
    # 2. Write outbox events as part of a saga run
    # ------------------------------------------------------------------

    events_to_publish: list[OutboxEvent] = []

    class OrderSaga(Saga):
        saga_name = "order-demo"

        @action("validate_order")
        async def validate_order(self, ctx):
            events_to_publish.append(
                OutboxEvent(
                    saga_id=ctx.get("saga_id", "demo"),
                    event_type="order.validated",
                    payload={"order_id": "ORD-001", "status": "validated"},
                )
            )
            return {"validated": True}

        @action("reserve_inventory", depends_on=["validate_order"])
        async def reserve_inventory(self, ctx):
            events_to_publish.append(
                OutboxEvent(
                    saga_id=ctx.get("saga_id", "demo"),
                    event_type="inventory.reserved",
                    payload={"order_id": "ORD-001", "items": 2},
                )
            )
            return {"reserved": True}

        @action("charge_payment", depends_on=["reserve_inventory"])
        async def charge_payment(self, ctx):
            events_to_publish.append(
                OutboxEvent(
                    saga_id=ctx.get("saga_id", "demo"),
                    event_type="payment.charged",
                    payload={"order_id": "ORD-001", "amount": 99.99},
                )
            )
            return {"charged": True, "payment_id": f"PAY-{int(time.time())}"}

    saga = OrderSaga()
    await saga.run({"saga_id": "order-demo-001"})
    logger.info("Saga completed: %d events queued", len(events_to_publish))

    # Persist all queued events to the outbox atomically
    for event in events_to_publish:
        await storage.insert(event)
        logger.info("  → queued: %s", event.event_type)

    # ------------------------------------------------------------------
    # 3. Show pending outbox state
    # ------------------------------------------------------------------
    await storage.get_pending_count()

    # ------------------------------------------------------------------
    # 4. Run the outbox worker to publish events to Redis
    # ------------------------------------------------------------------
    worker = OutboxWorker(
        storage=storage,
        broker=broker,
        config=OutboxConfig(batch_size=10),
        worker_id="demo-worker",
    )
    processed = await worker.process_batch()
    await storage.get_pending_count()

    # ------------------------------------------------------------------
    # Cleanup connections (containers are stopped by ServiceManager)
    # ------------------------------------------------------------------
    await broker.close()
    if hasattr(storage, "_pool") and storage._pool:
        await storage._pool.close()

    if processed == len(events_to_publish):
        pass
    else:
        pass


# ============================================================================
# Entry point — owns full lifecycle
# ============================================================================


def main() -> None:
    """Provision services, run demo, tear down."""
    with ServiceManager(postgres=True, redis=True) as svc:
        asyncio.run(_demo_saga_run(svc.postgres_url, svc.redis_url))


if __name__ == "__main__":
    main()
