#!/usr/bin/env python3
"""
Time-Travel Example - Query Historical Saga State

Demonstrates retrieving saga state at any point in history for auditing.

Usage:
    python -m sagaz.examples.replay.time_travel
"""

import asyncio
import logging
from datetime import datetime, timedelta
from uuid import UUID

from sagaz.core.context import SagaContext
from sagaz.core.replay import ReplayConfig, SnapshotStrategy
from sagaz.core.saga import Saga
from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class SimpleWorkflowSaga(Saga):
    """Simple 3-step workflow for time-travel demonstration."""

    async def build(self):
        await self.add_step("step_1", self.step_1)
        await self.add_step("step_2", self.step_2)
        await self.add_step("step_3", self.step_3)

    async def step_1(self, ctx: SagaContext) -> dict:
        await asyncio.sleep(0.05)
        return {"step_1_result": "completed"}

    async def step_2(self, ctx: SagaContext) -> dict:
        await asyncio.sleep(0.05)
        return {"step_2_result": "completed"}

    async def step_3(self, ctx: SagaContext) -> dict:
        await asyncio.sleep(0.05)
        return {"step_3_result": "completed"}


async def main():
    """Demonstrate time-travel queries."""

    snapshot_storage = InMemorySnapshotStorage()

    replay_config = ReplayConfig(
        enable_snapshots=True, snapshot_strategy=SnapshotStrategy.AFTER_EACH_STEP, retention_days=30
    )

    # Execute saga with snapshot capture
    saga = SimpleWorkflowSaga(
        name="workflow", replay_config=replay_config, snapshot_storage=snapshot_storage
    )

    saga.context.set("workflow_id", "WF-12345")
    saga.context.set("initiated_by", "user@example.com")

    await saga.build()
    start_time = datetime.now()
    await saga.execute()
    end_time = datetime.now()

    saga_id = saga.saga_id

    # Query snapshots

    snapshots = await snapshot_storage.list_snapshots(saga_id=saga_id)

    for _i, _snapshot in enumerate(snapshots, 1):
        pass

    # Query state at specific time
    start_time + (end_time - start_time) / 2

    midpoint_snapshot = await snapshot_storage.get_latest_snapshot(
        saga_id=saga_id,
        before_step=None,  # Get latest before midpoint_time
    )

    if midpoint_snapshot:
        pass


if __name__ == "__main__":
    asyncio.run(main())
