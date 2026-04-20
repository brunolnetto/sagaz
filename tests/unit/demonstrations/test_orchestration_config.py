"""Tests for orchestration_config demonstration modules."""

import asyncio
from unittest.mock import patch, AsyncMock

import pytest


# ===========================================================================
# event_triggers — trigger handler body + compensation + registry loop coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_order_saga_trigger_handler_body():
    """Covers the on_order_created return dict (L46)."""
    from sagaz import SagaConfig, configure
    from sagaz.demonstrations.orchestration_config.event_triggers.main import OrderSaga

    configure(SagaConfig())
    saga = OrderSaga()
    result = saga.on_order_created({"order_id": "ORD-T", "customer": "Alice", "amount": 25.0})
    assert result["order_id"] == "ORD-T"


@pytest.mark.asyncio
async def test_notification_saga_on_webhook_no_notify_returns_none():
    """Covers NotificationSaga.on_webhook when notify is absent → returns None (L81-83)."""
    from sagaz.demonstrations.orchestration_config.event_triggers.main import NotificationSaga

    saga = NotificationSaga()
    assert saga.on_webhook({"order_id": "ORD-T"}) is None
    # Also cover the notify=True branch
    result = saga.on_webhook({"order_id": "ORD-T", "notify": True})
    assert result["channel"] == "email"


@pytest.mark.asyncio
async def test_event_triggers_compensation_bodies_directly():
    """Covers undo_validate (L60), undo_process (L70), unsend (L93)."""
    from sagaz.demonstrations.orchestration_config.event_triggers.main import (
        OrderSaga,
        NotificationSaga,
    )

    order = OrderSaga()
    await order.undo_validate({"order_id": "ORD-T"})
    await order.undo_process({"order_id": "ORD-T"})

    notif = NotificationSaga()
    await notif.unsend({})


@pytest.mark.asyncio
async def test_event_triggers_run_function_with_registry_populated():
    """Covers the TriggerRegistry print loop (L111-112) by ensuring registry is populated."""
    import importlib
    from sagaz.core.triggers.registry import TriggerRegistry

    TriggerRegistry.clear()
    import sagaz.demonstrations.orchestration_config.event_triggers.main as mod

    importlib.reload(mod)
    await mod._run()
    TriggerRegistry.clear()


# ===========================================================================
# storage_backends — compensation bodies + None-return + exception paths
# ===========================================================================


@pytest.mark.asyncio
async def test_storage_backends_cancel_order_and_refund_payment_directly():
    """Covers cancel_order (L41) and refund_payment (L49) pass bodies."""
    from sagaz.demonstrations.orchestration_config.storage_backends.main import (
        cancel_order,
        refund_payment,
    )

    ctx = {"order_id": "ORD-1"}
    await cancel_order(ctx)
    await refund_payment(ctx)


@pytest.mark.asyncio
async def test_storage_backends_test_storage_none_return(tmp_path):
    """Covers the load_saga_state → None branch (L84)."""
    from sagaz.demonstrations.orchestration_config.storage_backends.main import test_storage
    from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage

    storage = InMemorySagaStorage()

    async def return_none(saga_id):
        return None

    storage.load_saga_state = return_none
    await test_storage("Memory-None", storage)


@pytest.mark.asyncio
async def test_storage_backends_redis_exception_path():
    """Covers the Redis except block (L114-115) by injecting a failing ServiceManager into sys.modules."""
    import sys
    import importlib
    from unittest.mock import MagicMock

    fake_utils = MagicMock()
    fake_utils.ServiceManager = MagicMock(side_effect=RuntimeError("No Redis"))

    with patch.dict(sys.modules, {"sagaz.demonstrations.utils": fake_utils}):
        import sagaz.demonstrations.orchestration_config.storage_backends.main as m

        importlib.reload(m)
        await m._run()


@pytest.mark.asyncio
async def test_storage_backends_postgres_exception_path():
    """Covers the PostgreSQL except block (L130-131) by making the second ServiceManager call fail."""
    import sys
    import importlib
    from unittest.mock import MagicMock

    call_count = [0]

    def make_sm(*args, **kwargs):
        call_count[0] += 1
        raise RuntimeError("No Postgres")

    fake_utils = MagicMock()
    fake_utils.ServiceManager = make_sm

    with patch.dict(sys.modules, {"sagaz.demonstrations.utils": fake_utils}):
        import sagaz.demonstrations.orchestration_config.storage_backends.main as m

        importlib.reload(m)
        await m._run()


