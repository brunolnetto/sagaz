#!/usr/bin/env python3
"""
Orchestrator — managing concurrent sagas with SagaOrchestrator

Submits multiple sagas concurrently and queries live statistics.
Some sagas succeed, some fail — demonstrates saga isolation (one
failure does not affect siblings).

No external infrastructure required — runs fully in-memory.

Usage:
    sagaz demo run orchestrator
    python -m sagaz.demonstrations.orchestrator.main
"""

import asyncio
import logging
import random

from sagaz.core.execution.orchestrator import SagaOrchestrator
from sagaz.core.saga import Saga, SagaContext
from sagaz.core.types import SagaStatus

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.orchestrator")


# ============================================================================
# Step functions
# ============================================================================


async def process_item(ctx: SagaContext) -> dict:
    item_id = ctx.get("item_id", "?")
    delay = random.uniform(0.02, 0.08)
    await asyncio.sleep(delay)
    return {"item_id": item_id, "processed": True}


async def undo_process(result: dict, ctx: SagaContext) -> None:
    logger.info(f"  ↩ Undoing item {ctx.get('item_id')}")


async def ship_item(ctx: SagaContext) -> dict:
    item_id = ctx.get("item_id", "?")
    should_fail = ctx.get("should_fail", False)
    await asyncio.sleep(random.uniform(0.01, 0.04))
    if should_fail:
        msg = f"Shipping failed for item {item_id}"
        raise RuntimeError(msg)
    return {"shipped": True}


async def cancel_shipment(result: dict, ctx: SagaContext) -> None:
    logger.info(f"  ↩ Cancelling shipment for {ctx.get('item_id')}")


# ============================================================================
# Helpers
# ============================================================================


async def create_saga(item_id: str, should_fail: bool = False) -> Saga:
    saga = Saga(name=f"order-{item_id}")
    await saga.add_step("process", process_item, undo_process)
    await saga.add_step("ship", ship_item, cancel_shipment)
    saga.context.set("item_id", item_id)
    saga.context.set("should_fail", should_fail)
    return saga


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    orchestrator = SagaOrchestrator(verbose=True)
    num_sagas = 10
    fail_indices = {2, 5, 7}  # These sagas will fail

    # --- Phase 1: Submit all sagas concurrently ------------------------------
    print("\n" + "=" * 60)
    print(f"Phase 1 — Submitting {num_sagas} sagas concurrently")
    print(f"  (indices {fail_indices} are configured to fail)")
    print("=" * 60)

    tasks = []
    for i in range(num_sagas):
        saga = await create_saga(f"ITEM-{i:03d}", should_fail=(i in fail_indices))
        tasks.append(orchestrator.execute_saga(saga))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # --- Phase 2: Summary ----------------------------------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — Execution results")
    print("=" * 60)

    for i, res in enumerate(results):
        if isinstance(res, Exception):
            print(f"  ITEM-{i:03d}: EXCEPTION — {res}")
        else:
            print(f"  ITEM-{i:03d}: {res.status.value}")

    # --- Phase 3: Orchestrator statistics ------------------------------------
    print("\n" + "=" * 60)
    print("Phase 3 — Orchestrator statistics")
    print("=" * 60)

    stats = await orchestrator.get_statistics()
    print(f"\n  Total sagas tracked: {stats['total_sagas']}")
    for key in ("completed", "rolled_back", "failed", "executing", "pending"):
        print(f"  {key:>15}: {stats.get(key, 0)}")

    # Verify isolation: completed + rolled_back should equal total
    completed = stats.get("completed", 0)
    rolled_back = stats.get("rolled_back", 0)
    failed = stats.get("failed", 0)
    total = stats["total_sagas"]
    finished = completed + rolled_back + failed
    print(f"\n  Isolation check: {finished}/{total} sagas finished independently")

    print("\n" + "=" * 60)
    print("Done — orchestrator demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
