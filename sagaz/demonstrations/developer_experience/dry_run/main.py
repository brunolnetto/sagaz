#!/usr/bin/env python3
"""
Dry-Run Mode — validate and simulate saga execution without side effects

Demonstrates the DryRunEngine with two modes:
  VALIDATE — catches configuration errors (missing compensations, cycles, etc.)
  SIMULATE — previews execution order, parallel groups, and critical path

No external infrastructure required — runs fully in-memory.

Usage:
    sagaz demo run dry_run
    python -m sagaz.demonstrations.dry_run.main
"""

import asyncio
import logging

from sagaz import DryRunEngine, DryRunMode, Saga, action, compensate

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.dry_run")


# ============================================================================
# A well-configured saga (passes validation)
# ============================================================================


class ShippingSaga(Saga):
    """Five-step shipping saga with DAG parallelism."""

    saga_name = "shipping"

    @action("check_inventory")
    async def check_inventory(self, ctx: dict) -> dict:
        return {"inventory_ok": True}

    @compensate("check_inventory")
    async def release_inventory(self, ctx: dict) -> None:
        pass

    @action("reserve_warehouse", depends_on=["check_inventory"])
    async def reserve_warehouse(self, ctx: dict) -> dict:
        return {"warehouse_id": "WH-01"}

    @compensate("reserve_warehouse")
    async def release_warehouse(self, ctx: dict) -> None:
        pass

    @action("calculate_shipping", depends_on=["check_inventory"])
    async def calculate_shipping(self, ctx: dict) -> dict:
        return {"shipping_cost": 12.50}

    @compensate("calculate_shipping")
    async def void_shipping(self, ctx: dict) -> None:
        pass

    @action("charge_customer", depends_on=["reserve_warehouse", "calculate_shipping"])
    async def charge_customer(self, ctx: dict) -> dict:
        return {"charge_id": "CHG-01"}

    @compensate("charge_customer")
    async def refund_customer(self, ctx: dict) -> None:
        pass

    @action("dispatch_order", depends_on=["charge_customer"])
    async def dispatch_order(self, ctx: dict) -> dict:
        return {"tracking_number": "TRK-123"}

    @compensate("dispatch_order")
    async def cancel_dispatch(self, ctx: dict) -> None:
        pass


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    engine = DryRunEngine()
    context = {"order_id": "ORD-100", "customer_id": "CUST-1"}

    # --- Phase 1: VALIDATE ---------------------------------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — DryRunMode.VALIDATE")
    print("=" * 60)

    saga = ShippingSaga()
    result = await engine.run(saga, context, DryRunMode.VALIDATE)

    print(f"\n  Success:  {result.success}")
    print(f"  Errors:   {result.validation_errors or '(none)'}")
    print(f"  Warnings: {result.validation_warnings or '(none)'}")
    print("  Checks:")
    for key, val in sorted(result.validation_checks.items()):
        print(f"    {key}: {val}")

    # --- Phase 2: SIMULATE ---------------------------------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — DryRunMode.SIMULATE")
    print("=" * 60)

    saga2 = ShippingSaga()
    result2 = await engine.run(saga2, context, DryRunMode.SIMULATE)

    print(f"\n  Execution order: {result2.execution_order}")
    print(f"  Parallel groups: {result2.parallel_groups}")

    if result2.forward_layers:
        print("\n  Forward execution layers:")
        for layer in result2.forward_layers:
            deps = f" (after: {layer.dependencies})" if layer.dependencies else ""
            print(f"    Layer {layer.layer_number}: {layer.steps}{deps}")

    print(f"\n  Total layers:           {result2.total_layers}")
    print(f"  Max parallel width:     {result2.max_parallel_width}")
    print(f"  Critical path:          {result2.critical_path}")
    print(f"  Sequential complexity:  {result2.sequential_complexity}")
    print(f"  Parallel complexity:    {result2.parallel_complexity}")
    print(f"  Parallelization ratio:  {result2.parallelization_ratio:.2f}")

    print("\n" + "=" * 60)
    print("Done — dry-run demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
