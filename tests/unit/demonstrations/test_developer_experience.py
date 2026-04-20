"""Tests for developer_experience demonstration modules."""

import asyncio
from unittest.mock import patch

import pytest


# ===========================================================================
# dry_run — ShippingSaga action + compensation body coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_shipping_saga_run_covers_action_bodies():
    """Running ShippingSaga directly covers all action return statements."""
    from sagaz.demonstrations.developer_experience.dry_run.main import ShippingSaga

    saga = ShippingSaga()
    result = await saga.run({"order_id": "ORD-DRY"})
    assert result.get("tracking_number") == "TRK-123"


@pytest.mark.asyncio
async def test_shipping_saga_compensation_bodies_directly():
    from sagaz.demonstrations.developer_experience.dry_run.main import ShippingSaga

    saga = ShippingSaga()
    ctx = {"order_id": "ORD-DRY"}
    await saga.release_inventory(ctx)
    await saga.release_warehouse(ctx)
    await saga.void_shipping(ctx)
    await saga.refund_customer(ctx)
    await saga.cancel_dispatch(ctx)


# ===========================================================================
# lifecycle_hooks — hook and compensation body coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_log_exit_hook_body():
    from sagaz.demonstrations.developer_experience.lifecycle_hooks.main import log_exit

    await log_exit({"order_id": "O1"}, "some_step")


@pytest.mark.asyncio
async def test_hooked_saga_compensation_bodies_directly():
    from sagaz.demonstrations.developer_experience.lifecycle_hooks.main import HookedSaga

    saga = HookedSaga()
    ctx = {"order_id": "ORD-HOOK"}
    await saga.undo_validate(ctx)
    await saga.refund(ctx)
    await saga.cancel_shipment(ctx)


@pytest.mark.asyncio
async def test_failing_hooked_saga_cancel_shipment_directly():
    from sagaz.demonstrations.developer_experience.lifecycle_hooks.main import FailingHookedSaga

    saga = FailingHookedSaga()
    await saga.cancel_shipment({"order_id": "ORD-HOOK-FAIL"})


# ===========================================================================
# visualization — FulfillmentSaga compensation body coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_fulfillment_saga_compensation_bodies_directly():
    from sagaz.demonstrations.developer_experience.visualization.main import FulfillmentSaga

    saga = FulfillmentSaga()
    ctx = {"order_id": "ORD-VIZ"}
    await saga.undo_validate(ctx)
    await saga.release_inventory(ctx)
    await saga.void_payment(ctx)
    await saga.void_fraud(ctx)
    await saga.refund_payment(ctx)
    await saga.cancel_shipment(ctx)


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


@pytest.mark.asyncio
async def test_dry_run_empty_forward_layers_branch():
    """Covers the FALSE branch of 'if result2.forward_layers:' (L113->119)."""
    from unittest.mock import AsyncMock
    from sagaz.dry_run import DryRunResult, DryRunMode
    from sagaz.demonstrations.developer_experience.dry_run.main import _run

    call_count = 0

    async def fake_run(saga, context, mode):
        nonlocal call_count
        call_count += 1
        result = DryRunResult(mode=mode, success=True)
        if call_count == 1:
            # Phase 1: VALIDATE — populate validation fields
            result.validation_errors = []
            result.validation_warnings = []
            result.validation_checks = {"has_steps": True}
        else:
            # Phase 2: SIMULATE — return empty forward_layers to hit FALSE branch
            result.execution_order = ["check_inventory"]
            result.parallel_groups = []
            result.forward_layers = []  # Triggers FALSE branch at L113
            result.total_layers = 0
            result.max_parallel_width = 0
            result.critical_path = []
            result.sequential_complexity = 1
            result.parallel_complexity = 0
            result.parallelization_ratio = 0.0
        return result

    with patch(
        "sagaz.demonstrations.developer_experience.dry_run.main.DryRunEngine"
    ) as MockEngine:
        MockEngine.return_value.run = fake_run
        await _run()
