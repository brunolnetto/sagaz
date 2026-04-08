"""
Unit tests for ChaosMonkey – Chaos Engineering.

Implements ADR-017: Chaos Engineering Automation
TDD: red phase – all tests will fail until sagaz/testing/chaos.py exists.

Coverage targets:
- ChaosMonkey construction and defaults
- Fault injection: failure, timeout, latency
- Targeted vs. global chaos
- Seed-based reproducibility
- ChaosReport generation and metrics
- Context manager (enable/disable)
- reset() clears metrics
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.testing.chaos import (
    ChaosDisabled,
    ChaosMonkey,
    ChaosReport,
    FaultType,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _noop_action(ctx: dict) -> str:
    """Stub action that returns a fixed value."""
    return "ok"


def _make_monkey(**kwargs) -> ChaosMonkey:
    return ChaosMonkey(seed=0, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Construction & defaults
# ─────────────────────────────────────────────────────────────────────────────


class TestChaosMonkeyDefaults:
    def test_default_rates_are_zero(self):
        cm = ChaosMonkey()
        assert cm.failure_rate == 0.0
        assert cm.timeout_probability == 0.0
        assert cm.latency_range is None
        assert cm.target_steps == []
        assert cm.exception_types == [RuntimeError]

    def test_custom_failure_rate(self):
        cm = ChaosMonkey(failure_rate=0.25)
        assert cm.failure_rate == 0.25

    def test_custom_exception_types(self):
        cm = ChaosMonkey(exception_types=[ValueError, ConnectionError])
        assert ValueError in cm.exception_types
        assert ConnectionError in cm.exception_types

    def test_seed_creates_reproducible_instance(self):
        cm1 = ChaosMonkey(seed=42)
        cm2 = ChaosMonkey(seed=42)
        # Both should produce identical random draws
        assert cm1.random.random() == cm2.random.random()

    def test_target_steps_stored(self):
        cm = ChaosMonkey(target_steps=["charge", "reserve"])
        assert "charge" in cm.target_steps
        assert "reserve" in cm.target_steps


# ─────────────────────────────────────────────────────────────────────────────
# Fault injection – failure
# ─────────────────────────────────────────────────────────────────────────────


class TestChaosMonkeyFailureInjection:
    async def test_zero_failure_rate_never_fails(self):
        cm = ChaosMonkey(failure_rate=0.0, seed=0)
        for _ in range(50):
            result = await cm.intercept_step("any_step", _noop_action, {})
            assert result == "ok"

    async def test_full_failure_rate_always_raises(self):
        cm = ChaosMonkey(failure_rate=1.0, seed=0)
        with pytest.raises(RuntimeError, match="Chaos"):
            await cm.intercept_step("step", _noop_action, {})

    async def test_failure_increments_injection_counter(self):
        cm = ChaosMonkey(failure_rate=1.0, seed=0)
        with pytest.raises(RuntimeError):
            await cm.intercept_step("step", _noop_action, {})
        assert cm.injections[FaultType.FAILURE] >= 1

    async def test_custom_exception_type_is_raised(self):
        cm = ChaosMonkey(failure_rate=1.0, exception_types=[ValueError], seed=0)
        with pytest.raises(ValueError):
            await cm.intercept_step("step", _noop_action, {})

    async def test_no_failure_injected_when_step_not_targeted(self):
        cm = ChaosMonkey(failure_rate=1.0, target_steps=["other_step"], seed=0)
        result = await cm.intercept_step("my_step", _noop_action, {})
        assert result == "ok"

    async def test_failure_injected_when_step_is_targeted(self):
        cm = ChaosMonkey(failure_rate=1.0, target_steps=["my_step"], seed=0)
        with pytest.raises(RuntimeError):
            await cm.intercept_step("my_step", _noop_action, {})


# ─────────────────────────────────────────────────────────────────────────────
# Fault injection – latency
# ─────────────────────────────────────────────────────────────────────────────


class TestChaosMonkeyLatencyInjection:
    async def test_latency_range_adds_delay(self):
        with patch("sagaz.testing.chaos.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            cm = ChaosMonkey(latency_range=(100, 100), failure_rate=0.0, seed=0)
            await cm.intercept_step("step", _noop_action, {})
        sleep_mock.assert_called_once()
        delay_seconds = sleep_mock.call_args[0][0]
        assert 0.0 <= delay_seconds <= 1.0  # 100ms → 0.1s

    async def test_latency_increments_counter(self):
        with patch("sagaz.testing.chaos.asyncio.sleep", new_callable=AsyncMock):
            cm = ChaosMonkey(latency_range=(50, 50), seed=0)
            await cm.intercept_step("step", _noop_action, {})
        assert cm.injections[FaultType.LATENCY] == 1

    async def test_no_latency_when_range_is_none(self):
        with patch("sagaz.testing.chaos.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            cm = ChaosMonkey(latency_range=None, failure_rate=0.0, seed=0)
            await cm.intercept_step("step", _noop_action, {})
        sleep_mock.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Fault injection – timeout
# ─────────────────────────────────────────────────────────────────────────────


class TestChaosMonkeyTimeoutInjection:
    async def test_timeout_raises_asyncio_timeout(self):
        """When timeout is injected, the step should raise asyncio.TimeoutError."""
        cm = ChaosMonkey(timeout_probability=1.0, seed=0)
        with pytest.raises(asyncio.TimeoutError):
            await cm.intercept_step("step", _noop_action, {})

    async def test_timeout_increments_counter(self):
        cm = ChaosMonkey(timeout_probability=1.0, seed=0)
        with pytest.raises(asyncio.TimeoutError):
            await cm.intercept_step("step", _noop_action, {})
        assert cm.injections[FaultType.TIMEOUT] >= 1

    async def test_zero_timeout_probability_never_times_out(self):
        cm = ChaosMonkey(timeout_probability=0.0, seed=0)
        for _ in range(50):
            result = await cm.intercept_step("step", _noop_action, {})
            assert result == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# ChaosReport
# ─────────────────────────────────────────────────────────────────────────────


class TestChaosReport:
    async def test_report_initial_state(self):
        cm = ChaosMonkey(seed=0)
        report = cm.report()
        assert isinstance(report, ChaosReport)
        assert report.total_injections == 0

    async def test_report_reflects_injections(self):
        cm = ChaosMonkey(failure_rate=1.0, seed=0)
        with pytest.raises(RuntimeError):
            await cm.intercept_step("step", _noop_action, {})
        report = cm.report()
        assert report.total_injections == 1
        assert report.by_type.get(FaultType.FAILURE, 0) == 1

    async def test_report_total_sums_all_types(self):
        with patch("sagaz.testing.chaos.asyncio.sleep", new_callable=AsyncMock):
            cm = ChaosMonkey(latency_range=(10, 10), failure_rate=0.0, seed=0)
            # Run 3 steps, all get latency injected
            for _ in range(3):
                await cm.intercept_step("step", _noop_action, {})
        report = cm.report()
        assert report.total_injections == 3

    def test_report_str_representation(self):
        report = ChaosReport(total_injections=5, by_type={FaultType.FAILURE: 5}, recoveries={})
        assert "5" in str(report)


# ─────────────────────────────────────────────────────────────────────────────
# reset()
# ─────────────────────────────────────────────────────────────────────────────


class TestChaosMonkeyReset:
    async def test_reset_clears_counters(self):
        cm = ChaosMonkey(failure_rate=1.0, seed=0)
        with pytest.raises(RuntimeError):
            await cm.intercept_step("step", _noop_action, {})
        assert cm.report().total_injections > 0
        cm.reset()
        assert cm.report().total_injections == 0

    def test_reset_preserves_configuration(self):
        cm = ChaosMonkey(failure_rate=0.5, target_steps=["charge"], seed=7)
        cm.reset()
        assert cm.failure_rate == 0.5
        assert "charge" in cm.target_steps


# ─────────────────────────────────────────────────────────────────────────────
# ChaosDisabled (no-op sentinel)
# ─────────────────────────────────────────────────────────────────────────────


class TestChaosDisabled:
    async def test_disabled_always_executes_action(self):
        disabled = ChaosDisabled()
        result = await disabled.intercept_step("any", _noop_action, {})
        assert result == "ok"

    def test_disabled_report_has_zero_injections(self):
        report = ChaosDisabled().report()
        assert report.total_injections == 0

    def test_disabled_reset_is_noop(self):
        ChaosDisabled().reset()  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# is_active property
# ─────────────────────────────────────────────────────────────────────────────


class TestChaosMonkeyIsActive:
    def test_is_active_when_failure_rate_positive(self):
        cm = ChaosMonkey(failure_rate=0.1)
        assert cm.is_active is True

    def test_is_active_when_timeout_positive(self):
        cm = ChaosMonkey(timeout_probability=0.05)
        assert cm.is_active is True

    def test_is_active_when_latency_set(self):
        cm = ChaosMonkey(latency_range=(100, 500))
        assert cm.is_active is True

    def test_is_inactive_when_all_zero(self):
        cm = ChaosMonkey()
        assert cm.is_active is False

    def test_disabled_is_never_active(self):
        assert ChaosDisabled().is_active is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
