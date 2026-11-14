"""Tenant context, scopes, registry and quota enforcement (ADR-020, #54)."""

from __future__ import annotations

import asyncio

import pytest

from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.tenant import (
    DEFAULT_TENANT,
    TENANT_RECORD_SAGA_NAME,
    CrossTenantAccessError,
    InvalidTenantIdError,
    QuotaEnforcer,
    QuotaExceededError,
    TenantContext,
    TenantError,
    TenantNotFoundError,
    TenantQuotas,
    TenantRegistry,
    TenantSuspendedError,
    capped_retries,
    capped_timeout,
    current_tenant_context,
    current_tenant_id,
    ensure_tenant_access,
    is_system_scope,
    system_scope,
    tenant_scope,
    validate_tenant_id,
)


class TestTenantIds:
    @pytest.mark.parametrize("tenant_id", ["acme", "a", "acme-corp_eu.1", "0tenant", "x" * 63])
    def test_valid_ids(self, tenant_id):
        assert validate_tenant_id(tenant_id) == tenant_id

    @pytest.mark.parametrize(
        "tenant_id", ["", "Acme", "-acme", "acme corp", "a:b", "*", "x" * 64, None, 7]
    )
    def test_invalid_ids_are_rejected(self, tenant_id):
        with pytest.raises(InvalidTenantIdError) as info:
            validate_tenant_id(tenant_id)
        assert isinstance(info.value, ValueError)

    def test_context_validates_its_id(self):
        with pytest.raises(InvalidTenantIdError):
            TenantContext("Not Valid")


class TestQuotasAndContext:
    def test_negative_quota_is_rejected(self):
        with pytest.raises(ValueError, match="max_retries"):
            TenantQuotas(max_retries=-1)

    def test_context_round_trips_through_a_dict(self):
        tenant = TenantContext(
            "acme",
            plan="premium",
            quotas=TenantQuotas(max_concurrent_sagas=5, max_step_duration_seconds=2.5),
            active=False,
            name="ACME",
            metadata={"region": "eu"},
        )
        assert TenantContext.from_dict(tenant.to_dict()) == tenant

    def test_from_dict_defaults(self):
        tenant = TenantContext.from_dict({"tenant_id": "acme"})
        assert (tenant.plan, tenant.active, tenant.quotas) == ("standard", True, TenantQuotas())


class TestScopes:
    def test_default_scope(self):
        assert current_tenant_id() == DEFAULT_TENANT
        assert current_tenant_context() is None
        assert not is_system_scope()

    def test_nested_scopes_restore_the_previous_tenant(self):
        tenant = TenantContext("beta")
        with tenant_scope("acme") as tenant_id:
            assert tenant_id == "acme"
            assert current_tenant_context() is None
            with tenant_scope(tenant):
                assert current_tenant_id() == "beta"
                assert current_tenant_context() is tenant
            assert current_tenant_id() == "acme"
        assert current_tenant_id() == DEFAULT_TENANT

    def test_scope_is_restored_after_an_error(self):
        with pytest.raises(RuntimeError), tenant_scope("acme"):
            raise RuntimeError
        assert current_tenant_id() == DEFAULT_TENANT

    def test_invalid_scope_is_rejected(self):
        with pytest.raises(InvalidTenantIdError), tenant_scope("*"):
            pass

    def test_system_scope(self):
        with tenant_scope("acme"), system_scope():
            assert is_system_scope()
            assert current_tenant_context() is None
        assert not is_system_scope()

    async def test_concurrent_tasks_keep_their_own_tenant(self):
        async def run_as(tenant_id):
            with tenant_scope(tenant_id):
                await asyncio.sleep(0.01)
                return current_tenant_id()

        assert await asyncio.gather(run_as("acme"), run_as("beta")) == ["acme", "beta"]
        assert current_tenant_id() == DEFAULT_TENANT


class TestCrossTenantGuard:
    def test_own_and_default_records(self):
        with tenant_scope("acme"):
            ensure_tenant_access("acme")
        ensure_tenant_access(None)
        ensure_tenant_access(DEFAULT_TENANT)

    def test_foreign_record_is_rejected(self):
        with tenant_scope("acme"), pytest.raises(CrossTenantAccessError) as info:
            ensure_tenant_access("beta")
        assert (info.value.record_tenant, info.value.current_tenant) == ("beta", "acme")

    def test_untagged_record_belongs_to_default(self):
        with tenant_scope("acme"), pytest.raises(CrossTenantAccessError):
            ensure_tenant_access(None)

    def test_system_scope_accesses_everything(self):
        with system_scope():
            ensure_tenant_access("beta")


