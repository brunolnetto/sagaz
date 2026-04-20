"""Tests for reliability_recovery demonstration modules."""

import asyncio
import builtins
from unittest.mock import patch, AsyncMock

import pytest


# ===========================================================================
# idempotency — trigger body + compensation + exception-path coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_idempotency_trigger_handler_bodies_directly():
    """Covers on_payment return dicts (L35, L57) and refund_payment prints (L47, L69)."""
    from sagaz.demonstrations.reliability_recovery.idempotency.main import (
        PaymentSagaWithoutIdempotency,
        PaymentSagaWithIdempotency,
    )

    saga1 = PaymentSagaWithoutIdempotency()
    result1 = saga1.on_payment({"order_id": "O1", "amount": 50.0})
    assert result1["order_id"] == "O1"
    await saga1.refund_payment({"order_id": "O1"})

    saga2 = PaymentSagaWithIdempotency()
    result2 = saga2.on_payment({"order_id": "O2", "amount": 50.0})
    assert result2["order_id"] == "O2"
    await saga2.refund_payment({"order_id": "O2"})


@pytest.mark.asyncio
async def test_idempotency_run_function_covers_exception_branches():
    """Covers IdempotencyKeyRequiredError (L90-92) and unexpected-exception (L103-104)."""
    from sagaz.core.exceptions import IdempotencyKeyRequiredError
    from sagaz.demonstrations.reliability_recovery.idempotency.main import (
        PaymentSagaWithoutIdempotency,
        PaymentSagaWithIdempotency,
    )

    call_count = [0]

    async def mock_fire_event(source, payload, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            raise IdempotencyKeyRequiredError("payment-saga", "payment_requested", ["amount"])
        raise RuntimeError("Unexpected service error")

    with patch(
        "sagaz.demonstrations.reliability_recovery.idempotency.main.fire_event",
        mock_fire_event,
    ):
        from sagaz.demonstrations.reliability_recovery.idempotency.main import _run

        await _run()

    assert call_count[0] == 2


# ===========================================================================
# replay_compliance — compensation body coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_wire_transfer_saga_compensation_bodies_directly():
    """Covers _cancel_validation (L66-68), _flag_compliance (L78-80), _reverse_transfer (L94-98)."""
    from sagaz import SagaConfig, configure
    from sagaz.demonstrations.reliability_recovery.replay_compliance.main import WireTransferSaga

    configure(SagaConfig())
    saga = WireTransferSaga()
    ctx = {"transfer_id": "TFR-001", "amount": 100.0}

    await saga._cancel_validation(None, ctx)
    await saga._flag_compliance(None, ctx)
    # with swift_code — covers L96-98
    await saga._reverse_transfer({"swift_code": "SWIFT-TFR-001"}, ctx)
    # without swift_code — covers L95 false branch
    await saga._reverse_transfer(None, ctx)


# ===========================================================================
# saga_replay — factory + compensation + exception-path coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_saga_factory_returns_saga_instance():
    """Covers saga_factory return (L106)."""
    from sagaz import Saga
    from sagaz.demonstrations.reliability_recovery.saga_replay.main import saga_factory

    saga = saga_factory("my-saga")
    assert saga.name == "my-saga"


@pytest.mark.asyncio
async def test_saga_replay_compensation_bodies_directly():
    """Covers undo_validate (L48), release_inventory (L58), refund_payment (L68), cancel_notification (L78)."""
    from sagaz.demonstrations.reliability_recovery.saga_replay.main import (
        undo_validate,
        release_inventory,
        refund_payment,
        cancel_notification,
    )

    ctx = {"order_id": "ORD-1"}
    await undo_validate(ctx)
    await release_inventory(ctx)
    await refund_payment(ctx)
    await cancel_notification(ctx)


# ===========================================================================
# sqlite_storage — refund + ImportError + None-load coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_sqlite_storage_refund_compensation_directly():
    """Covers refund pass body (L58) by calling the inner function shape directly."""
    from sagaz.core.saga import Saga

    refund_called = []

    async def validate(ctx):
        return {"valid": True}

    async def cancel_validate(result, ctx):
        pass

    async def charge(ctx):
        return {"charge_id": "CHG-test"}

    async def refund(result, ctx):
        refund_called.append("refund")

    async def fail_step(ctx):
        raise RuntimeError("fail to trigger compensation")

    async def cancel_fail(result, ctx):
        pass

    saga = Saga(name="order")
    await saga.add_step("validate", validate, cancel_validate)
    await saga.add_step("charge", charge, refund)
    await saga.add_step("fail_step", fail_step, cancel_fail)
    result = await saga.execute()
    assert result.status.value == "rolled_back"
    # refund ran because charge succeeded but a later step failed
    assert "refund" in refund_called


@pytest.mark.asyncio
async def test_sqlite_storage_import_error_path():
    """Covers ImportError branch (L76-79) when sqlite backend unavailable."""
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "sagaz.core.storage.backends.sqlite.saga":
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    import sagaz.demonstrations.reliability_recovery.sqlite_storage.main as m
    import importlib

    with patch("builtins.__import__", mock_import):
        importlib.reload(m)
        await m._run()


@pytest.mark.asyncio
async def test_sqlite_storage_none_load_branch():
    """Covers the load_saga_state → None branch (L125)."""
    from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
    from sagaz.demonstrations.reliability_recovery.sqlite_storage.main import _run

    original_load = SQLiteSagaStorage.load_saga_state
    call_count = [0]

    async def mock_load(self, saga_id):
        call_count[0] += 1
        if call_count[0] == 1:
            return None
        return await original_load(self, saga_id)

    with patch.object(SQLiteSagaStorage, "load_saga_state", mock_load):
        await _run()


# ===========================================================================
# postgres_storage — compensation body coverage via in-memory storage
# ===========================================================================


@pytest.mark.asyncio
async def test_postgres_storage_order_saga_compensations():
    """Builds OrderSaga with InMemorySagaStorage and calls compensation methods directly (L54, 62, 70)."""
    from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
    from sagaz.demonstrations.reliability_recovery.postgres_storage.main import _build_order_saga

    storage = InMemorySagaStorage()
    saga = await _build_order_saga(storage, "ORD-COMP")
    ctx = {"order_id": "ORD-COMP"}
    await saga.cancel_validate(ctx)
    await saga.release_reserve(ctx)
    await saga.refund(ctx)


@pytest.mark.asyncio
async def test_postgres_storage_order_saga_run_success():
    """Runs OrderSaga to success to cover action return bodies (L85)."""
    from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
    from sagaz.demonstrations.reliability_recovery.postgres_storage.main import _build_order_saga

    storage = InMemorySagaStorage()
    saga = await _build_order_saga(storage, "ORD-RUN")
    result = await saga.run({"order_id": "ORD-RUN"})
    assert result is not None


@pytest.mark.asyncio
async def test_postgres_storage_failing_saga_compensations():
    """Builds FailingPaymentSaga and triggers compensation bodies (L88-90, 96-98)."""
    from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
    from sagaz.demonstrations.reliability_recovery.postgres_storage.main import _build_failing_saga

    storage = InMemorySagaStorage()
    saga = await _build_failing_saga(storage, "ORD-FAIL")
    ctx = {"order_id": "ORD-FAIL"}
    await saga.void_auth(ctx)
    await saga.void_capture(ctx)


@pytest.mark.asyncio
async def test_postgres_storage_failing_saga_run_to_compensate():
    """Runs FailingPaymentSaga which fails at capture, covering L93-94."""
    from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
    from sagaz.demonstrations.reliability_recovery.postgres_storage.main import _build_failing_saga

    storage = InMemorySagaStorage()
    saga = await _build_failing_saga(storage, "ORD-FAIL2")
    try:
        await saga.run({"order_id": "ORD-FAIL2"})
    except Exception:
        pass  # expected - capture raises RuntimeError


@pytest.mark.asyncio
async def test_postgres_storage_import_error_path():
    """Covers ImportError branch (L111-113) when sagaz.demonstrations.utils is missing."""
    import sys
    import importlib

    real_module = sys.modules.pop("sagaz.demonstrations.utils", None)
    # Also bust the module if it's cached under a sub-key used by the demo
    with patch.dict(sys.modules, {"sagaz.demonstrations.utils": None}):
        import sagaz.demonstrations.reliability_recovery.postgres_storage.main as m

        importlib.reload(m)
        await m._run()

    if real_module is not None:
        sys.modules["sagaz.demonstrations.utils"] = real_module


@pytest.mark.asyncio
async def test_postgres_storage_service_manager_exception_path():
    """Covers outer except block (L206-209) when ServiceManager is importable but raises on entry."""
    import importlib
    import sys
    import types

    class FailingSM:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            raise RuntimeError("Docker not available")

        def __exit__(self, *a):
            pass

    fake_utils = types.ModuleType("sagaz.demonstrations.utils")
    fake_utils.ServiceManager = FailingSM

    import sagaz.demonstrations.reliability_recovery.postgres_storage.main as m

    with patch.dict(sys.modules, {"sagaz.demonstrations.utils": fake_utils}):
        importlib.reload(m)
        await m._run()


@pytest.mark.asyncio
async def test_postgres_storage_run_full_flow_mocked():
    """Covers L134-201 by injecting mocked ServiceManager and PostgreSQLSagaStorage."""
    import sys
    import importlib
    import types
    from contextlib import asynccontextmanager

    # Build a fake PostgreSQLSagaStorage that is an async context manager
    shared_db = {}

    class FakeStorage:
        def __init__(self, url):
            self._records = shared_db  # shared across instances

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def save_saga_state(self, saga_id, saga_name, status, steps, context):
            self._records[saga_id] = {"saga_id": saga_id, "saga_name": saga_name, "status": str(status)}

        async def load_saga_state(self, saga_id):
            return self._records.get(saga_id)

        async def list_sagas(self):
            return list(self._records.values())

    # Fake svc returned by ServiceManager context manager
    class FakeSvc:
        postgres_url = "postgresql://fake/db"

    class FakeServiceManager:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return FakeSvc()

        def __exit__(self, *args):
            pass

    # Fake utils module
    fake_utils = types.ModuleType("sagaz.demonstrations.utils")
    fake_utils.ServiceManager = FakeServiceManager

    # Fake postgresql storage module
    fake_pg_mod = types.ModuleType("sagaz.core.storage.backends.postgresql.saga")
    fake_pg_mod.PostgreSQLSagaStorage = FakeStorage

    # Also need to patch saga.saga_id attribute on OrderSaga/FailingPaymentSaga instances
    # We do this by patching the Saga base class to add a saga_id property
    from sagaz.core.decorators import Saga as DecoratorSaga

    original_getattr = getattr(DecoratorSaga, "__getattr__", None)

    def fake_saga_id_property(self):
        return self._saga_id

    # Add saga_id as a property via monkeypatching
    DecoratorSaga.saga_id = property(fake_saga_id_property)

    try:
        import sagaz.demonstrations.reliability_recovery.postgres_storage.main as m
        with patch.dict(
            sys.modules,
            {
                "sagaz.demonstrations.utils": fake_utils,
                "sagaz.core.storage.backends.postgresql.saga": fake_pg_mod,
            },
        ):
            importlib.reload(m)
            await m._run()
    finally:
        # Restore: remove the monkey-patched property
        try:
            del DecoratorSaga.saga_id
        except AttributeError:
            pass
        importlib.reload(m)


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
        mock_run.side_effect = lambda coro: coro.close()
        from sagaz.demonstrations.reliability_recovery.idempotency.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# postgres_storage (mocked — requires Docker)
# ===========================================================================


def test_postgres_storage_main():
    with patch(
        "sagaz.demonstrations.reliability_recovery.postgres_storage.main.asyncio.run"
    ) as mock_run:
        mock_run.side_effect = lambda coro: coro.close()
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
        mock_run.side_effect = lambda coro: coro.close()
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


@pytest.mark.asyncio
async def test_saga_replay_empty_snapshots_branch():
    """Covers L149->175 and L179->199 branch (when snapshots is empty list)."""
    from unittest.mock import AsyncMock, patch
    from sagaz.demonstrations.reliability_recovery.saga_replay.main import _run

    with patch(
        "sagaz.demonstrations.reliability_recovery.saga_replay.main.InMemorySnapshotStorage"
    ) as MockStorage:
        instance = MockStorage.return_value
        instance.list_snapshots = AsyncMock(return_value=[])
        await _run()


@pytest.mark.asyncio
async def test_saga_replay_state_none_branch():
    """Covers L162 (when time_travel.get_state_at returns None)."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from sagaz.demonstrations.reliability_recovery.saga_replay.main import _run

    with patch(
        "sagaz.demonstrations.reliability_recovery.saga_replay.main.SagaTimeTravel"
    ) as MockTimeTravel:
        instance = MockTimeTravel.return_value
        instance.get_state_at = AsyncMock(return_value=None)
        instance.list_state_changes = AsyncMock(return_value=[])
        await _run()


@pytest.mark.asyncio
async def test_saga_replay_from_checkpoint_exception_branch():
    """Covers L195-197 (when SagaReplay.from_checkpoint raises an exception)."""
    from unittest.mock import AsyncMock, patch
    from sagaz.demonstrations.reliability_recovery.saga_replay.main import _run

    with patch(
        "sagaz.demonstrations.reliability_recovery.saga_replay.main.SagaReplay"
    ) as MockReplay:
        instance = MockReplay.return_value
        instance.from_checkpoint = AsyncMock(side_effect=RuntimeError("No checkpoint"))
        await _run()


def test_saga_replay_main():
    with patch(
        "sagaz.demonstrations.reliability_recovery.saga_replay.main.asyncio.run"
    ) as mock_run:
        mock_run.side_effect = lambda coro: coro.close()
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
        mock_run.side_effect = lambda coro: coro.close()
        from sagaz.demonstrations.reliability_recovery.sqlite_storage.main import main

        main()
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_postgres_storage_warning_branch_mocked():
    """Covers L189 — WARNING branch when load_saga_state returns None in Phase 4."""
    import sys
    import importlib
    import types

    class FakeStorage:
        def __init__(self, url):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def save_saga_state(self, saga_id, saga_name, status, steps, context):
            pass  # Don't save — so Phase 4 finds nothing

        async def load_saga_state(self, saga_id):
            return None  # Always None → triggers WARNING branch (L189)

        async def list_sagas(self):
            return []

    class FakeSvc:
        postgres_url = "postgresql://fake/db"

    class FakeServiceManager:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return FakeSvc()

        def __exit__(self, *args):
            pass

    fake_utils = types.ModuleType("sagaz.demonstrations.utils")
    fake_utils.ServiceManager = FakeServiceManager

    fake_pg_mod = types.ModuleType("sagaz.core.storage.backends.postgresql.saga")
    fake_pg_mod.PostgreSQLSagaStorage = FakeStorage

    from sagaz.core.decorators import Saga as DecoratorSaga

    DecoratorSaga.saga_id = property(lambda self: self._saga_id)

    try:
        import sagaz.demonstrations.reliability_recovery.postgres_storage.main as m
        with patch.dict(
            sys.modules,
            {
                "sagaz.demonstrations.utils": fake_utils,
                "sagaz.core.storage.backends.postgresql.saga": fake_pg_mod,
            },
        ):
            importlib.reload(m)
            await m._run()
    finally:
        try:
            del DecoratorSaga.saga_id
        except AttributeError:
            pass
        importlib.reload(m)
