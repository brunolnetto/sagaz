#!/usr/bin/env python3
"""Simple Replay Demo - Minimal Example"""

import asyncio

from sagaz.core.context import SagaContext
from sagaz.core.exceptions import SagaStepError
from sagaz.core.replay import ReplayConfig, SnapshotStrategy
from sagaz.core.saga import Saga
from sagaz.core.saga_replay import SagaReplay
from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage


class ThreeStepSaga(Saga):
    """Simple saga: step1 → step2 (fails) → step3"""

    async def build(self):
        await self.add_step("step1", self.step1)
        await self.add_step("step2", self.step2)
        await self.add_step("step3", self.step3)

    async def step1(self, ctx: SagaContext) -> dict:
        return {"data": "from_step1"}

    async def step2(self, ctx: SagaContext) -> dict:
        if ctx.get("should_fail", True):
            msg = "Step 2 intentional failure"
            raise SagaStepError(msg)
        return {"data": "from_step2"}

    async def step3(self, ctx: SagaContext) -> dict:
        return {"data": "from_step3"}


async def main():
    """Run simple replay demo."""

    # Setup
    storage = InMemorySnapshotStorage()
    config = ReplayConfig(
        enable_snapshots=True, snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP
    )

    # Phase 1: Initial failure
    saga = ThreeStepSaga(replay_config=config, snapshot_storage=storage)
    saga.context.set("should_fail", True)
    await saga.build()

    failed_id = saga.saga_id
    try:
        await saga.execute()
    except Exception:
        pass

    # Phase 2: Replay with fix
    from uuid import UUID

    replay = SagaReplay(
        saga_id=UUID(failed_id),  # Convert string to UUID
        snapshot_storage=storage,
        saga_factory=lambda name: ThreeStepSaga(replay_config=config, snapshot_storage=storage),
    )

    await replay.from_checkpoint(
        step_name="step1",  # Replay from step1 (last successful snapshot)
        context_override={"should_fail": False},
    )


if __name__ == "__main__":
    asyncio.run(main())
