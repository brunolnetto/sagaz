#!/usr/bin/env python3
"""Time-Travel Demo - Query historical saga state for auditing"""

import asyncio
import logging
from datetime import UTC, datetime

from sagaz import ReplayConfig, Saga, SagaConfig, SnapshotStrategy, action
from sagaz.core.decorators._snapshots import snapshot_saga_id
from sagaz.core.replay.time_travel import SagaTimeTravel
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class SimpleWorkflowSaga(Saga):
    """Simple 3-step workflow for time-travel demonstration."""

    saga_name = "workflow"

    @action("step_1")
    async def step_1(self, ctx: dict) -> dict:
        await asyncio.sleep(0.05)
        return {"step_1_result": "completed"}

    @action("step_2", depends_on=["step_1"])
    async def step_2(self, ctx: dict) -> dict:
        await asyncio.sleep(0.05)
        return {"step_2_result": "completed"}

    @action("step_3", depends_on=["step_2"])
    async def step_3(self, ctx: dict) -> dict:
        await asyncio.sleep(0.05)
        return {"step_3_result": "completed"}


async def main() -> None:
    """Demonstrate time-travel queries."""

    snapshot_storage = InMemorySnapshotStorage()
    config = SagaConfig(
        replay_config=ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.AFTER_EACH_STEP,
            retention_days=30,
        ),
        snapshot_storage=snapshot_storage,
        metrics=False,
        logging=False,
    )

    # Execute saga with snapshot capture
    start_time = datetime.now(UTC)
    context = await SimpleWorkflowSaga(config=config).run(
        {"workflow_id": "WF-12345", "initiated_by": "user@example.com"}, saga_id="WF-12345"
    )
    end_time = datetime.now(UTC)

    # Query snapshots: they are stored under the saga id's UUID
    saga_id = snapshot_saga_id(context["saga_id"])
    snapshots = await snapshot_storage.list_snapshots(saga_id=saga_id)
    logger.info(f"{len(snapshots)} snapshots of saga {context['saga_id']!r}:")
    for snapshot in sorted(snapshots, key=lambda s: s.created_at):
        logger.info(f"  after {snapshot.step_name}: completed={snapshot.completed_steps}")

    # Query state at a specific time: halfway through the run
    midpoint = start_time + (end_time - start_time) / 2
    state = await SagaTimeTravel("WF-12345", snapshot_storage).get_state_at(midpoint)
    if state:
        logger.info(f"At the midpoint, the saga had completed {state.completed_steps}")
    else:
        logger.info("At the midpoint, no step had completed yet")


if __name__ == "__main__":
    asyncio.run(main())
