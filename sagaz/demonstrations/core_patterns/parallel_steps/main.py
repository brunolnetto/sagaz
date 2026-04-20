#!/usr/bin/env python3
"""
Parallel Steps — DAG execution with failure strategies

Demonstrates saga steps that run in parallel using dependency graphs,
and compares the three parallel failure strategies:
  FAIL_FAST            — cancel siblings immediately on first failure
  WAIT_ALL             — let all parallel steps finish, then compensate
  FAIL_FAST_WITH_GRACE — cancel remaining, wait for in-flight to finish

Uses the imperative Saga API (add_step with dependencies) because
failure strategy configuration is only available on that interface.

No external infrastructure required — runs fully in-memory.

Usage:
    sagaz demo run parallel_steps
    python -m sagaz.demonstrations.parallel_steps.main
"""

import asyncio
import logging

from sagaz.core.saga import Saga, SagaContext
from sagaz.core.types import ParallelFailureStrategy, SagaStatus

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.parallel_steps")


# ============================================================================
# Step functions
# ============================================================================


async def setup(ctx: SagaContext) -> dict:
    logger.info("  ✓ Setup — preparing order environment")
    await asyncio.sleep(0.02)
    return {"setup_done": True}


async def undo_setup(ctx: SagaContext) -> None:
    logger.info("  ↩ Tearing down order environment")


async def fetch_inventory(ctx: SagaContext) -> dict:
    logger.info("  ✓ Fetch inventory (parallel A)")
    await asyncio.sleep(0.08)
    return {"inventory_checked": True}


async def release_inventory(ctx: SagaContext) -> None:
    logger.info("  ↩ Releasing inventory hold")


async def validate_payment(ctx: SagaContext) -> dict:
    logger.info("  ✓ Validate payment method (parallel B)")
    await asyncio.sleep(0.05)
    return {"payment_valid": True}


async def void_payment_check(ctx: SagaContext) -> None:
    logger.info("  ↩ Voiding payment validation")


async def check_fraud(ctx: SagaContext) -> dict:
    logger.info("  ✓ Fraud check (parallel C)")
    await asyncio.sleep(0.06)
    return {"fraud_clear": True}


async def void_fraud_check(ctx: SagaContext) -> None:
    logger.info("  ↩ Voiding fraud check record")


async def finalize(ctx: SagaContext) -> dict:
    logger.info("  ✓ Finalize — aggregating results")
    await asyncio.sleep(0.02)
    return {"finalized": True}


async def undo_finalize(ctx: SagaContext) -> None:
    logger.info("  ↩ Reversing finalization")


# Failing variant of fraud check
async def check_fraud_failing(ctx: SagaContext) -> dict:
    logger.info("  ✗ Fraud check (parallel C) — will FAIL")
    await asyncio.sleep(0.03)
    msg = "Fraud detection flagged the transaction"
    raise RuntimeError(msg)


# ============================================================================
# Build helpers
# ============================================================================


async def build_success_saga(strategy: ParallelFailureStrategy) -> Saga:
    """Build a passing saga with the given failure strategy."""
    saga = Saga(name=f"parallel-{strategy.value}", failure_strategy=strategy)
    await saga.add_step("setup", setup, undo_setup, dependencies=set())
    await saga.add_step(
        "fetch_inventory", fetch_inventory, release_inventory, dependencies={"setup"}
    )
    await saga.add_step(
        "validate_payment", validate_payment, void_payment_check, dependencies={"setup"}
    )
    await saga.add_step("check_fraud", check_fraud, void_fraud_check, dependencies={"setup"})
    await saga.add_step(
        "finalize",
        finalize,
        undo_finalize,
        dependencies={"fetch_inventory", "validate_payment", "check_fraud"},
    )
    return saga


async def build_failing_saga(strategy: ParallelFailureStrategy) -> Saga:
    """Build a saga where the fraud check fails."""
    saga = Saga(name=f"parallel-fail-{strategy.value}", failure_strategy=strategy)
    await saga.add_step("setup", setup, undo_setup, dependencies=set())
    await saga.add_step(
        "fetch_inventory", fetch_inventory, release_inventory, dependencies={"setup"}
    )
    await saga.add_step(
        "validate_payment", validate_payment, void_payment_check, dependencies={"setup"}
    )
    await saga.add_step(
        "check_fraud", check_fraud_failing, void_fraud_check, dependencies={"setup"}
    )
    await saga.add_step(
        "finalize",
        finalize,
        undo_finalize,
        dependencies={"fetch_inventory", "validate_payment", "check_fraud"},
    )
    return saga


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    # --- Phase 1: Successful parallel execution ------------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — Successful parallel execution")
    print("=" * 60)

    saga = await build_success_saga(ParallelFailureStrategy.FAIL_FAST)
    result = await saga.execute()

    print(f"\n  Status:          {result.status.value}")
    print(f"  Completed steps: {result.completed_steps}/{result.total_steps}")
    print(f"  Execution time:  {result.execution_time:.3f}s")

    # --- Phase 2: Compare failure strategies ---------------------------------
    strategies = [
        ParallelFailureStrategy.FAIL_FAST,
        ParallelFailureStrategy.WAIT_ALL,
        ParallelFailureStrategy.FAIL_FAST_WITH_GRACE,
    ]

    for strategy in strategies:
        print("\n" + "=" * 60)
        print(f"Phase 2 — Failure with {strategy.value} strategy")
        print("=" * 60)

        saga = await build_failing_saga(strategy)
        result = await saga.execute()

        print(f"\n  Strategy:            {strategy.value}")
        print(f"  Status:              {result.status.value}")
        print(f"  Completed steps:     {result.completed_steps}/{result.total_steps}")
        print(f"  Compensation errors: {len(result.compensation_errors)}")
        print(f"  Execution time:      {result.execution_time:.3f}s")

    print("\n" + "=" * 60)
    print("Done — parallel steps demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
