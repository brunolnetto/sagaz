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
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sagaz import Saga, SagaConfig, SagaFailedError
from sagaz.core.types import ParallelFailureStrategy

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.parallel_steps")

Step = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


# ============================================================================
# Step functions
# ============================================================================


async def setup(ctx: dict) -> dict:
    logger.info("  ✓ Setup — preparing order environment")
    await asyncio.sleep(0.02)
    return {"setup_done": True}


async def undo_setup(ctx: dict) -> None:
    logger.info("  ↩ Tearing down order environment")


async def fetch_inventory(ctx: dict) -> dict:
    logger.info("  ✓ Fetch inventory (parallel A)")
    await asyncio.sleep(0.08)
    return {"inventory_checked": True}


async def release_inventory(ctx: dict) -> None:
    logger.info("  ↩ Releasing inventory hold")


async def validate_payment(ctx: dict) -> dict:
    logger.info("  ✓ Validate payment method (parallel B)")
    await asyncio.sleep(0.05)
    return {"payment_valid": True}


async def void_payment_check(ctx: dict) -> None:
    logger.info("  ↩ Voiding payment validation")


async def check_fraud(ctx: dict) -> dict:
    logger.info("  ✓ Fraud check (parallel C)")
    await asyncio.sleep(0.06)
    return {"fraud_clear": True}


async def void_fraud_check(ctx: dict) -> None:
    logger.info("  ↩ Voiding fraud check record")


async def finalize(ctx: dict) -> dict:
    logger.info("  ✓ Finalize — aggregating results")
    await asyncio.sleep(0.02)
    return {"finalized": True}


async def undo_finalize(ctx: dict) -> None:
    logger.info("  ↩ Reversing finalization")


# Failing variant of fraud check
async def check_fraud_failing(ctx: dict) -> dict:
    logger.info("  ✗ Fraud check (parallel C) — will FAIL")
    await asyncio.sleep(0.03)
    msg = "Fraud detection flagged the transaction"
    raise RuntimeError(msg)


# ============================================================================
# Build helpers
# ============================================================================


def _build(strategy: ParallelFailureStrategy, name: str, fraud_check: Step) -> Saga:
    """setup, then three checks in parallel, then finalize."""
    config = SagaConfig(
        failure_strategy=strategy.name,
        failure_grace_period=0.05,
        default_max_retries=0,
        metrics=False,
        logging=False,
    )
    saga = Saga(config=config)
    saga.saga_name = name
    saga.add_step("setup", setup, undo_setup)
    saga.add_step("fetch_inventory", fetch_inventory, release_inventory, depends_on=["setup"])
    saga.add_step("validate_payment", validate_payment, void_payment_check, depends_on=["setup"])
    saga.add_step("check_fraud", fraud_check, void_fraud_check, depends_on=["setup"])
    saga.add_step(
        "finalize",
        finalize,
        undo_finalize,
        depends_on=["fetch_inventory", "validate_payment", "check_fraud"],
    )
    return saga


def build_success_saga(strategy: ParallelFailureStrategy) -> Saga:
    """Build a passing saga with the given failure strategy."""
    return _build(strategy, f"parallel-{strategy.value}", check_fraud)


def build_failing_saga(strategy: ParallelFailureStrategy) -> Saga:
    """Build a saga where the fraud check fails."""
    return _build(strategy, f"parallel-fail-{strategy.value}", check_fraud_failing)


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    # --- Phase 1: Successful parallel execution ------------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — Successful parallel execution")
    print("=" * 60)

    started = time.perf_counter()
    context = await build_success_saga(ParallelFailureStrategy.FAIL_FAST).run({})

    print("\n  Status:          completed")
    print(f"  Finalized:       {context['finalized']}")
    print(f"  Execution time:  {time.perf_counter() - started:.3f}s")

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

        started = time.perf_counter()
        try:
            await build_failing_saga(strategy).run({})
        except SagaFailedError as failure:
            print(f"\n  Strategy:            {strategy.value}")
            print(f"  Status:              {failure.status.value}")
            print(f"  Failed step:         {failure.failed_step}")
            print(f"  Compensation errors: {len(failure.compensation_errors)}")
            print(f"  Execution time:      {time.perf_counter() - started:.3f}s")

    print("\n" + "=" * 60)
    print("Done — parallel steps demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
