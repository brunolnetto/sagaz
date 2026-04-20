"""Tests for orchestration_config demonstration modules."""

import asyncio
from unittest.mock import patch

import pytest


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


def test_orchestrator_main():
    with patch(
        "sagaz.demonstrations.orchestration_config.orchestrator.main.asyncio.run"
    ) as mock_run:
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


@pytest.mark.asyncio
async def test_storage_backends_run_function():
    from sagaz.demonstrations.orchestration_config.storage_backends.main import _run

    await _run()


def test_storage_backends_main():
    with patch(
        "sagaz.demonstrations.orchestration_config.storage_backends.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.orchestration_config.storage_backends.main import main

        main()
        mock_run.assert_called_once()
