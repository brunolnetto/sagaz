#!/usr/bin/env python3
"""
PostgreSQL Storage — saga state persistence and crash recovery

Demonstrates how PostgreSQL-backed storage allows a saga to survive
process restarts by re-loading its persisted state.

Phases:
  1. Spin up a PostgreSQL container (testcontainers) and configure storage.
  2. Execute an order saga that succeeds — state is saved to PostgreSQL.
  3. Execute a payment saga that fails mid-way — rolled-back state is saved.
  4. Simulate a "process restart": create a fresh storage client pointing at
     the same database and load both sagas back by their saga IDs.
  5. Query all stored sagas and display a status summary.

This is the canonical pattern for crash recovery: whatever state the saga
reaches before a crash is retrievable from PostgreSQL on the next start.

Prerequisites:
    Docker (for testcontainers PostgreSQL).
    Install testcontainers: pip install testcontainers

Usage:
    sagaz demo run postgres_storage
    python -m sagaz.demonstrations.reliability_recovery.postgres_storage.main
"""

import asyncio
import logging

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sagaz.demo.postgres_storage")


# ---------------------------------------------------------------------------
# Saga definitions
# ---------------------------------------------------------------------------


async def _build_order_saga(storage, order_id: str):
    from sagaz import Saga, SagaConfig, action, compensate, configure

    configure(SagaConfig(storage=storage))

    class OrderSaga(Saga):
        saga_name = "order"

        @action("validate")
        async def validate(self, ctx: dict) -> dict:
            return {"order_id": ctx["order_id"], "valid": True}

        @compensate("validate")
        async def cancel_validate(self, ctx: dict) -> None:
            pass

        @action("reserve", depends_on=["validate"])
        async def reserve(self, ctx: dict) -> dict:
            return {"reserved": True}

        @compensate("reserve")
        async def release_reserve(self, ctx: dict) -> None:
            pass

        @action("charge", depends_on=["reserve"])
        async def charge(self, ctx: dict) -> dict:
            return {"charge_id": "CHG-1"}

        @compensate("charge")
        async def refund(self, ctx: dict) -> None:
            pass

    return OrderSaga()


async def _build_failing_saga(storage, order_id: str):
    from sagaz import Saga, SagaConfig, action, compensate, configure

    configure(SagaConfig(storage=storage))

    class FailingPaymentSaga(Saga):
        saga_name = "failing-payment"

        @action("authorise")
        async def authorise(self, ctx: dict) -> dict:
            return {"authorised": True}

        @compensate("authorise")
        async def void_auth(self, ctx: dict) -> None:
            pass

        @action("capture", depends_on=["authorise"])
        async def capture(self, ctx: dict) -> dict:
            msg = "Gateway timeout"
            raise RuntimeError(msg)

        @compensate("capture")
        async def void_capture(self, ctx: dict) -> None:
            pass

    return FailingPaymentSaga()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _run() -> None:
    try:
        from sagaz.demonstrations.utils import ServiceManager
    except ImportError as exc:
        print(f"\n  Missing utility: {exc}")
        return

    print("\n" + "=" * 60)
    print("Phase 1 — Starting PostgreSQL container")
    print("=" * 60)

    try:
        with ServiceManager(postgres=True) as svc:
            from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

            async with PostgreSQLSagaStorage(svc.postgres_url) as storage:
                # -------------------------------------------------------
                # Phase 2: successful saga
                # -------------------------------------------------------
                print("\n" + "=" * 60)
                print("Phase 2 — Execute and persist a successful saga")
                print("=" * 60)

                success_saga = await _build_order_saga(storage, "ORD-100")
                result = await success_saga.run({"order_id": "ORD-100"})
                success_id = success_saga.saga_id
                print(f"\n  Saga {success_id} → {result.get('status', 'unknown')}")

                # Persist manually so we can load it back below
                await storage.save_saga_state(
                    saga_id=success_id,
                    saga_name="order",
                    status=__import__(
                        "sagaz.core.types", fromlist=["SagaStatus"]
                    ).SagaStatus.COMPLETED,
                    steps=[],
                    context={"order_id": "ORD-100"},
                )
                print(f"  State persisted for {success_id}.")

                # -------------------------------------------------------
                # Phase 3: failing saga
                # -------------------------------------------------------
                print("\n" + "=" * 60)
                print("Phase 3 — Execute and persist a rolled-back saga")
                print("=" * 60)

                from sagaz.core.types import SagaStatus

                failing_saga = await _build_failing_saga(storage, "ORD-101")
                try:
                    await failing_saga.run({"order_id": "ORD-101"})
                except Exception:
                    pass
                failing_id = failing_saga.saga_id
                print(f"\n  Saga {failing_id} → rolled back (expected)")
                await storage.save_saga_state(
                    saga_id=failing_id,
                    saga_name="failing-payment",
                    status=SagaStatus.ROLLED_BACK,
                    steps=[],
                    context={"order_id": "ORD-101"},
                )
                print(f"  State persisted for {failing_id}.")

            # ---------------------------------------------------------------
            # Phase 4: "process restart" — new storage client, same database
            # ---------------------------------------------------------------
            print("\n" + "=" * 60)
            print("Phase 4 — Simulate restart: load saga state from PostgreSQL")
            print("=" * 60)

            async with PostgreSQLSagaStorage(svc.postgres_url) as fresh_storage:
                for label, saga_id in [("successful", success_id), ("rolled-back", failing_id)]:
                    record = await fresh_storage.load_saga_state(saga_id)
                    if record:
                        print(
                            f"\n  Loaded {label} saga {saga_id[:8]}…"
                            f"  name={record.get('saga_name')}  status={record.get('status')}"
                        )
                    else:
                        print(f"\n  WARNING: could not load {label} saga {saga_id}")

                # -------------------------------------------------------
                # Phase 5: list all persisted sagas
                # -------------------------------------------------------
                print("\n" + "=" * 60)
                print("Phase 5 — List all persisted sagas")
                print("=" * 60)

                all_sagas = await fresh_storage.list_sagas()
                print(f"\n  Total sagas in database: {len(all_sagas)}")
                for saga in all_sagas:
                    print(
                        f"    {saga.get('saga_id', '')[:8]}…  "
                        f"{saga.get('saga_name', ''):<20}  {saga.get('status', '')}"
                    )

    except Exception as exc:
        print(f"\n  Skipping — {type(exc).__name__}: {exc}")
        print("  Ensure Docker is running and testcontainers is installed.")
        return

    print("\n" + "=" * 60)
    print("Done — PostgreSQL storage demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
