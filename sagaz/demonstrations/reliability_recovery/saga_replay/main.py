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

from sagaz import ReplayConfig, Saga, SagaConfig, SnapshotStrategy
from sagaz.core.decorators._snapshots import snapshot_saga_id
from sagaz.core.replay.saga_replay import SagaReplay
from sagaz.core.replay.time_travel import SagaTimeTravel
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.saga_replay")


# ============================================================================
# Step functions
# ============================================================================


async def validate_order(ctx: dict) -> dict:
    logger.info("  ✓ Validating order")
    await asyncio.sleep(0.02)
    return {"validated": True, "order_id": ctx.get("order_id", "ORD-1")}


async def undo_validate(ctx: dict) -> None:
    logger.info("  ↩ Undoing validation")


async def reserve_inventory(ctx: dict) -> dict:
    logger.info("  ✓ Reserving inventory")
    await asyncio.sleep(0.02)
    return {"reservation_id": "RSRV-1"}


async def release_inventory(ctx: dict) -> None:
    logger.info("  ↩ Releasing inventory")


async def charge_payment(ctx: dict) -> dict:
    logger.info("  ✓ Charging payment")
    await asyncio.sleep(0.02)
    return {"charge_id": "CHG-1"}


async def refund_payment(ctx: dict) -> None:
    logger.info("  ↩ Refunding payment")


async def send_notification(ctx: dict) -> dict:
    logger.info("  ✓ Sending notification")
    await asyncio.sleep(0.02)
    return {"notified": True}


async def cancel_notification(ctx: dict) -> None:
    logger.info("  ↩ Cancelling notification")


# ============================================================================
# Helpers
# ============================================================================


def build_saga(snapshot_storage: InMemorySnapshotStorage, name: str = "order-replay") -> Saga:
    """The order saga, saving a snapshot before each step to *snapshot_storage*."""
    config = SagaConfig(
        replay_config=ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
        ),
        snapshot_storage=snapshot_storage,
        metrics=False,
        logging=False,
    )
    saga = Saga(config=config)
    saga.saga_name = name
    saga.add_step("validate_order", validate_order, undo_validate)
    saga.add_step(
        "reserve_inventory", reserve_inventory, release_inventory, depends_on=["validate_order"]
    )
    saga.add_step(
        "charge_payment", charge_payment, refund_payment, depends_on=["reserve_inventory"]
    )
    saga.add_step(
        "send_notification", send_notification, cancel_notification, depends_on=["charge_payment"]
    )
    return saga


def saga_factory(saga_name: str, snapshot_storage: InMemorySnapshotStorage | None = None) -> Saga:
    """Factory used by SagaReplay: the same saga, with the same steps, to run again."""
    return build_saga(snapshot_storage or InMemorySnapshotStorage(), saga_name)


# ============================================================================
# Runner
# ============================================================================


async def _run() -> None:
    snapshot_storage = InMemorySnapshotStorage()

    # --- Phase 1: Execute and capture snapshots ------------------------------
    print("\n" + "=" * 60)
    print("Phase 1 — Execute saga with snapshot capture")
    print("=" * 60)

    context = await build_saga(snapshot_storage).run({"order_id": "ORD-1"})
    saga_id = snapshot_saga_id(context["saga_id"])  # snapshots are stored under a UUID

    print("\n  Status:          completed")
    print(f"  Notified:        {context['notified']}")
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
            saga_factory=lambda name: saga_factory(name, snapshot_storage),
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
