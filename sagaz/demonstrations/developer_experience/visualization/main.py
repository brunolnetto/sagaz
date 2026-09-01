#!/usr/bin/env python3
"""
Visualization — Mermaid flowchart generation from saga definitions

Builds a non-trivial 6-step DAG saga and calls saga.to_mermaid() to
produce renderable Mermaid diagrams.  Shows both the default view and
a highlighted trail after a simulated execution.

No external infrastructure required — runs fully in-memory.

Usage:
    sagaz demo run visualization
    python -m sagaz.demonstrations.visualization.main
"""

import asyncio
import logging

from sagaz import Saga, action, compensate

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.visualization")


# ============================================================================
# A 6-step DAG saga
# ============================================================================


class FulfillmentSaga(Saga):
    """Order fulfillment with parallel warehouse and payment branches."""

    saga_name = "fulfillment"

    @action("validate_order")
    async def validate_order(self, ctx: dict) -> dict:
        return {"valid": True}

    @compensate("validate_order")
    async def undo_validate(self, ctx: dict) -> None:
        pass

    @action("reserve_inventory", depends_on=["validate_order"])
    async def reserve_inventory(self, ctx: dict) -> dict:
        return {"reservation_id": "RES-1"}

    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: dict) -> None:
        pass

    @action("authorize_payment", depends_on=["validate_order"])
    async def authorize_payment(self, ctx: dict) -> dict:
        return {"auth_id": "AUTH-1"}

    @compensate("authorize_payment")
    async def void_payment(self, ctx: dict) -> None:
        pass

    @action("check_fraud", depends_on=["validate_order"])
    async def check_fraud(self, ctx: dict) -> dict:
        return {"fraud_clear": True}

    @compensate("check_fraud")
    async def void_fraud(self, ctx: dict) -> None:
        pass

    @action("capture_payment", depends_on=["authorize_payment", "check_fraud"])
    async def capture_payment(self, ctx: dict) -> dict:
        return {"capture_id": "CAP-1"}

    @compensate("capture_payment")
    async def refund_payment(self, ctx: dict) -> None:
        pass

    @action("ship_order", depends_on=["reserve_inventory", "capture_payment"])
    async def ship_order(self, ctx: dict) -> dict:
        return {"tracking": "TRK-001"}

    @compensate("ship_order")
    async def cancel_shipment(self, ctx: dict) -> None:
        pass


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    saga = FulfillmentSaga()

    # --- Phase 1: Default diagram (full graph with compensations) ------------
    print("\n" + "=" * 60)
    print("Phase 1 — Full Mermaid diagram (forward + compensation)")
    print("=" * 60 + "\n")

    diagram = saga.to_mermaid(direction="TB", show_compensation=True)
    print(diagram)

    # --- Phase 2: Diagram without compensation nodes -------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — Forward-only diagram (no compensation nodes)")
    print("=" * 60 + "\n")

    diagram_fwd = saga.to_mermaid(direction="LR", show_compensation=False)
    print(diagram_fwd)

    # --- Phase 3: Highlighted trail (simulated partial execution) ------------
    print("\n" + "=" * 60)
    print("Phase 3 — Highlighted execution trail")
    print("=" * 60)
    print("  Scenario: steps completed up to capture_payment, then ship_order failed")
    print("  Compensation ran for capture_payment, authorize_payment, check_fraud,")
    print("  reserve_inventory, validate_order.\n")

    trail = {
        "completed_steps": [
            "validate_order",
            "reserve_inventory",
            "authorize_payment",
            "check_fraud",
            "capture_payment",
        ],
        "failed_step": "ship_order",
        "compensated_steps": [
            "capture_payment",
            "authorize_payment",
            "check_fraud",
            "reserve_inventory",
            "validate_order",
        ],
    }

    diagram_trail = saga.to_mermaid(
        direction="TB",
        show_compensation=True,
        highlight_trail=trail,
    )
    print(diagram_trail)

    print("=" * 60)
    print("Done — visualization demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
