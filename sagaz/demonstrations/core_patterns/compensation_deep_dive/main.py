#!/usr/bin/env python3
"""
Compensation Deep Dive — mechanical, semantic, and pivot compensation

Demonstrates three compensation types:
  1. MECHANICAL  — simple, symmetric undo (e.g. delete what was created)
  2. SEMANTIC    — logical undo that may differ from the forward action
  3. Pivot steps — irreversible point of no return; ancestors become
     tainted and a @forward_recovery handler decides how to proceed

Shows:
  - CompensationType enum on @compensate
  - pivot=True on @step to mark irreversible steps
  - @forward_recovery decorator for post-pivot failure handling
  - RecoveryAction.SKIP to continue past a failed post-pivot step
  - PARTIALLY_COMMITTED and FORWARD_RECOVERY saga statuses

No external infrastructure required — runs fully in-memory.

Usage:
    sagaz demo run compensation_deep_dive
    python -m sagaz.demonstrations.compensation_deep_dive.main
"""

import asyncio
import logging

from sagaz import Saga, action, compensate, forward_recovery
from sagaz.core.execution.graph import CompensationType
from sagaz.core.execution.pivot import RecoveryAction

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.compensation")


# ============================================================================
# 1. Standard saga — shows mechanical + semantic compensation
# ============================================================================


class PaymentSaga(Saga):
    """
    Three-step saga:
      reserve_funds  → MECHANICAL compensation (simple reversal)
      charge_card    → SEMANTIC compensation (issue refund, not a simple delete)
      send_receipt   → always fails to trigger the compensation chain
    """

    saga_name = "payment-compensation"

    @action("reserve_funds")
    async def reserve_funds(self, ctx: dict) -> dict:
        logger.info("  ✓ Reserving $100 from account")
        await asyncio.sleep(0.02)
        return {"reservation_id": "RSRV-1", "amount": 100.0}

    @compensate("reserve_funds", compensation_type=CompensationType.MECHANICAL)
    async def release_funds(self, ctx: dict) -> None:
        logger.info(f"  ↩ [MECHANICAL] Releasing reservation {ctx.get('reservation_id')}")

    @action("charge_card", depends_on=["reserve_funds"])
    async def charge_card(self, ctx: dict) -> dict:
        logger.info(f"  ✓ Charging ${ctx.get('amount', 0):.2f} to card")
        await asyncio.sleep(0.02)
        return {"charge_id": "CHG-1"}

    @compensate("charge_card", compensation_type=CompensationType.SEMANTIC)
    async def refund_card(self, ctx: dict) -> None:
        logger.info(
            f"  ↩ [SEMANTIC] Issuing refund for charge {ctx.get('charge_id')} "
            f"(refund ≠ simple delete)"
        )

    @action("send_receipt", depends_on=["charge_card"])
    async def send_receipt(self, ctx: dict) -> dict:
        msg = "Email service unavailable!"
        raise RuntimeError(msg)

    @compensate("send_receipt")
    async def void_receipt(self, ctx: dict) -> None:
        logger.info("  ↩ Voiding receipt (nothing sent)")


# ============================================================================
# 2. Pivot saga — shows irreversible step + forward recovery
# ============================================================================


class TradeSaga(Saga):
    """
    Four-step trade saga with a pivot:
      validate_order   → regular step
      submit_to_exchange (pivot=True) → irreversible once done
      update_portfolio → deliberately fails AFTER the pivot
      confirm_trade    → never reached

    When update_portfolio fails, normal rollback cannot undo the exchange
    submission. The @forward_recovery handler kicks in instead.
    """

    saga_name = "trade-pivot"

    @action("validate_order")
    async def validate_order(self, ctx: dict) -> dict:
        logger.info("  ✓ Validating trade order")
        await asyncio.sleep(0.02)
        return {"trade_id": ctx.get("trade_id", "TRD-1"), "validated": True}

    @compensate("validate_order")
    async def undo_validation(self, ctx: dict) -> None:
        logger.info("  ↩ Undoing trade validation")

    @action("submit_to_exchange", depends_on=["validate_order"], pivot=True)
    async def submit_to_exchange(self, ctx: dict) -> dict:
        logger.info("  ✓ [PIVOT] Submitting order to exchange — IRREVERSIBLE")
        await asyncio.sleep(0.03)
        return {"exchange_ref": "EXC-42"}

    @compensate("submit_to_exchange")
    async def cancel_exchange_order(self, ctx: dict) -> None:
        logger.info("  ↩ Cannot fully undo exchange submission (pivot)")

    @action("update_portfolio", depends_on=["submit_to_exchange"])
    async def update_portfolio(self, ctx: dict) -> dict:
        msg = "Portfolio service timeout!"
        raise RuntimeError(msg)

    @compensate("update_portfolio")
    async def revert_portfolio(self, ctx: dict) -> None:
        logger.info("  ↩ Reverting portfolio update")

    @forward_recovery("update_portfolio")
    async def recover_portfolio(self, ctx: dict, error: Exception) -> RecoveryAction:
        logger.info(f"  ⚡ [FORWARD RECOVERY] update_portfolio failed: {error}")
        logger.info("  ⚡ Decision: SKIP this step and continue (will reconcile later)")
        return RecoveryAction.SKIP

    @action("confirm_trade", depends_on=["update_portfolio"])
    async def confirm_trade(self, ctx: dict) -> dict:
        logger.info("  ✓ Confirming trade")
        return {"confirmed": True}

    @compensate("confirm_trade")
    async def void_confirmation(self, ctx: dict) -> None:
        logger.info("  ↩ Voiding trade confirmation")


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    # --- Phase 1: Mechanical + Semantic compensation -------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — Mechanical and semantic compensation types")
    print("=" * 60)

    saga = PaymentSaga()
    try:
        await saga.run({"customer_id": "CUST-1"})
    except Exception as exc:
        print(f"\n  Saga raised: {type(exc).__name__}: {exc}")
        print("  Both MECHANICAL and SEMANTIC compensations ran automatically.")

    # --- Phase 2: Pivot + Forward Recovery -----------------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — Pivot step with forward recovery")
    print("=" * 60)

    trade = TradeSaga()
    try:
        result = await trade.run({"trade_id": "TRD-1"})
        print(f"\n  Result keys: {sorted(result.keys())}")
    except Exception as exc:
        print(f"\n  Saga raised: {type(exc).__name__}: {exc}")
        print("  Forward recovery handler was invoked for the post-pivot failure.")

    print("\n" + "=" * 60)
    print("Done — compensation deep-dive demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
