#!/usr/bin/env python3
"""
Lifecycle Hooks — step-level observers and saga listeners

Demonstrates two complementary observability mechanisms:
  1. Step-level hooks: on_enter, on_success, on_failure, on_exit
     (attached per-step via the @step decorator)
  2. Saga listeners: LoggingSagaListener and custom SagaListener subclass
     (attached at the saga class level, notified for every step)

No external infrastructure required — runs fully in-memory.

Usage:
    sagaz demo run lifecycle_hooks
    python -m sagaz.demonstrations.lifecycle_hooks.main
"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaListener, action, compensate
from sagaz.core.decorators._steps import step

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.lifecycle_hooks")


# ============================================================================
# Step-level hook functions
# ============================================================================


async def log_enter(ctx: dict, step_name: str) -> None:
    print(f"    [hook] on_enter  → {step_name}")


async def log_success(ctx: dict, step_name: str, result: Any) -> None:
    print(f"    [hook] on_success → {step_name}  result_keys={sorted(result.keys()) if result else '∅'}")


async def log_failure(ctx: dict, step_name: str, error: Exception) -> None:
    print(f"    [hook] on_failure → {step_name}  error={error}")


async def log_exit(ctx: dict, step_name: str) -> None:
    print(f"    [hook] on_exit   → {step_name}")


# ============================================================================
# Custom saga listener
# ============================================================================


class AuditListener(SagaListener):
    """Records an in-memory audit trail of saga events."""

    def __init__(self) -> None:
        self.trail: list[str] = []

    async def on_saga_start(self, saga_name: str, saga_id: str, ctx: dict) -> None:
        self.trail.append(f"saga_start({saga_name})")

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict) -> None:
        self.trail.append(f"step_enter({step_name})")

    async def on_step_success(self, saga_name: str, step_name: str, ctx: dict, result: Any) -> None:
        self.trail.append(f"step_success({step_name})")

    async def on_step_failure(self, saga_name: str, step_name: str, ctx: dict, error: Exception) -> None:
        self.trail.append(f"step_failure({step_name})")

    async def on_compensation_start(self, saga_name: str, step_name: str, ctx: dict) -> None:
        self.trail.append(f"compensation_start({step_name})")

    async def on_compensation_complete(self, saga_name: str, step_name: str, ctx: dict) -> None:
        self.trail.append(f"compensation_complete({step_name})")

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict) -> None:
        self.trail.append(f"saga_complete({saga_name})")

    async def on_saga_failed(self, saga_name: str, saga_id: str, ctx: dict, error: Exception) -> None:
        self.trail.append(f"saga_failed({saga_name})")


# ============================================================================
# Sagas
# ============================================================================

audit_listener = AuditListener()


class HookedSaga(Saga):
    """Saga with per-step hooks and a global audit listener."""

    saga_name = "hooked-order"
    listeners = [audit_listener]

    @step(
        "validate",
        on_enter=log_enter,
        on_success=log_success,
        on_failure=log_failure,
        on_exit=log_exit,
    )
    async def validate(self, ctx: dict) -> dict:
        logger.info("  ✓ Validating order")
        await asyncio.sleep(0.02)
        return {"validated": True}

    @compensate("validate")
    async def undo_validate(self, ctx: dict) -> None:
        logger.info("  ↩ Undoing validation")

    @step(
        "charge",
        depends_on=["validate"],
        on_enter=log_enter,
        on_success=log_success,
        on_failure=log_failure,
        on_exit=log_exit,
    )
    async def charge(self, ctx: dict) -> dict:
        logger.info("  ✓ Charging payment")
        await asyncio.sleep(0.02)
        return {"charge_id": "CHG-01"}

    @compensate("charge")
    async def refund(self, ctx: dict) -> None:
        logger.info("  ↩ Refunding payment")

    @step(
        "ship",
        depends_on=["charge"],
        on_enter=log_enter,
        on_success=log_success,
        on_failure=log_failure,
        on_exit=log_exit,
    )
    async def ship(self, ctx: dict) -> dict:
        logger.info("  ✓ Shipping order")
        await asyncio.sleep(0.02)
        return {"tracking": "TRK-99"}

    @compensate("ship")
    async def cancel_shipment(self, ctx: dict) -> None:
        logger.info("  ↩ Cancelling shipment")


class FailingHookedSaga(Saga):
    """Same structure but shipping always fails — shows failure hooks + compensation listener."""

    saga_name = "hooked-failing"
    listeners = [audit_listener]

    @step("validate", on_enter=log_enter, on_success=log_success, on_exit=log_exit)
    async def validate(self, ctx: dict) -> dict:
        logger.info("  ✓ Validating order")
        return {"validated": True}

    @compensate("validate")
    async def undo_validate(self, ctx: dict) -> None:
        logger.info("  ↩ Undoing validation")

    @step("charge", depends_on=["validate"], on_enter=log_enter, on_success=log_success, on_exit=log_exit)
    async def charge(self, ctx: dict) -> dict:
        logger.info("  ✓ Charging payment")
        return {"charge_id": "CHG-02"}

    @compensate("charge")
    async def refund(self, ctx: dict) -> None:
        logger.info("  ↩ Refunding payment")

    @step("ship", depends_on=["charge"], on_enter=log_enter, on_failure=log_failure, on_exit=log_exit)
    async def ship(self, ctx: dict) -> dict:
        msg = "Warehouse closed!"
        raise RuntimeError(msg)

    @compensate("ship")
    async def cancel_shipment(self, ctx: dict) -> None:
        logger.info("  ↩ Cancelling shipment")


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    # --- Phase 1: Success path with hooks ------------------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — Success path with per-step hooks")
    print("=" * 60)

    audit_listener.trail.clear()
    saga = HookedSaga()
    result = await saga.run({"order_id": "ORD-10"})

    print(f"\n  Final context keys: {sorted(result.keys())}")
    print(f"\n  Audit trail ({len(audit_listener.trail)} events):")
    for event in audit_listener.trail:
        print(f"    • {event}")

    # --- Phase 2: Failure path -----------------------------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — Failure path (shipping fails, compensations triggered)")
    print("=" * 60)

    audit_listener.trail.clear()
    failing = FailingHookedSaga()
    try:
        await failing.run({"order_id": "ORD-11"})
    except Exception as exc:
        print(f"\n  Saga raised: {type(exc).__name__}: {exc}")

    print(f"\n  Audit trail ({len(audit_listener.trail)} events):")
    for event in audit_listener.trail:
        print(f"    • {event}")

    print("\n" + "=" * 60)
    print("Done — lifecycle hooks demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
