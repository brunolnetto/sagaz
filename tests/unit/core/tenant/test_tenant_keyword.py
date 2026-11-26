"""One keyword for the tenant, ``tenant=``; the old ones work until 3.0 (#572)."""

from __future__ import annotations

import pytest

from sagaz.core.saga import Saga as ImperativeSaga
from sagaz.core.tenant import TenantContext, tenant_argument
from tests.unit.core.tenant.test_tenant_execution import ProbeSaga


def test_tenant_argument_returns_tenant_when_no_old_name_is_given():
    assert tenant_argument("f", "acme", tenant_id=None) == "acme"
    assert tenant_argument("f", None, tenant_id=None) is None


def test_an_old_name_still_works_with_a_deprecation_warning():
    with pytest.warns(
        DeprecationWarning, match=r"f\(tenant_id=\.\.\.\) is deprecated.*use tenant="
    ):
        assert tenant_argument("f", None, tenant_id="acme") == "acme"


def test_giving_both_names_is_an_error():
    with pytest.raises(TypeError, match="pass the tenant once"):
        tenant_argument("f", "acme", tenant_id="globex")


async def test_saga_run_takes_tenant_and_the_old_tenant_context():
    new = await ProbeSaga().run({}, tenant="acme")
    assert new["tenant_id"] == "acme"
    with pytest.warns(DeprecationWarning, match="Saga.run"):
        old = await ProbeSaga().run({}, tenant_context="globex")
    assert old["tenant_id"] == "globex"


async def test_saga_orchestrator_takes_tenant_and_the_old_tenant_id():
    from sagaz.core.execution.orchestrator import SagaOrchestrator

    assert SagaOrchestrator(tenant="acme").tenant.tenant_id == "acme"
    with pytest.warns(DeprecationWarning, match="SagaOrchestrator"):
        assert SagaOrchestrator(tenant_id="acme").tenant.tenant_id == "acme"
    saga = ImperativeSaga("one-step")

    async def step(ctx):
        return {"ok": True}

    await saga.add_step("step", step)
    result = await SagaOrchestrator(tenant=TenantContext("acme")).execute_saga(saga)
    assert result.success


async def test_begin_takes_tenant_as_an_id_or_a_context():
    from sagaz.choreography import ChoreographedSaga, ChoreographyEngine, EventBus

    engine = ChoreographyEngine(EventBus())

    class Orders(ChoreographedSaga):
        name = "orders"

    orders = Orders()
    engine.register(orders)
    await engine.start()
    try:
        assert (await orders.begin("order.created", tenant="acme")).tenant_id == "acme"
        context = TenantContext("globex")
        assert (await orders.begin("order.created", tenant=context)).tenant_id == "globex"
        with pytest.warns(DeprecationWarning, match="Orders.begin"):
            assert (await orders.begin("order.created", tenant_id="initech")).tenant_id == "initech"
    finally:
        await engine.stop()
