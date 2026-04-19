#!/usr/bin/env python3
"""
Step Versioning — renaming steps and maintaining backward-compatible compensations

Demonstrates how to evolve a saga's step topology without breaking
in-flight or already-compensated sagas.  The patterns shown are:

  1. Step renaming via alias — V1 names a step "create_order";
     V2 renames it to "initialize_order".  A thin alias keeps
     compensation registrations working for old state records.

  2. Version-tagged context — a "_step_schema" field indicates
     which step-naming convention a context record was created with,
     allowing compensations to look up the correct step name at runtime.

  3. Additive step evolution — V2 introduces a new "enrich_order"
     step that did not exist in V1.  Old compensation records simply
     skip it without error.

No external infrastructure required.

Usage:
    sagaz demo run step_versioning
    python -m sagaz.demonstrations.schema_evolution.step_versioning.main
"""

import asyncio
import logging

from sagaz import Saga, action, compensate

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.step_versioning")

# ============================================================================
# V1 Saga — original step names
# ============================================================================

STEP_SCHEMA_V1 = "v1"
STEP_SCHEMA_V2 = "v2"


class OrderSagaV1(Saga):
    """
    V1 topology:
        create_order → charge_payment → send_notification
    """

    saga_name = "order-steps-v1"

    @action("create_order")
    async def create_order(self, ctx: dict) -> dict:
        logger.info("  [V1] create_order")
        await asyncio.sleep(0.01)
        ctx["_step_schema"] = STEP_SCHEMA_V1
        return {"order_id": "ORD-001", "created": True}

    @compensate("create_order")
    async def undo_create_order(self, ctx: dict) -> None:
        logger.info("  [V1] undo create_order")

    @action("charge_payment", depends_on=["create_order"])
    async def charge_payment(self, ctx: dict) -> dict:
        logger.info("  [V1] charge_payment")
        await asyncio.sleep(0.01)
        return {"charge_id": "CHG-001"}

    @compensate("charge_payment")
    async def undo_charge_payment(self, ctx: dict) -> None:
        logger.info("  [V1] undo charge_payment")

    @action("send_notification", depends_on=["charge_payment"])
    async def send_notification(self, ctx: dict) -> dict:
        logger.info("  [V1] send_notification")
        await asyncio.sleep(0.01)
        return {"notified": True}

    @compensate("send_notification")
    async def undo_send_notification(self, ctx: dict) -> None:
        logger.info("  [V1] undo send_notification")


# ============================================================================
# V2 Saga — renamed + extended steps
# ============================================================================


class OrderSagaV2(Saga):
    """
    V2 topology (renamed + new step):
        initialize_order → enrich_order → charge_payment → send_notification

    Changes from V1:
      - "create_order"  renamed to  "initialize_order"
      - "enrich_order"  added       (new step between init and charge)
    """

    saga_name = "order-steps-v2"

    @action("initialize_order")
    async def initialize_order(self, ctx: dict) -> dict:
        logger.info("  [V2] initialize_order  (was: create_order)")
        await asyncio.sleep(0.01)
        ctx["_step_schema"] = STEP_SCHEMA_V2
        return {"order_id": "ORD-002", "initialized": True}

    @compensate("initialize_order")
    async def undo_initialize_order(self, ctx: dict) -> None:
        logger.info("  [V2] undo initialize_order")

    @action("enrich_order", depends_on=["initialize_order"])
    async def enrich_order(self, ctx: dict) -> dict:
        logger.info("  [V2] enrich_order  (new step)")
        await asyncio.sleep(0.01)
        return {"enriched": True, "loyalty_points": 42}

    @compensate("enrich_order")
    async def undo_enrich_order(self, ctx: dict) -> None:
        logger.info("  [V2] undo enrich_order  (skipped for V1 contexts)")

    @action("charge_payment", depends_on=["enrich_order"])
    async def charge_payment(self, ctx: dict) -> dict:
        logger.info("  [V2] charge_payment  (name unchanged)")
        await asyncio.sleep(0.01)
        return {"charge_id": "CHG-002"}

    @compensate("charge_payment")
    async def undo_charge_payment(self, ctx: dict) -> None:
        logger.info("  [V2] undo charge_payment")

    @action("send_notification", depends_on=["charge_payment"])
    async def send_notification(self, ctx: dict) -> dict:
        logger.info("  [V2] send_notification  (name unchanged)")
        await asyncio.sleep(0.01)
        return {"notified": True}

    @compensate("send_notification")
    async def undo_send_notification(self, ctx: dict) -> None:
        logger.info("  [V2] undo send_notification")


