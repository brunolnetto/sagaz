"""Tests for schema_evolution demonstration modules."""

import asyncio
from unittest.mock import patch

import pytest


# ===========================================================================
# context_migration
# ===========================================================================


def test_get_schema_version_default():
    from sagaz.demonstrations.schema_evolution.context_migration.main import get_schema_version

    assert get_schema_version({}) == 1
    assert get_schema_version({"_schema_version": 2}) == 2


def test_migrate_v1_to_v2_string_customer():
    from sagaz.demonstrations.schema_evolution.context_migration.main import migrate_v1_to_v2

    ctx = {"customer": "Alice", "_schema_version": 1}
    migrated = migrate_v1_to_v2(ctx)
    assert migrated["customer"] == {"name": "Alice", "email": "unknown@example.com"}
    assert migrated["_schema_version"] == 2


def test_migrate_v1_to_v2_already_dict():
    from sagaz.demonstrations.schema_evolution.context_migration.main import migrate_v1_to_v2

    ctx = {"customer": {"name": "Bob", "email": "bob@example.com"}, "_schema_version": 1}
    migrated = migrate_v1_to_v2(ctx)
    assert migrated["customer"] == {"name": "Bob", "email": "bob@example.com"}


def test_migrate_context_v1_to_v2():
    from sagaz.demonstrations.schema_evolution.context_migration.main import migrate_context

    ctx = {"customer": "Carol", "_schema_version": 1}
    result = migrate_context(ctx)
    assert result["_schema_version"] == 2
    assert isinstance(result["customer"], dict)


def test_migrate_context_already_current():
    from sagaz.demonstrations.schema_evolution.context_migration.main import migrate_context

    ctx = {"customer": {"name": "Dave"}, "_schema_version": 2}
    result = migrate_context(ctx)
    assert result == ctx


@pytest.mark.asyncio
async def test_order_saga_v1_runs():
    from sagaz.demonstrations.schema_evolution.context_migration.main import OrderSagaV1

    saga = OrderSagaV1()
    result = await saga.run({"customer": "Alice", "_schema_version": 1})
    assert result.get("email_sent") is True


@pytest.mark.asyncio
async def test_order_saga_v2_runs():
    from sagaz.demonstrations.schema_evolution.context_migration.main import OrderSagaV2

    saga = OrderSagaV2()
    ctx = {"customer": {"name": "Alice", "email": "alice@example.com"}, "_schema_version": 2}
    result = await saga.run(ctx)
    assert result.get("email_sent") is True


@pytest.mark.asyncio
async def test_context_migration_run_function():
    from sagaz.demonstrations.schema_evolution.context_migration.main import _run

    await _run()


def test_context_migration_main():
    with patch(
        "sagaz.demonstrations.schema_evolution.context_migration.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.schema_evolution.context_migration.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# step_versioning
# ===========================================================================


@pytest.mark.asyncio
async def test_order_saga_v1_step_versioning():
    from sagaz.demonstrations.schema_evolution.step_versioning.main import OrderSagaV1

    result = await OrderSagaV1().run({"customer": "Alice", "amount": 50.0})
    assert result.get("_step_schema") == "v1"
    assert result.get("notified") is True


@pytest.mark.asyncio
async def test_order_saga_v2_step_versioning():
    from sagaz.demonstrations.schema_evolution.step_versioning.main import OrderSagaV2

    result = await OrderSagaV2().run({"customer": "Bob", "amount": 75.0})
    assert result.get("_step_schema") == "v2"
    assert result.get("loyalty_points") == 42


@pytest.mark.asyncio
async def test_order_saga_v2_failing_compensates():
    from sagaz.demonstrations.schema_evolution.step_versioning.main import OrderSagaV2Failing

    with pytest.raises(Exception):
        await OrderSagaV2Failing().run({"customer": "Carol", "amount": 99.0})


@pytest.mark.asyncio
async def test_step_versioning_run_function():
    from sagaz.demonstrations.schema_evolution.step_versioning.main import _run

    await _run()


def test_step_versioning_main():
    with patch(
        "sagaz.demonstrations.schema_evolution.step_versioning.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.schema_evolution.step_versioning.main import main

        main()
        mock_run.assert_called_once()
