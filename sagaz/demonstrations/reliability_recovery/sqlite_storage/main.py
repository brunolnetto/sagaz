#!/usr/bin/env python3
"""
SQLite Storage — embedded saga state persistence for local development

Demonstrates SQLiteSagaStorage: a zero-infrastructure persistent backend
that uses an on-disk SQLite file (or ':memory:') — no Docker, no external
service required.

Phases:
  1. Execute three order sagas (two succeed, one fails) with a file-based
     SQLite database.
  2. Open a second storage connection to the same file — simulating a
     process restart — and load each saga back by ID.
  3. Query all persisted records with status filtering.
  4. Demonstrate ':memory:' usage: state is isolated to the connection and
     lost when it closes (useful for integration tests).

Prerequisites:
    pip install aiosqlite

Usage:
    sagaz demo run sqlite_storage
    python -m sagaz.demonstrations.reliability_recovery.sqlite_storage.main
"""

import asyncio
import logging
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sagaz.demo.sqlite_storage")


# ---------------------------------------------------------------------------
# Minimal saga helpers (imperative API to avoid re-importing SagaConfig)
# ---------------------------------------------------------------------------


async def _run_order(order_id: str, fail: bool = False) -> tuple[str, object]:
    """Execute an order saga and return (saga_id, result)."""
    from sagaz.core.saga import Saga, SagaContext
    from sagaz.core.types import SagaStatus

    async def validate(ctx: SagaContext):
        return {"valid": True}

    async def cancel_validate(result: dict, ctx: SagaContext):
        pass

    async def charge(ctx: SagaContext):
        if fail:
            msg = "Card declined"
            raise RuntimeError(msg)
        return {"charge_id": f"CHG-{order_id}"}

    async def refund(result: dict, ctx: SagaContext):
        pass  # pragma: no cover

    saga = Saga(name="order")
    await saga.add_step("validate", validate, cancel_validate)
    await saga.add_step("charge", charge, refund)
    result = await saga.execute()
    return saga.saga_id, result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _run() -> None:
    try:
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStatus
    except ImportError as exc:
        print(f"\n  Missing dependency: {exc}")
        print("  Install with: pip install aiosqlite")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "demo_sagas.db")

        # ----------------------------------------------------------------
        # Phase 1: execute sagas and persist state
        # ----------------------------------------------------------------
        print("\n" + "=" * 60)
        print("Phase 1 — Execute sagas and persist state to SQLite")
        print("=" * 60)

        saved_ids: list[tuple[str, str, SagaStatus]] = []  # (saga_id, order_id, status)

        async with SQLiteSagaStorage(db_path) as storage:
            for order_id, should_fail in [("ORD-1", False), ("ORD-2", False), ("ORD-3", True)]:
                saga_id, result = await _run_order(order_id, fail=should_fail)
                status = result.status
                print(f"\n  {order_id}  saga_id={saga_id[:8]}…  status={status.value}")

                await storage.save_saga_state(
                    saga_id=saga_id,
                    saga_name="order",
                    status=status,
                    steps=[],
                    context={"order_id": order_id},
                )
                saved_ids.append((saga_id, order_id, status))

            print(f"\n  {len(saved_ids)} sagas written to {db_path}")

        # ----------------------------------------------------------------
        # Phase 2: simulate restart — new connection to same file
        # ----------------------------------------------------------------
        print("\n" + "=" * 60)
        print("Phase 2 — Simulate restart: reload state from same file")
        print("=" * 60)

        async with SQLiteSagaStorage(db_path) as storage2:
            for saga_id, order_id, original_status in saved_ids:
                record = await storage2.load_saga_state(saga_id)
                if record:
                    loaded_status = record.get("status")
                    match = "✓" if str(loaded_status) in str(original_status.value) else "✗"
                    print(f"\n  {match} {order_id}  loaded status={loaded_status}")
                else:
                    print(f"\n  ✗ {order_id}  not found (unexpected)")

            # ----------------------------------------------------------------
            # Phase 3: list with status filter
            # ----------------------------------------------------------------
            print("\n" + "=" * 60)
            print("Phase 3 — List sagas by status")
            print("=" * 60)

            all_sagas = await storage2.list_sagas()
            print(f"\n  All sagas: {len(all_sagas)}")

            for status_filter in (SagaStatus.COMPLETED, SagaStatus.ROLLED_BACK):
                filtered = await storage2.list_sagas(status=status_filter)
                print(f"  Status={status_filter.value}: {len(filtered)} saga(s)")

        # ----------------------------------------------------------------
        # Phase 4: in-memory isolation
        # ----------------------------------------------------------------
        print("\n" + "=" * 60)
        print("Phase 4 — In-memory storage (isolated, test-friendly)")
        print("=" * 60)

        first_saga_id, _, _ = saved_ids[0]

        async with SQLiteSagaStorage(":memory:") as mem:
            # The on-disk saga should NOT appear here
            record = await mem.load_saga_state(first_saga_id)
            isolated = record is None
            print(f"\n  In-memory is isolated from on-disk file: {isolated}")

            # Write a fresh saga
            await mem.save_saga_state(
                saga_id="test-123",
                saga_name="test",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )
            all_mem = await mem.list_sagas()
            print(f"  In-memory sagas after one write: {len(all_mem)}")

    print("\n" + "=" * 60)
    print("Done — SQLite storage demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
