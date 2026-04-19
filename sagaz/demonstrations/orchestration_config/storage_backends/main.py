#!/usr/bin/env python3
"""
Storage Backends — compare in-memory, Redis, and PostgreSQL saga storage

Runs the same saga against each storage backend, persists state, and
verifies it can be loaded back.  Redis and PostgreSQL phases use
testcontainers (Docker) and are gracefully skipped when Docker is
unavailable.

Prerequisites:
    - Docker (optional, for Redis + PostgreSQL phases)

Usage:
    sagaz demo run storage_backends
    python -m sagaz.demonstrations.storage_backends.main
"""

import asyncio
import logging
from typing import Any

from sagaz.core.saga import Saga, SagaContext
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.storage.base import SagaStorage
from sagaz.core.types import SagaStatus

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.storage_backends")


# ============================================================================
# Step functions
# ============================================================================


async def create_order(ctx: SagaContext) -> dict:
    return {"order_id": ctx.get("order_id", "ORD-1"), "created": True}


async def cancel_order(ctx: SagaContext) -> None:
    pass


async def charge_payment(ctx: SagaContext) -> dict:
    return {"charge_id": "CHG-1", "amount": 42.00}


async def refund_payment(ctx: SagaContext) -> None:
    pass


# ============================================================================
# Storage test helper
# ============================================================================


async def test_storage(label: str, storage: SagaStorage) -> None:
    """Run a saga, persist state, and verify retrieval."""
    print(f"\n  [{label}] Building and executing saga ...")

    saga = Saga(name="storage-test")
    await saga.add_step("create_order", create_order, cancel_order)
    await saga.add_step("charge_payment", charge_payment, refund_payment)
    result = await saga.execute()

    saga_id = saga.saga_id
    print(f"  [{label}] Saga {saga_id} → {result.status.value}")

    # Persist
    await storage.save_saga_state(
        saga_id=saga_id,
        saga_name=saga.name,
        status=result.status,
        steps=[],
        context=dict(saga.context) if hasattr(saga.context, "__iter__") else {},
    )
    print(f"  [{label}] State saved.")

    # Retrieve
    loaded = await storage.load_saga_state(saga_id)
    if loaded:
        print(f"  [{label}] State loaded — status={loaded.get('status')}")
    else:
        print(f"  [{label}] State loaded — (none returned)")


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    # --- Phase 1: In-Memory --------------------------------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — InMemorySagaStorage")
    print("=" * 60)

    mem_storage = InMemorySagaStorage()
    await test_storage("Memory", mem_storage)

    # --- Phase 2: Redis (requires Docker) ------------------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — RedisSagaStorage (testcontainers)")
    print("=" * 60)

    try:
        from sagaz.demonstrations.utils import ServiceManager

        with ServiceManager(redis=True) as svc:
            from sagaz.core.storage.backends.redis.saga import RedisSagaStorage

            async with RedisSagaStorage(svc.redis_url) as redis_storage:
                await test_storage("Redis", redis_storage)
    except Exception as exc:
        print(f"\n  Skipping Redis — {type(exc).__name__}: {exc}")

    # --- Phase 3: PostgreSQL (requires Docker) -------------------------------
    print("\n" + "=" * 60)
    print("Phase 3 — PostgreSQLSagaStorage (testcontainers)")
    print("=" * 60)

    try:
        from sagaz.demonstrations.utils import ServiceManager

        with ServiceManager(postgres=True) as svc:
            from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

            async with PostgreSQLSagaStorage(svc.postgres_url) as pg_storage:
                await test_storage("PostgreSQL", pg_storage)
    except Exception as exc:
        print(f"\n  Skipping PostgreSQL — {type(exc).__name__}: {exc}")

    print("\n" + "=" * 60)
    print("Done — storage backends demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
