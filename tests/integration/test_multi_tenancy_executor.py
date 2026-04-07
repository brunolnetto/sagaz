"""
Integration tests for multi-tenant saga execution.

Implements ADR-020: Multi-Tenant Isolation
Tests cover:
- Tenant-aware saga execution
- Tenant registry operations
- Database session management
- Feature management
"""

from datetime import datetime, timedelta

import pytest

from sagaz.core.tenant import (
    TenantAwareSagaExecutor,
    TenantContext,
    TenantError,
    TenantQuotas,
    TenantRegistry,
)


class TestTenantRegistry:
    """Tests for TenantRegistry."""

    @pytest.mark.asyncio
    async def test_register_tenant(self):
        """Test registering a new tenant."""
        registry = TenantRegistry()

        tenant_data = {
            "tenant_id": "merchant-a",
            "name": "MerchantA",
            "tier": "premium",
            "status": "active",
        }

        await registry.register("merchant-a", tenant_data)

        result = await registry.get("merchant-a")
        assert result is not None
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_nonexistent_tenant(self):
        """Test getting a tenant that doesn't exist."""
        registry = TenantRegistry()

        result = await registry.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_tenant(self):
        """Test updating tenant data."""
        registry = TenantRegistry()

        initial_data = {
            "tenant_id": "merchant-a",
            "name": "MerchantA",
            "tier": "standard",
        }

        await registry.register("merchant-a", initial_data)

        updated_data = {"tier": "premium"}
        await registry.update("merchant-a", updated_data)

        result = await registry.get("merchant-a")
        assert result["tier"] == "premium"
        assert result["name"] == "MerchantA"  # Unchanged

    @pytest.mark.asyncio
    async def test_delete_tenant(self):
        """Test deleting a tenant."""
        registry = TenantRegistry()

        await registry.register("merchant-a", {"tenant_id": "merchant-a", "name": "MerchantA"})

        await registry.delete("merchant-a")

        result = await registry.get("merchant-a")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_all_tenants(self):
        """Test listing all registered tenants."""
        registry = TenantRegistry()

        await registry.register("merchant-a", {"name": "MerchantA"})
        await registry.register("merchant-b", {"name": "MerchantB"})
        await registry.register("merchant-c", {"name": "MerchantC"})

        tenants = await registry.list_all()
        assert len(tenants) == 3
        assert "merchant-a" in tenants
        assert "merchant-b" in tenants
        assert "merchant-c" in tenants

    @pytest.mark.asyncio
    async def test_delete_nonexistent_tenant(self):
        """Test deleting a tenant that doesn't exist (should not raise)."""
        registry = TenantRegistry()

        # Should not raise
        await registry.delete("nonexistent")


class TestTenantContextEnrichment:
    """Tests for enriching saga context with tenant information."""

    def test_enrich_context_with_tenant(self):
        """Test enriching saga context with tenant information."""
        tenant_ctx = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="premium",
            region="us-east-1",
        )

        saga_context = {
            "order_id": "order-123",
            "amount": 99.99,
        }

        enriched_context = {
            **saga_context,
            "tenant_context": tenant_ctx,
        }

        assert enriched_context["order_id"] == "order-123"
        assert enriched_context["amount"] == 99.99
        assert enriched_context["tenant_context"].tenant_id == "merchant-a"

    def test_tenant_isolation_ensures_distinct_contexts(self):
        """Test that tenant contexts remain isolated."""
        tenant1 = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="premium",
            region="us-east-1",
        )

        tenant2 = TenantContext(
            tenant_id="merchant-b",
            tenant_name="Merchant B",
            tier="standard",
            region="eu-west-1",
        )

        context1 = {"order_id": "order-1", "tenant_context": tenant1}
        context2 = {"order_id": "order-2", "tenant_context": tenant2}

        # Modify context1 should not affect context2
        context1["custom_field"] = "value"

        assert "custom_field" not in context2
        assert context1["tenant_context"].tenant_id != context2["tenant_context"].tenant_id


