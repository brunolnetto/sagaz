"""Tests for integrations demonstrations."""

from __future__ import annotations

import time

import pytest

from sagaz.core.tenant import tenant_scope
from sagaz.core.types import SagaStatus
from sagaz.demonstrations.integrations.multi_tenancy import main as demo


async def _executed(encryption: bool = True) -> demo.Deployment:
    deployment = demo.setup(encryption=encryption)
    await demo.execute(deployment)
    return deployment


class TestMultiTenancyDemo:
    async def test_runs_fast_and_reports_isolation(self, capsys):
        started = time.perf_counter()
        await demo._run()
        assert time.perf_counter() - started < 0.5

        out = capsys.readouterr().out
        assert "acme/order-1001      completed" in out
        assert "globex/order-1001    rolled_back" in out
        assert "max_concurrent_sagas" in out
        assert "no data crossed, quotas enforced, data encrypted" in out

    async def test_same_saga_id_two_tenants_are_isolated(self):
        deployment = await _executed()
        assert await demo.verify(deployment) == []
        with tenant_scope("acme"):
            acme = await deployment.storage.load_saga_state(demo.ORDER_ID)
        assert acme["context"]["card"] == demo.CARD  # the application sees plaintext

    async def test_without_encryption_the_rest_still_holds(self, capsys, monkeypatch):
        deployment = await _executed(encryption=False)
        assert deployment.storage is deployment.plain
        assert await demo.verify(deployment) == []

        monkeypatch.setattr(demo, "ENCRYPTION", False)
        await demo._run()
        out = capsys.readouterr().out
        assert "install sagaz[encryption]" in out
        assert "data encrypted" not in out

    async def test_per_tenant_counts_come_from_one_system_scope_listing(self):
        deployment = await _executed()
        counts = await demo.per_tenant_counts(deployment.plain)
        assert {t: dict(c) for t, c in counts.items()} == {
            "acme": {"completed": 1},
            "globex": {"completed": 2, "rolled_back": 1},
        }

    async def test_verify_flags_every_violation(self):
        deployment = demo.setup()  # nothing executed: every expectation fails
        await deployment.plain.save_saga_state(
            demo.ORDER_ID, "order", SagaStatus.COMPLETED, [], {"card": demo.CARD}
        )  # visible to the default tenant, in plaintext

        problems = await demo.verify(deployment)

        assert problems == [
            "acme does not see its own completed order",
            "globex does not see its own rolled-back order",
            "the default tenant can see a tenant's order",
            "acme's order is stored in plaintext",
            "globex's concurrency quota did not refuse exactly one saga",
            "unexpected per-tenant counts: {'default': Counter({'completed': 1})}",
        ]

    async def test_run_fails_loudly_when_verification_fails(self, monkeypatch, capsys):
        async def broken(deployment):
            return ["isolation broke"]

        monkeypatch.setattr(demo, "verify", broken)
        with pytest.raises(RuntimeError, match="tenant isolation did not hold"):
            await demo._run()
        assert "❌ isolation broke" in capsys.readouterr().out
