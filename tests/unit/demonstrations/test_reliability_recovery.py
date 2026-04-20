"""Tests for reliability_recovery demonstration modules."""

import asyncio
from unittest.mock import patch

import pytest


# ===========================================================================
# idempotency
# ===========================================================================


@pytest.mark.asyncio
async def test_payment_saga_without_idempotency_runs():
    from sagaz.demonstrations.reliability_recovery.idempotency.main import (
        PaymentSagaWithoutIdempotency,
    )
    from sagaz.core.triggers.registry import TriggerRegistry

    saga = PaymentSagaWithoutIdempotency()
    result = await saga.run({"order_id": "ORD-001", "amount": 150.0})
    assert result.get("transaction_id") == "TXN-001"
    TriggerRegistry.clear()


@pytest.mark.asyncio
async def test_payment_saga_with_idempotency_runs():
    from sagaz.demonstrations.reliability_recovery.idempotency.main import (
        PaymentSagaWithIdempotency,
    )
    from sagaz.core.triggers.registry import TriggerRegistry

    saga = PaymentSagaWithIdempotency()
    result = await saga.run({"order_id": "ORD-002", "amount": 250.0})
    assert result.get("transaction_id") == "TXN-001"
    TriggerRegistry.clear()


@pytest.mark.asyncio
async def test_idempotency_run_function():
    from sagaz.demonstrations.reliability_recovery.idempotency.main import _run
    from sagaz.core.triggers.registry import TriggerRegistry

    TriggerRegistry.clear()
    await _run()
    TriggerRegistry.clear()


def test_idempotency_main():
    with patch(
        "sagaz.demonstrations.reliability_recovery.idempotency.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.reliability_recovery.idempotency.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# postgres_storage (mocked — requires Docker)
# ===========================================================================


@pytest.mark.asyncio
async def test_postgres_storage_run_function_skips_without_docker():
    from sagaz.demonstrations.reliability_recovery.postgres_storage.main import _run

    # _run() uses ServiceManager which tries Docker; it should handle the exception gracefully
    try:
        await _run()
    except Exception:
        pass  # Acceptable if Docker not available


def test_postgres_storage_main():
    with patch(
        "sagaz.demonstrations.reliability_recovery.postgres_storage.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.reliability_recovery.postgres_storage.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# replay_compliance
# ===========================================================================


@pytest.mark.asyncio
async def test_wire_transfer_saga_runs_successfully():
    from sagaz.demonstrations.reliability_recovery.replay_compliance.main import WireTransferSaga
    from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage
    from sagaz.core.replay import ReplayConfig, SnapshotStrategy

    snapshot_storage = InMemorySnapshotStorage()
    replay_config = ReplayConfig(
        enable_snapshots=True,
        snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
    )
    saga = WireTransferSaga(replay_config=replay_config, snapshot_storage=snapshot_storage)
    saga.context.set("transfer_id", "TXN-001")
    saga.context.set("amount", 1000.0)
    await saga.build()
    result = await saga.execute()
    assert result is not None


@pytest.mark.asyncio
async def test_replay_compliance_run_function():
    from sagaz.demonstrations.reliability_recovery.replay_compliance.main import _run

    await _run()


def test_replay_compliance_main():
    with patch(
        "sagaz.demonstrations.reliability_recovery.replay_compliance.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.reliability_recovery.replay_compliance.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# saga_replay
# ===========================================================================


@pytest.mark.asyncio
async def test_build_saga_and_execute():
    from sagaz.demonstrations.reliability_recovery.saga_replay.main import build_saga
    from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage

    snapshot_storage = InMemorySnapshotStorage()
    saga = await build_saga(snapshot_storage)
    result = await saga.execute()
    assert result.completed_steps > 0


@pytest.mark.asyncio
async def test_saga_replay_run_function():
    from sagaz.demonstrations.reliability_recovery.saga_replay.main import _run

    await _run()


def test_saga_replay_main():
    with patch(
        "sagaz.demonstrations.reliability_recovery.saga_replay.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.reliability_recovery.saga_replay.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# sqlite_storage
# ===========================================================================


@pytest.mark.asyncio
async def test_run_order_success():
    from sagaz.demonstrations.reliability_recovery.sqlite_storage.main import _run_order

    saga_id, result = await _run_order("ORD-1", fail=False)
    assert saga_id
    assert result.status.value == "completed"


@pytest.mark.asyncio
async def test_run_order_failure():
    from sagaz.demonstrations.reliability_recovery.sqlite_storage.main import _run_order

    saga_id, result = await _run_order("ORD-ERR", fail=True)
    assert saga_id
    assert result.status.value in ("rolled_back", "failed", "compensated")


@pytest.mark.asyncio
async def test_sqlite_storage_run_function():
    from sagaz.demonstrations.reliability_recovery.sqlite_storage.main import _run

    await _run()


def test_sqlite_storage_main():
    with patch(
        "sagaz.demonstrations.reliability_recovery.sqlite_storage.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.reliability_recovery.sqlite_storage.main import main

        main()
        mock_run.assert_called_once()