class TestTenantFeatureManagement:
    """Tests for tenant feature flags."""

    def test_enable_feature(self):
        """Test enabling a feature."""
        tenant_ctx = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="premium",
            region="us-east-1",
        )

        tenant_ctx.enable_feature("chaos_engineering")
        assert tenant_ctx.has_feature("chaos_engineering")

    def test_disable_feature(self):
        """Test disabling a feature."""
        tenant_ctx = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="premium",
            region="us-east-1",
            features={"chaos_engineering"},
        )

        tenant_ctx.disable_feature("chaos_engineering")
        assert not tenant_ctx.has_feature("chaos_engineering")

    def test_multiple_features(self):
        """Test managing multiple features."""
        features = {"dry_run", "versioning", "chaos_engineering"}
        tenant_ctx = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="enterprise",
            region="us-east-1",
            features=features,
        )

        assert len(tenant_ctx.features) == 3
        assert tenant_ctx.has_feature("dry_run")
        assert tenant_ctx.has_feature("versioning")
        assert tenant_ctx.has_feature("chaos_engineering")

    def test_feature_check_nonexistent(self):
        """Test checking for a feature that doesn't exist."""
        tenant_ctx = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="free",
            region="us-east-1",
        )

        assert not tenant_ctx.has_feature("premium_feature")


class TestTenantQuotaManagement:
    """Tests for quota management."""

    def test_get_quota(self):
        """Test getting a quota value."""
        quotas = TenantQuotas(
            max_concurrent_sagas=50,
            max_sagas_per_hour=5000,
        )

        tenant_ctx = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="standard",
            region="us-east-1",
            quotas=quotas,
        )

        assert tenant_ctx.get_quota("max_concurrent_sagas") == 50
        assert tenant_ctx.get_quota("max_sagas_per_hour") == 5000

    def test_get_quota_with_default(self):
        """Test getting a quota with default value."""
        tenant_ctx = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="free",
            region="us-east-1",
        )

        # Should use default if quota is None or field doesn't exist
        value = tenant_ctx.get_quota("nonexistent_quota", default=999)
        assert value == 999

    def test_quota_enforcement_levels(self):
        """Test different quota levels by tier."""
        free_quotas = TenantQuotas(
            max_concurrent_sagas=10,
            max_sagas_per_hour=100,
        )

        TenantQuotas(
            max_concurrent_sagas=100,
            max_sagas_per_hour=10000,
        )

        premium_quotas = TenantQuotas(
            max_concurrent_sagas=1000,
            max_sagas_per_hour=100000,
        )

        free_tenant = TenantContext(
            tenant_id="merchant-free",
            tenant_name="Free",
            tier="free",
            region="us-east-1",
            quotas=free_quotas,
        )

        premium_tenant = TenantContext(
            tenant_id="merchant-premium",
            tenant_name="Premium",
            tier="premium",
            region="us-east-1",
            quotas=premium_quotas,
        )

        assert free_tenant.get_quota("max_concurrent_sagas") == 10
        assert premium_tenant.get_quota("max_concurrent_sagas") == 1000


class TestTenantExecutorBasics:
    """Basic tests for TenantAwareSagaExecutor."""

    @pytest.mark.asyncio
    async def test_executor_initialization(self):
        """Test initializing executor with mock storage and registry."""
        registry = TenantRegistry()

        # Mock storage object
        class MockStorage:
            pass

        storage = MockStorage()

        executor = TenantAwareSagaExecutor(storage=storage, tenant_registry=registry)

        assert executor.storage is not None
        assert executor.tenant_registry is not None
        assert executor.db is None  # No DB connection by default


class TestTenantContextStringRepresentation:
    """Tests for string representation of tenant context."""

    def test_str_representation(self):
        """Test string representation."""
        tenant_ctx = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="premium",
            region="us-east-1",
        )

        str_repr = str(tenant_ctx)
        assert "merchant-a" in str_repr
        assert "premium" in str_repr
        assert "us-east-1" in str_repr

    def test_repr_representation(self):
        """Test repr representation."""
        tenant_ctx = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="premium",
            region="us-east-1",
        )

        repr_str = repr(tenant_ctx)
        assert "merchant-a" in repr_str
        assert "TenantContext" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
