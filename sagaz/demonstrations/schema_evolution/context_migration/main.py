#!/usr/bin/env python3
"""
Context Migration — evolving saga context schemas between versions

Demonstrates how to safely evolve the data carried inside a saga's context
when the business domain changes.  No built-in versioning API is required;
the pattern relies on:

  1. A schema-version sentinel stored in the context itself.
  2. A pure-function migrator that up-grades old context records.
  3. Using InMemorySagaStorage to persist, reload, migrate, and re-execute.

Two versions of an order saga are shown:

  V1 — flat customer string:  {"customer": "Alice"}
  V2 — structured customer:   {"customer": {"name": "Alice", "email": "…"}}

Phases:
  1. Execute V1 saga and persist its context.
  2. Load the persisted record and run the V1 → V2 migration.
  3. Execute a V2 saga with the migrated context and verify it succeeds.

No external infrastructure required.

Usage:
    sagaz demo run context_migration
    python -m sagaz.demonstrations.schema_evolution.context_migration.main
"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, action, compensate
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.types import SagaStatus

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.context_migration")

# ============================================================================
# Schema versioning helpers
# ============================================================================

CURRENT_SCHEMA_VERSION = 2


def get_schema_version(ctx: dict) -> int:
    """Return schema version embedded in context, defaulting to 1."""
    return ctx.get("_schema_version", 1)


def migrate_v1_to_v2(ctx: dict) -> dict:
    """
    V1 → V2: promote flat `customer` string to structured dict.

    Before: {"customer": "Alice", "_schema_version": 1}
    After:  {"customer": {"name": "Alice", "email": "unknown@example.com"},
             "_schema_version": 2}
    """
    migrated = dict(ctx)
    if isinstance(migrated.get("customer"), str):
        migrated["customer"] = {
            "name": migrated["customer"],
            "email": "unknown@example.com",  # back-filled default
        }
    migrated["_schema_version"] = 2
    return migrated


def migrate_context(ctx: dict) -> dict:
    """Apply all pending migrations in order until reaching current version."""
    migrations = {
        1: migrate_v1_to_v2,
        # future: 2: migrate_v2_to_v3, …
    }
    version = get_schema_version(ctx)
    while version < CURRENT_SCHEMA_VERSION:
        ctx = migrations[version](ctx)
        version = get_schema_version(ctx)
    return ctx


# ============================================================================
# V1 Saga — uses flat customer string
# ============================================================================


class OrderSagaV1(Saga):
    saga_name = "order-v1"

    @action("create_order")
    async def create_order(self, ctx: dict) -> dict:
        customer = ctx.get("customer", "unknown")
        logger.info(f"  [V1] Creating order for customer: {customer!r}")
        await asyncio.sleep(0.02)
        return {"order_id": "ORD-V1-001", "customer": customer}

    @compensate("create_order")
    async def cancel_order(self, ctx: dict) -> None:
        logger.info("  [V1] Cancelling order")

    @action("send_confirmation", depends_on=["create_order"])
    async def send_confirmation(self, ctx: dict) -> dict:
        customer = ctx.get("customer", "unknown")
        logger.info(f"  [V1] Sending confirmation to: {customer!r}")
        await asyncio.sleep(0.01)
        return {"email_sent": True}

    @compensate("send_confirmation")
    async def revoke_confirmation(self, ctx: dict) -> None:
        logger.info("  [V1] Revoking confirmation")


# ============================================================================
# V2 Saga — uses structured customer dict
# ============================================================================


class OrderSagaV2(Saga):
    saga_name = "order-v2"

    @action("create_order")
    async def create_order(self, ctx: dict) -> dict:
        customer = ctx.get("customer", {})
        name = customer.get("name", "unknown") if isinstance(customer, dict) else str(customer)
        email = customer.get("email", "?") if isinstance(customer, dict) else "?"
        logger.info(f"  [V2] Creating order for {name} <{email}>")
        await asyncio.sleep(0.02)
        return {"order_id": "ORD-V2-001", "customer_name": name}

    @compensate("create_order")
    async def cancel_order(self, ctx: dict) -> None:
        logger.info("  [V2] Cancelling order")

    @action("send_confirmation", depends_on=["create_order"])
    async def send_confirmation(self, ctx: dict) -> dict:
        customer = ctx.get("customer", {})
        email = customer.get("email", "?") if isinstance(customer, dict) else "?"
        logger.info(f"  [V2] Sending confirmation email to: {email}")
        await asyncio.sleep(0.01)
        return {"email_sent": True}

    @compensate("send_confirmation")
    async def revoke_confirmation(self, ctx: dict) -> None:
        logger.info("  [V2] Revoking confirmation")


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    storage = InMemorySagaStorage()

    # --- Phase 1: Execute V1 saga and persist context -----------------------
    print("\n" + "=" * 60)
    print("Phase 1 — Execute V1 saga (flat customer string)")
    print("=" * 60)

    v1_context: dict[str, Any] = {
        "order_id": "ORD-001",
        "customer": "Alice",  # V1 schema: plain string
        "_schema_version": 1,
    }

    saga_v1 = OrderSagaV1()
    result_v1 = await saga_v1.run(v1_context)

    saga_id = result_v1.get("saga_id", "v1-saga")
    print(f"\n  V1 saga result status: {result_v1.get('status')}")
    print(f"  V1 context snapshot:   customer={v1_context['customer']!r}, "
          f"schema_version={v1_context['_schema_version']}")

    # Persist the V1 context to storage
    await storage.save_saga_state(
        saga_id=saga_id,
        saga_name="order-v1",
        status=SagaStatus.COMPLETED,
        steps=[],
        context=v1_context,
    )
    print(f"\n  Persisted saga {saga_id} with V1 context.")

    # --- Phase 2: Load & migrate context ------------------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — Load persisted V1 context and migrate to V2")
    print("=" * 60)

    loaded = await storage.load_saga_state(saga_id)
    assert loaded is not None
    raw_ctx = loaded.get("context", {})

    print(f"\n  Loaded context (raw):    {raw_ctx}")
    print(f"  Schema version detected: {get_schema_version(raw_ctx)}")

    migrated_ctx = migrate_context(raw_ctx)
    print(f"\n  Migrated context:        {migrated_ctx}")
    print(f"  Customer (V2 struct):    {migrated_ctx['customer']}")
    print(f"  Schema version after:    {get_schema_version(migrated_ctx)}")

    # --- Phase 3: Execute V2 saga with migrated context ---------------------
    print("\n" + "=" * 60)
    print("Phase 3 — Execute V2 saga with migrated context")
    print("=" * 60)

    saga_v2 = OrderSagaV2()
    result_v2 = await saga_v2.run(migrated_ctx)

    print(f"\n  V2 saga result status: {result_v2.get('status')}")
    print(f"  Email sent:            {result_v2.get('__send_confirmation_completed', False)}")

    customer_v2 = migrated_ctx["customer"]
    print(f"\n  Migration summary:")
    print(f"    V1 customer:  {raw_ctx.get('customer')!r}")
    print(f"    V2 customer:  name={customer_v2['name']!r}, email={customer_v2['email']!r}")

    print("\n" + "=" * 60)
    print("Done — context migration demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
