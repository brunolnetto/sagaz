"""Tests for developer_experience demonstration modules."""

import asyncio
from unittest.mock import patch

import pytest


# ===========================================================================
# dry_run
# ===========================================================================


@pytest.mark.asyncio
async def test_shipping_saga_validate_mode():
    from sagaz import DryRunEngine, DryRunMode
    from sagaz.demonstrations.developer_experience.dry_run.main import ShippingSaga

    engine = DryRunEngine()
    saga = ShippingSaga()
    result = await engine.run(saga, {"order_id": "ORD-1"}, DryRunMode.VALIDATE)
    assert result.success is True


@pytest.mark.asyncio
async def test_shipping_saga_simulate_mode():
    from sagaz import DryRunEngine, DryRunMode
    from sagaz.demonstrations.developer_experience.dry_run.main import ShippingSaga

    engine = DryRunEngine()
    saga = ShippingSaga()
    result = await engine.run(saga, {"order_id": "ORD-1"}, DryRunMode.SIMULATE)
    assert result.execution_order


@pytest.mark.asyncio
async def test_dry_run_run_function():
    from sagaz.demonstrations.developer_experience.dry_run.main import _run

    await _run()


def test_dry_run_main():
    with patch(
        "sagaz.demonstrations.developer_experience.dry_run.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.developer_experience.dry_run.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# lifecycle_hooks
# ===========================================================================


@pytest.mark.asyncio
async def test_hooked_saga_success():
    from sagaz.demonstrations.developer_experience.lifecycle_hooks.main import (
        HookedSaga,
        audit_listener,
    )

    audit_listener.trail.clear()
    saga = HookedSaga()
    result = await saga.run({"order_id": "ORD-10"})
    assert result.get("validated") is True
    assert result.get("tracking") == "TRK-99"
    assert any("step_enter" in e for e in audit_listener.trail)


@pytest.mark.asyncio
async def test_failing_hooked_saga_triggers_compensation():
    from sagaz.demonstrations.developer_experience.lifecycle_hooks.main import (
        FailingHookedSaga,
        audit_listener,
    )

    audit_listener.trail.clear()
    saga = FailingHookedSaga()
    with pytest.raises(Exception):
        await saga.run({"order_id": "ORD-11"})
    assert any("step_failure" in e for e in audit_listener.trail)


@pytest.mark.asyncio
async def test_lifecycle_hooks_run_function():
    from sagaz.demonstrations.developer_experience.lifecycle_hooks.main import _run

    await _run()


def test_lifecycle_hooks_main():
    with patch(
        "sagaz.demonstrations.developer_experience.lifecycle_hooks.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.developer_experience.lifecycle_hooks.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# visualization
# ===========================================================================


@pytest.mark.asyncio
async def test_fulfillment_saga_mermaid_default():
    from sagaz.demonstrations.developer_experience.visualization.main import FulfillmentSaga

    saga = FulfillmentSaga()
    diagram = saga.to_mermaid(direction="TB", show_compensation=True)
    assert "flowchart" in diagram or "graph" in diagram or "validate_order" in diagram


@pytest.mark.asyncio
async def test_fulfillment_saga_mermaid_no_compensation():
    from sagaz.demonstrations.developer_experience.visualization.main import FulfillmentSaga

    saga = FulfillmentSaga()
    diagram = saga.to_mermaid(direction="LR", show_compensation=False)
    assert diagram is not None


@pytest.mark.asyncio
async def test_fulfillment_saga_runs_successfully():
    from sagaz.demonstrations.developer_experience.visualization.main import FulfillmentSaga

    saga = FulfillmentSaga()
    result = await saga.run({"order_id": "ORD-VIZ"})
    assert result.get("tracking") == "TRK-001"


@pytest.mark.asyncio
async def test_visualization_run_function():
    from sagaz.demonstrations.developer_experience.visualization.main import _run

    await _run()


def test_visualization_main():
    with patch(
        "sagaz.demonstrations.developer_experience.visualization.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.developer_experience.visualization.main import main

        main()
        mock_run.assert_called_once()
