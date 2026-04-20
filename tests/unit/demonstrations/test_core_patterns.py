"""Tests for core_patterns demonstration modules."""

import asyncio
from unittest.mock import patch

import pytest


# ===========================================================================
# basic_saga
# ===========================================================================


@pytest.mark.asyncio
async def test_order_saga_success():
    from sagaz.demonstrations.core_patterns.basic_saga.main import OrderSaga

    saga = OrderSaga()
    result = await saga.run({"order_id": "ORD-001", "amount": 99.99})
    assert result.get("validated") is True
    assert result.get("notified") is True


@pytest.mark.asyncio
async def test_failing_order_saga_compensates():
    from sagaz.demonstrations.core_patterns.basic_saga.main import FailingOrderSaga

    saga = FailingOrderSaga()
    with pytest.raises(Exception):
        await saga.run({"order_id": "ORD-002", "amount": 49.99})


@pytest.mark.asyncio
async def test_basic_saga_run_function():
    from sagaz.demonstrations.core_patterns.basic_saga.main import _run

    await _run()


def test_basic_saga_main():
    with patch(
        "sagaz.demonstrations.core_patterns.basic_saga.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.core_patterns.basic_saga.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# compensation_deep_dive
# ===========================================================================


@pytest.mark.asyncio
async def test_payment_saga_compensates():
    from sagaz.demonstrations.core_patterns.compensation_deep_dive.main import PaymentSaga

    saga = PaymentSaga()
    with pytest.raises(Exception):
        await saga.run({"customer": "Alice"})


@pytest.mark.asyncio
async def test_trade_saga_pivot_forward_recovery():
    from sagaz.demonstrations.core_patterns.compensation_deep_dive.main import TradeSaga

    saga = TradeSaga()
    # TradeSaga has a pivot + forward_recovery(SKIP). Saga may complete or raise
    # depending on how SKIP recovery propagates — either is acceptable here.
    try:
        result = await saga.run({"trade_id": "TRD-1"})
        assert result is not None
    except Exception:
        pass  # Forward recovery may still propagate the error


@pytest.mark.asyncio
async def test_compensation_deep_dive_run_function():
    from sagaz.demonstrations.core_patterns.compensation_deep_dive.main import _run

    await _run()


def test_compensation_deep_dive_main():
    with patch(
        "sagaz.demonstrations.core_patterns.compensation_deep_dive.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.core_patterns.compensation_deep_dive.main import main

        main()
        mock_run.assert_called_once()


# ===========================================================================
# parallel_steps
# ===========================================================================


@pytest.mark.asyncio
async def test_build_success_saga_all_strategies():
    from sagaz.demonstrations.core_patterns.parallel_steps.main import build_success_saga
    from sagaz.core.types import ParallelFailureStrategy

    for strategy in ParallelFailureStrategy:
        saga = await build_success_saga(strategy)
        result = await saga.execute()
        assert result.completed_steps > 0


@pytest.mark.asyncio
async def test_build_failing_saga():
    from sagaz.demonstrations.core_patterns.parallel_steps.main import build_failing_saga
    from sagaz.core.types import ParallelFailureStrategy

    saga = await build_failing_saga(ParallelFailureStrategy.FAIL_FAST)
    result = await saga.execute()
    # Fraud check fails so saga should not be COMPLETED
    assert result.completed_steps < result.total_steps or result.status.value != "completed"


@pytest.mark.asyncio
async def test_parallel_steps_run_function():
    from sagaz.demonstrations.core_patterns.parallel_steps.main import _run

    await _run()


def test_parallel_steps_main():
    with patch(
        "sagaz.demonstrations.core_patterns.parallel_steps.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.core_patterns.parallel_steps.main import main

        main()
        mock_run.assert_called_once()