class TestQuotaEnforcer:
    async def test_concurrency_limit(self):
        enforcer = QuotaEnforcer()
        tenant = TenantContext("acme", quotas=TenantQuotas(max_concurrent_sagas=1))
        async with enforcer.admit(tenant):
            assert enforcer.running("acme") == 1
            with pytest.raises(QuotaExceededError) as info:
                async with enforcer.admit(tenant):
                    pass
            assert (info.value.quota, info.value.limit, info.value.current) == (
                "max_concurrent_sagas",
                1,
                2,
            )
        assert enforcer.running("acme") == 0

    async def test_slot_is_released_after_an_error(self):
        enforcer = QuotaEnforcer()
        tenant = TenantContext("acme", quotas=TenantQuotas(max_concurrent_sagas=1))
        with pytest.raises(RuntimeError):
            async with enforcer.admit(tenant):
                raise RuntimeError
        async with enforcer.admit(tenant):
            pass

    async def test_tenants_do_not_share_slots(self):
        enforcer = QuotaEnforcer()
        quotas = TenantQuotas(max_concurrent_sagas=1)
        async with enforcer.admit(TenantContext("acme", quotas=quotas)):
            async with enforcer.admit(TenantContext("beta", quotas=quotas)):
                assert (enforcer.running("acme"), enforcer.running("beta")) == (1, 1)

    async def test_suspended_tenant_is_refused(self):
        with pytest.raises(TenantSuspendedError):
            async with QuotaEnforcer().admit(TenantContext("acme", active=False)):
                pass

    def test_caps_apply_only_inside_a_limited_tenant(self):
        assert (capped_timeout(30), capped_retries(5)) == (30, 5)
        limited = TenantContext(
            "acme", quotas=TenantQuotas(max_step_duration_seconds=2, max_retries=1)
        )
        with tenant_scope(limited):
            assert (capped_timeout(30), capped_timeout(1), capped_retries(5)) == (2, 1, 1)
        with tenant_scope(TenantContext("beta")):
            assert (capped_timeout(30), capped_retries(5)) == (30, 5)


class TestRegistry:
    def test_register_get_list_and_delete(self):
        registry = TenantRegistry()
        registry.register(TenantContext("beta"))
        registry.register(TenantContext("acme"))
        assert "acme" in registry
        assert [t.tenant_id for t in registry.list()] == ["acme", "beta"]
        assert registry.delete("acme").tenant_id == "acme"
        assert "acme" not in registry

    def test_duplicates_and_unknown_tenants(self):
        registry = TenantRegistry()
        registry.register(TenantContext("acme"))
        with pytest.raises(TenantError, match="already registered"):
            registry.register(TenantContext("acme"))
        with pytest.raises(TenantNotFoundError) as info:
            registry.get("ghost")
        assert "ghost" in str(info.value)
        with pytest.raises(TenantNotFoundError):
            registry.delete("ghost")

    def test_quotas_and_status_updates(self):
        registry = TenantRegistry()
        registry.register(TenantContext("acme", plan="free"))
        registry.set_quotas("acme", TenantQuotas(max_retries=2))
        registry.set_active("acme", False)
        tenant = registry.get("acme")
        assert (tenant.plan, tenant.quotas.max_retries, tenant.active) == ("free", 2, False)

    async def test_persistence_survives_a_reload_and_deletions(self):
        storage = InMemorySagaStorage()
        registry = TenantRegistry(storage)
        registry.register(TenantContext("acme", quotas=TenantQuotas(max_concurrent_sagas=3)))
        registry.register(TenantContext("beta"))
        assert await registry.save() == 2

        registry.delete("beta")
        await registry.save()
        reloaded = await TenantRegistry.from_storage(storage)

        assert [t.tenant_id for t in reloaded.list()] == ["acme"]
        assert reloaded.get("acme").quotas.max_concurrent_sagas == 3

    async def test_records_live_in_the_default_partition(self):
        storage = InMemorySagaStorage()
        registry = TenantRegistry(storage)
        registry.register(TenantContext("acme"))
        with tenant_scope("acme"):
            await registry.save()  # saved in the default partition whatever the scope
        summaries = await storage.list_sagas(saga_name=TENANT_RECORD_SAGA_NAME)
        assert [s["saga_id"] for s in summaries] == [f"{TENANT_RECORD_SAGA_NAME}:acme"]

    async def test_vanished_record_is_skipped(self, monkeypatch):
        storage = InMemorySagaStorage()
        registry = TenantRegistry(storage)
        registry.register(TenantContext("acme"))
        await registry.save()

        async def gone(saga_id):
            return None

        monkeypatch.setattr(storage, "load_saga_state", gone)
        assert await TenantRegistry(storage).load() == 0

    async def test_persistence_requires_storage(self):
        with pytest.raises(ValueError, match="storage"):
            await TenantRegistry().save()
        with pytest.raises(ValueError, match="storage"):
            await TenantRegistry().load()
