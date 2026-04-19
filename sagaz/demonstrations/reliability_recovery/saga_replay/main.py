#!/usr/bin/env python3
"""
Saga Replay — snapshot capture and time-travel queries

Demonstrates:
  1. Automatic snapshot capture with SnapshotStrategy.BEFORE_EACH_STEP
  2. Inspecting snapshots after execution via InMemorySnapshotStorage
  3. SagaTimeTravel — querying historical saga state at a point in time
  4. SagaReplay — replaying a saga from a checkpoint with context override

Uses the imperative Saga API with InMemorySnapshotStorage. No external
infrastructure required.

Usage:
    sagaz demo run saga_replay
    python -m sagaz.demonstrations.saga_replay.main
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sagaz.core.replay import ReplayConfig, SnapshotStrategy
from sagaz.core.replay.saga_replay import SagaReplay
from sagaz.core.replay.time_travel import SagaTimeTravel
from sagaz.core.saga import Saga, SagaContext
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.saga_replay")


# ============================================================================
# Step functions
# ============================================================================


async def validate_order(ctx: SagaContext) -> dict:
    logger.info("  ✓ Validating order")
    await asyncio.sleep(0.02)
    return {"validated": True, "order_id": ctx.get("order_id", "ORD-1")}


async def undo_validate(ctx: SagaContext) -> None:
    logger.info("  ↩ Undoing validation")


async def reserve_inventory(ctx: SagaContext) -> dict:
    logger.info("  ✓ Reserving inventory")
    await asyncio.sleep(0.02)
    return {"reservation_id": "RSRV-1"}


async def release_inventory(ctx: SagaContext) -> None:
    logger.info("  ↩ Releasing inventory")


async def charge_payment(ctx: SagaContext) -> dict:
    logger.info("  ✓ Charging payment")
    await asyncio.sleep(0.02)
    return {"charge_id": "CHG-1"}


async def refund_payment(ctx: SagaContext) -> None:
    logger.info("  ↩ Refunding payment")


async def send_notification(ctx: SagaContext) -> dict:
    logger.info("  ✓ Sending notification")
    await asyncio.sleep(0.02)
    return {"notified": True}


async def cancel_notification(ctx: SagaContext) -> None:
    logger.info("  ↩ Cancelling notification")


# ============================================================================
# Helpers
# ============================================================================


async def build_saga(snapshot_storage: InMemorySnapshotStorage) -> Saga:
    replay_config = ReplayConfig(
        enable_snapshots=True,
        snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
    )
    saga = Saga(
        name="order-replay",
        replay_config=replay_config,
        snapshot_storage=snapshot_storage,
    )
    await saga.add_step("validate_order", validate_order, undo_validate)
    await saga.add_step("reserve_inventory", reserve_inventory, release_inventory)
    await saga.add_step("charge_payment", charge_payment, refund_payment)
    await saga.add_step("send_notification", send_notification, cancel_notification)
    return saga


def saga_factory(saga_name: str) -> Saga:
    """Factory used by SagaReplay to create a fresh saga instance."""
    # Steps will be added during replay setup (replay engine re-adds them)
    return Saga(name=saga_name)


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    snapshot_storage = InMemorySnapshotStorage()

    # --- Phase 1: Execute and capture snapshots ------------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — Execute saga with snapshot capture")
    print("=" * 60)

    saga = await build_saga(snapshot_storage)
    saga_id = UUID(saga.saga_id)
    result = await saga.execute()

    print(f"\n  Status:          {result.status.value}")
    print(f"  Completed steps: {result.completed_steps}/{result.total_steps}")
    print(f"  Saga ID:         {saga_id}")

    # --- Phase 2: List captured snapshots ------------------------------------
    print("\n" + "=" * 60)
    print("Phase 2 — Inspect captured snapshots")
    print("=" * 60)

    snapshots = await snapshot_storage.list_snapshots(saga_id)
    print(f"\n  Total snapshots captured: {len(snapshots)}")
    for snap in snapshots:
        print(
            f"    [{snap.step_index}] {snap.step_name:<25} "
            f"status={snap.status:<12} "
            f"completed={snap.completed_steps}"
        )

    # --- Phase 3: Time-travel query ------------------------------------------
    print("\n" + "=" * 60)
    print("Phase 3 — Time-travel: query historical state")
    print("=" * 60)

    if snapshots:
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=snapshot_storage)

        # Query state at a time after the saga completed
        query_time = datetime.now(UTC) + timedelta(seconds=1)
        state = await time_travel.get_state_at(timestamp=query_time)
        if state:
            print(f"\n  State at {query_time.strftime('%H:%M:%S')} UTC:")
            print(f"    Status:          {state.status}")
            print(f"    Current step:    {state.current_step}")
            print(f"    Completed steps: {state.completed_steps}")
            print(f"    Context keys:    {sorted(state.context.keys())}")
        else:
            print("\n  No state found at queried time.")

        # List all state changes
        changes = await time_travel.list_state_changes()
        print(f"\n  State change timeline ({len(changes)} entries):")
        for change in changes:
            print(
                f"    {change.timestamp.strftime('%H:%M:%S.%f')[:-3]} "
                f"step={change.current_step:<25} "
                f"completed={change.completed_steps}"
            )

    # --- Phase 4: Replay from checkpoint (dry_run) ---------------------------
    print("\n" + "=" * 60)
    print("Phase 4 — Replay from checkpoint (dry-run)")
    print("=" * 60)

    if snapshots:
        replay = SagaReplay(
            saga_id=saga_id,
            snapshot_storage=snapshot_storage,
            saga_factory=saga_factory,
        )
        try:
            replay_result = await replay.from_checkpoint(
                step_name="charge_payment",
                context_override={"payment_token": "NEW-TOKEN"},
                dry_run=True,
            )
            print(f"\n  Replay status:    {replay_result.replay_status}")
            print(f"  Checkpoint step:  {replay_result.checkpoint_step}")
            print(f"  Original saga ID: {replay_result.original_saga_id}")
            print(f"  New saga ID:      {replay_result.new_saga_id}")
        except Exception as exc:
            print(f"\n  Replay error: {type(exc).__name__}: {exc}")
            print("  (This is expected if no snapshot exists at that exact checkpoint)")

    print("\n" + "=" * 60)
    print("Done — saga replay demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