# ===========================================================================
# event_triggers
# ===========================================================================


@pytest.mark.asyncio
async def test_order_saga_trigger_success():
    from sagaz import SagaConfig, configure
    from sagaz.demonstrations.orchestration_config.event_triggers.main import OrderSaga
    from sagaz.core.triggers.registry import TriggerRegistry

    configure(SagaConfig())
    saga = OrderSaga()
    result = await saga.run({"order_id": "ORD-T1", "amount": 50.0})
    assert result.get("validated") is True
    TriggerRegistry.clear()


@pytest.mark.asyncio
async def test_notification_saga_trigger_with_notify():
    from sagaz.demonstrations.orchestration_config.event_triggers.main import NotificationSaga
    from sagaz.core.triggers.registry import TriggerRegistry

    saga = NotificationSaga()
    result = await saga.run({"order_id": "ORD-N1", "channel": "email"})
    assert result.get("sent") is True
    TriggerRegistry.clear()


@pytest.mark.asyncio
async def test_event_triggers_run_function():
    from sagaz.demonstrations.orchestration_config.event_triggers.main import _run

    await _run()


def test_event_triggers_main():
    with patch(
        "sagaz.demonstrations.orchestration_config.event_triggers.main.asyncio.run"
    ) as mock_run:
        mock_run.side_effect = lambda coro: coro.close()
        from sagaz.demonstrations.orchestration_config.event_triggers.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# orchestrator
# ===========================================================================


@pytest.mark.asyncio
async def test_create_saga_success():
    from sagaz.demonstrations.orchestration_config.orchestrator.main import create_saga

    saga = await create_saga("ITEM-001", should_fail=False)
    result = await saga.execute()
    assert result.status.value in ("completed",)


@pytest.mark.asyncio
async def test_create_saga_failure():
    from sagaz.demonstrations.orchestration_config.orchestrator.main import create_saga

    saga = await create_saga("ITEM-002", should_fail=True)
    result = await saga.execute()
    assert result.status.value in ("rolled_back", "failed", "compensated")


@pytest.mark.asyncio
async def test_orchestrator_run_function():
    from sagaz.demonstrations.orchestration_config.orchestrator.main import _run

    await _run()


@pytest.mark.asyncio
async def test_orchestrator_cancel_shipment_directly():
    """Covers L56 — cancel_shipment logger.info body (compensation for ship step)."""
    from sagaz.demonstrations.orchestration_config.orchestrator.main import cancel_shipment
    from sagaz.core.saga import SagaContext

    ctx = SagaContext()
    ctx.set("item_id", "ITEM-001")
    await cancel_shipment({"shipped": True}, ctx)


@pytest.mark.asyncio
async def test_orchestrator_exception_in_results():
    """Covers L103 — exception branch when execute_saga raises an exception."""
    from unittest.mock import AsyncMock, patch

    from sagaz.demonstrations.orchestration_config.orchestrator.main import _run

    async def fake_execute_saga_raises(saga):
        raise RuntimeError("Orchestrator internal failure")

    fake_stats = {
        "total_sagas": 1,
        "completed": 0,
        "rolled_back": 0,
        "failed": 1,
        "executing": 0,
        "pending": 0,
    }

    with patch(
        "sagaz.demonstrations.orchestration_config.orchestrator.main.SagaOrchestrator"
    ) as MockOrch:
        instance = MockOrch.return_value
        instance.execute_saga = fake_execute_saga_raises
        instance.get_statistics = AsyncMock(return_value=fake_stats)
        await _run()


def test_orchestrator_main():
    with patch(
        "sagaz.demonstrations.orchestration_config.orchestrator.main.asyncio.run"
    ) as mock_run:
        mock_run.side_effect = lambda coro: coro.close()
        from sagaz.demonstrations.orchestration_config.orchestrator.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# storage_backends
# ===========================================================================


@pytest.mark.asyncio
async def test_storage_backends_in_memory():
    from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
    from sagaz.demonstrations.orchestration_config.storage_backends.main import test_storage

    storage = InMemorySagaStorage()
    await test_storage("Memory-test", storage)


def test_storage_backends_main():
    with patch(
        "sagaz.demonstrations.orchestration_config.storage_backends.main.asyncio.run"
    ) as mock_run:
        mock_run.side_effect = lambda coro: coro.close()
        from sagaz.demonstrations.orchestration_config.storage_backends.main import main

        main()
        mock_run.assert_called_once()
