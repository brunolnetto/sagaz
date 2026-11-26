#!/usr/bin/env python3
"""Simple Replay Demo - Minimal Example"""

import asyncio
import logging

from sagaz import (
    ReplayConfig,
    Saga,
    SagaConfig,
    SagaFailedError,
    SagaStepError,
    SnapshotStrategy,
    action,
)
from sagaz.core.replay.saga_replay import SagaReplay
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class ThreeStepSaga(Saga):
    """Simple saga: step1 → step2 (fails) → step3"""

    saga_name = "three-steps"

    @action("step1")
    async def step1(self, ctx: dict) -> dict:
        return {"from_step1": "done"}

    @action("step2", depends_on=["step1"], max_retries=0)
    async def step2(self, ctx: dict) -> dict:
        if ctx.get("should_fail", True):
            msg = "Step 2 intentional failure"
            raise SagaStepError(msg)
        return {"from_step2": "done"}

    @action("step3", depends_on=["step2"])
    async def step3(self, ctx: dict) -> dict:
        return {"from_step3": "done"}


async def main() -> None:
    """Run simple replay demo."""

    # Setup: a snapshot before each step, kept in memory
    storage = InMemorySnapshotStorage()
    config = SagaConfig(
        replay_config=ReplayConfig(
            enable_snapshots=True, snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP
        ),
        snapshot_storage=storage,
        metrics=False,
        logging=False,
    )

    # Phase 1: Initial failure
    try:
        await ThreeStepSaga(config=config).run({"should_fail": True}, saga_id="demo-run")
    except SagaFailedError as failure:
        logger.info(f"Phase 1: the saga failed at {failure.failed_step!r} ({failure.status.value})")

    # Phase 2: Replay from the failed step, with the cause fixed
    replay = SagaReplay(
        "demo-run",  # the run that failed
        storage,
        saga_factory=lambda name: ThreeStepSaga(config=config),
    )
    result = await replay.from_checkpoint(
        step_name="step2",  # step1 completed: it is adopted, not run again
        context_override={"should_fail": False},
    )
    logger.info(f"Phase 2: replay {result.replay_status.value} as new saga {result.new_saga_id}")


if __name__ == "__main__":
    asyncio.run(main())
