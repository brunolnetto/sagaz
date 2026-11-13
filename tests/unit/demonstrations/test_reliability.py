"""Tests for reliability demonstrations."""

import pytest

from sagaz.core.types import SagaStatus
from sagaz.demonstrations.reliability.chaos_patterns import main as chaos
from sagaz.demonstrations.reliability.chaos_patterns.main import _run as chaos_run
from sagaz.demonstrations.reliability.dlq_handling.main import _run as dlq_run
from sagaz.testing import FaultType


@pytest.mark.asyncio
async def test_dlq_handling_demo():
    """Test DLQ handling demonstration."""
    await dlq_run()
    # If no exception is raised, the demo ran successfully


class TestChaosPatternsDemo:
    """The chaos demo runs a real saga through ChaosMonkey and checks recovery."""

    async def test_demo_runs_and_reports_containment(self, capsys):
        await chaos_run()
        out = capsys.readouterr().out
        assert "✅ Every injected fault was contained by compensation" in out
        assert out.count("status       : rolled_back") == 3

    async def test_random_failure_rolls_back_completed_steps(self):
        result = await chaos.random_failure_experiment()
        assert result.status == SagaStatus.ROLLED_BACK
        assert result.executed == ["reserve_stock"]
        assert result.compensated == ["reserve_stock"]
        assert result.injections[FaultType.FAILURE] == 1

    async def test_timeout_is_retried_then_rolled_back(self):
        result = await chaos.timeout_experiment(max_retries=2)
        assert result.attempts == {"charge_card": 3}
        assert result.injections[FaultType.TIMEOUT] == 3
        assert result.status == SagaStatus.ROLLED_BACK

    async def test_parallel_failure_skips_join_and_failed_branch(self):
        result = await chaos.parallel_failure_experiment()
        assert "ship_order" not in result.executed
        assert "charge_card" not in result.compensated
        assert set(result.compensated) == {"reserve_stock", "validate_order"}

    async def test_verify_accepts_real_results(self):
        results = [
            await chaos.random_failure_experiment(),
            await chaos.timeout_experiment(),
            await chaos.parallel_failure_experiment(),
        ]
        assert chaos.verify(results) == []

    def test_verify_flags_every_violation(self):
        def broken(name, **overrides):
            fields = {
                "status": SagaStatus.FAILED,
                "executed": ["charge_card", "ship_order"],
                "compensated": ["charge_card"],
                "injections": {},
                "attempts": {"charge_card": 1},
            }
            fields.update(overrides)
            return chaos.ExperimentResult(name, **fields)

        problems = chaos.verify(
            [broken("random failure"), broken("timeout + retry"), broken("parallel DAG failure")]
        )
        assert problems == [
            "random failure did not roll back reserve_stock",
            "ship_order ran after charge_card failed",
            "timed-out step was not retried",
            "timeout did not end in rollback",
            "ship_order ran although a parent branch failed",
            "the failed branch was compensated",
        ]

    async def test_run_fails_loudly_when_verification_fails(self, monkeypatch, capsys):
        monkeypatch.setattr(chaos, "verify", lambda results: ["boom"])
        with pytest.raises(RuntimeError, match="did not behave"):
            await chaos_run()
        assert "❌ boom" in capsys.readouterr().out
