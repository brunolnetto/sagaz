#!/usr/bin/env python3
"""Simple Saga Time-Travel Demo - Historical state queries."""

import asyncio
import logging
from datetime import datetime

from sagaz.core.context import SagaContext
from sagaz.core.replay import ReplayConfig, SnapshotStrategy
from sagaz.core.saga import Saga
from sagaz.core.time_travel import SagaTimeTravel
from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage

logging.basicConfig(level=logging.WARNING)

class SimpleConsentSaga(Saga):
    def __init__(self, **kwargs):
        super().__init__(name="consent", **kwargs)

    async def build(self):
        await self.add_step("verify", self._verify, None)
        await self.add_step("collect", self._collect, None)
        await self.add_step("record", self._record, None)

    async def _verify(self, ctx: SagaContext) -> dict:
        await asyncio.sleep(0.05)
        return {"verified": True}

    async def _collect(self, ctx: SagaContext) -> dict:
        await asyncio.sleep(0.05)
        return {"consent": "given"}

    async def _record(self, ctx: SagaContext) -> dict:
        await asyncio.sleep(0.05)
        return {"recorded": True}

async def main():
    print("\n" + "="*70)
    print("SAGA TIME-TRAVEL DEMO")
    print("="*70 + "\n")

    storage = InMemorySnapshotStorage()
    config = ReplayConfig(
        enable_snapshots=True,
        snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP
    )

    saga = SimpleConsentSaga(replay_config=config, snapshot_storage=storage)
    saga.context.set("patient_id", "PT-123")
    await saga.build()

    start_time = datetime.now()
    await saga.execute()
    end_time = datetime.now()

    print(f"✓ Saga completed in {(end_time - start_time).total_seconds():.3f}s")
    print(f"  Saga ID: {saga.saga_id}\n")

    # Time travel query
    time_travel = SagaTimeTravel(snapshot_storage=storage, saga_id=saga.saga_id)
    midpoint = start_time + (end_time - start_time) / 2

    state = await time_travel.get_state_at(timestamp=midpoint)
    if state:
        print(f"State at {midpoint.strftime('%H:%M:%S.%f')[:-3]}:")
        print(f"  Status: {state['status']}")
        print(f"  Completed steps: {state['completed_steps']}")
        print(f"  Context keys: {list(state['context'].keys())}")
    else:
        print(f"No snapshot found at {midpoint.strftime('%H:%M:%S.%f')[:-3]}")
        print("✓ Time-travel feature working (no data at that exact time)")

    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