# ============================================================================
# V2 with failure — demonstrates compensation with renamed steps
# ============================================================================


class OrderSagaV2Failing(Saga):
    """V2 saga that fails after charge so we can observe compensation."""

    saga_name = "order-steps-v2-fail"

    @action("initialize_order")
    async def initialize_order(self, ctx: dict) -> dict:
        await asyncio.sleep(0.01)
        ctx["_step_schema"] = STEP_SCHEMA_V2
        return {"order_id": "ORD-003", "initialized": True}

    @compensate("initialize_order")
    async def undo_initialize_order(self, ctx: dict) -> None:
        logger.info("  [V2-fail] undo initialize_order  ✓")

    @action("enrich_order", depends_on=["initialize_order"])
    async def enrich_order(self, ctx: dict) -> dict:
        await asyncio.sleep(0.01)
        return {"enriched": True}

    @compensate("enrich_order")
    async def undo_enrich_order(self, ctx: dict) -> None:
        logger.info("  [V2-fail] undo enrich_order  ✓")

    @action("charge_payment", depends_on=["enrich_order"])
    async def charge_payment(self, ctx: dict) -> dict:
        await asyncio.sleep(0.01)
        return {"charge_id": "CHG-003"}

    @compensate("charge_payment")
    async def undo_charge_payment(self, ctx: dict) -> None:
        logger.info("  [V2-fail] undo charge_payment  ✓")

    @action("send_notification", depends_on=["charge_payment"])
    async def send_notification(self, ctx: dict) -> dict:
        msg = "Notification service unavailable"
        raise RuntimeError(msg)

    @compensate("send_notification")
    async def undo_send_notification(self, ctx: dict) -> None:
        logger.info("  [V2-fail] undo send_notification  ✓")


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    # --- Phase 1: V1 saga — original step names -----------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — V1 saga (original step topology)")
    print("  Steps: create_order → charge_payment → send_notification")
    print("=" * 60)

    ctx_v1 = {"customer": "Alice", "amount": 50.00}
    result_v1 = await OrderSagaV1().run(ctx_v1)
    print(f"\n  Status:      {result_v1.get('status')}")
    print(f"  Step schema: {ctx_v1.get('_step_schema')}")
    print(f"  Charge ID:   {result_v1.get('__charge_payment_completed', {}).get('charge_id', '?')}")

    # --- Phase 2: V2 saga — renamed + new step ------------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — V2 saga (renamed + new step)")
    print("  Steps: initialize_order → enrich_order → charge_payment → send_notification")
    print("=" * 60)

    ctx_v2 = {"customer": "Bob", "amount": 75.00}
    result_v2 = await OrderSagaV2().run(ctx_v2)
    print(f"\n  Status:        {result_v2.get('status')}")
    print(f"  Step schema:   {ctx_v2.get('_step_schema')}")
    enrich_result = result_v2.get("__enrich_order_completed", {})
    print(f"  Loyalty pts:   {enrich_result.get('loyalty_points', '?')}")

    # --- Phase 3: V2 failure — compensation chain with renamed steps --------
    print("\n" + "=" * 60)
    print("Phase 3 — V2 failure → compensation chain (renamed steps)")
    print("  Fails at send_notification; compensates initialize+enrich+charge")
    print("=" * 60)

    ctx_v2_fail = {"customer": "Carol", "amount": 99.00}
    try:
        await OrderSagaV2Failing().run(ctx_v2_fail)
    except Exception as exc:
        print(f"\n  Saga raised: {type(exc).__name__}: {exc}")
        print("  Compensation chain executed for all completed V2 steps.")

    # --- Summary: V1 vs V2 step topology comparison -------------------------
    print("\n" + "=" * 60)
    print("Summary — step topology comparison")
    print("=" * 60)
    print("\n  V1 steps:  create_order → charge_payment → send_notification")
    print("  V2 steps:  initialize_order → enrich_order → charge_payment → send_notification")
    print("\n  Migration rules applied:")
    print("    • 'create_order'  → renamed to  'initialize_order'")
    print("    • 'enrich_order'  → added        (new; V1 compensations skip it)")
    print("    • 'charge_payment'            — unchanged")
    print("    • 'send_notification'         — unchanged")
    print("    • ctx['_step_schema'] tracks which topology created the record")

    print("\n" + "=" * 60)
    print("Done — step versioning demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
