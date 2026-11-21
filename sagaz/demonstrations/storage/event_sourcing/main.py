#!/usr/bin/env python3
"""
Event sourcing: a saga's full history, and its state rebuilt from it (#57)

An order saga opts in to event sourcing, so every state change is appended to
an event store instead of overwriting one record:

  1. Setup   → an in-memory event store; ``OrderSaga.Meta`` opts in, with a
               snapshot every 4 events
  2. Execute → order-1001 completes; order-1002's payment is declined, so the
               saga compensates the stock reservation
  3. Verify  → each saga's events are numbered 1..n with unique ids; replaying
               them gives the same state as the snapshot + tail load; replaying
               only the first events shows the saga as it was mid-run

Everything runs in-process; no external services are required. In production,
use ``event_store = "postgresql://..."`` and ``sagaz event-log <saga-id>``.

Usage:
    sagaz demo run event_sourcing
    python -m sagaz.demonstrations.storage.event_sourcing.main
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.events import SagaEvent
from sagaz.core.exceptions import SagaFailedError
from sagaz.core.storage.event_store import InMemoryEventStore, SagaEventStore
from sagaz.projections import SagaSummaryProjection, build_projection, load_projection

COMPLETED_ORDER, DECLINED_ORDER = "order-1001", "order-1002"
CARD_LIMIT = 100


def order_saga(store: SagaEventStore) -> Saga:
    """An order saga recording its events in *store*."""

    class OrderSaga(Saga):
        saga_name = "order"

        class Meta:
            storage_strategy = "event_sourced"
            event_store = store
            snapshot_threshold = 4

        @action("reserve_stock")
        async def reserve_stock(self, ctx: dict[str, Any]) -> dict[str, str]:
            return {"reservation": f"rsv-{ctx['order_id']}"}

        @compensate("reserve_stock")
        async def release_stock(self, ctx: dict[str, Any]) -> None:
            return None

        @action("charge_card", depends_on=["reserve_stock"])
        async def charge_card(self, ctx: dict[str, Any]) -> dict[str, str]:
            if ctx["amount"] > CARD_LIMIT:
                msg = "card declined"
                raise ValueError(msg)
            return {"charge": f"ch-{ctx['order_id']}"}

        @action("ship", depends_on=["charge_card"])
        async def ship(self, ctx: dict[str, Any]) -> dict[str, str]:
            return {"tracking": f"trk-{ctx['order_id']}"}

    return OrderSaga(config=SagaConfig(metrics=False, logging=False))


@dataclass
class Demo:
    store: SagaEventStore = field(default_factory=InMemoryEventStore)
    outcomes: dict[str, str] = field(default_factory=dict)


async def execute(demo: Demo) -> None:
    """Run one order that completes and one whose payment is declined."""
    for order_id, amount in ((COMPLETED_ORDER, 40), (DECLINED_ORDER, 500)):
        try:
            await order_saga(demo.store).run({"order_id": order_id, "amount": amount}, order_id)
            demo.outcomes[order_id] = "completed"
        except SagaFailedError as error:
            demo.outcomes[order_id] = f"rolled back ({error.__cause__})"


def as_of(saga_id: str, events: list[SagaEvent], sequence: int) -> SagaSummaryProjection:
    """The saga's state right after event *sequence* (time travel)."""
    return build_projection(saga_id, [e for e in events if e.sequence <= sequence])


async def _stream_problems(store: SagaEventStore, saga_id: str) -> list[str]:
    events = await store.load_stream(saga_id)
    problems = []
    if [e.sequence for e in events] != list(range(1, len(events) + 1)):
        problems.append(f"{saga_id}: sequences are not 1..n")
    if len({e.event_id for e in events}) != len(events):
        problems.append(f"{saga_id}: duplicate event ids")
    replayed = build_projection(saga_id, events)
    loaded = await load_projection(store, saga_id)
    if loaded != replayed:
        problems.append(f"{saga_id}: snapshot + tail differs from a full replay")
    if await store.load_latest_snapshot(saga_id) is None:
        problems.append(f"{saga_id}: no snapshot was taken")
    return problems


async def verify(demo: Demo) -> list[str]:
    """Return the event-sourcing guarantees that do not hold (empty when all hold)."""
    problems = [
        *await _stream_problems(demo.store, COMPLETED_ORDER),
        *await _stream_problems(demo.store, DECLINED_ORDER),
    ]
    expected = {COMPLETED_ORDER: "completed", DECLINED_ORDER: "rolled_back"}
    for saga_id, status in expected.items():
        state = await load_projection(demo.store, saga_id)
        if state is None or state.status != status:
            problems.append(f"{saga_id}: expected {status}")
    declined = await demo.store.load_stream(DECLINED_ORDER)
    if as_of(DECLINED_ORDER, declined, 2).status != "executing":
        problems.append(f"{DECLINED_ORDER}: the mid-run state was not executing")
    return problems


async def _timeline(store: SagaEventStore, saga_id: str) -> None:
    state = await load_projection(store, saga_id)
    assert state is not None
    print(f"\n  {saga_id} → {state.status}")
    for event in await store.load_stream(saga_id):
        step = event.payload.get("step_name") or event.payload.get("failed_step") or ""
        print(f"    {event.sequence:>2}  {event.event_type:<20} {step}".rstrip())


async def _run() -> None:
    # Phase 1: Setup
    demo = Demo()
    print("📜 OrderSaga opts in: Meta.storage_strategy = 'event_sourced' (snapshot every 4)")

    # Phase 2: Execute
    await execute(demo)
    for order_id, outcome in demo.outcomes.items():
        print(f"  ▶ {order_id}: {outcome}")
    for order_id in demo.outcomes:
        await _timeline(demo.store, order_id)

    # Phase 3: Verify
    declined = await demo.store.load_stream(DECLINED_ORDER)
    mid_run = as_of(DECLINED_ORDER, declined, 2)
    reserve = mid_run.steps["reserve_stock"].status
    print(f"\n  ⏪ {DECLINED_ORDER} as of event 2: {mid_run.status}, reserve_stock {reserve}")
    problems = await verify(demo)
    print()
    if problems:
        for problem in problems:
            print(f"❌ {problem}")
        msg = "event sourcing guarantees did not hold"
        raise RuntimeError(msg)
    print("✅ Full history kept; replay, snapshot + tail and time travel agree")


if __name__ == "__main__":
    asyncio.run(_run())
