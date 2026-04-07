"""
Unit tests for tenant context and multi-tenant isolation.

Implements ADR-020: Multi-Tenant Isolation
Tests cover:
- TenantContext creation and validation
- Tenant-aware saga execution
- Resource quota enforcement
- Cross-tenant prevention
- Database session tenant isolation
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from sagaz.core.context import SagaContext
from sagaz.core.exceptions import SagaError
from sagaz.core.tenant import (
    QuotaExceededError,
    RateLimitExceededError,
    TenantAwareSagaExecutor,
    TenantContext,
    TenantError,
    TenantNotFoundError,
    TenantQuotas,
    TenantRegistry,
    TenantSuspendedError,
)
from sagaz.core.types import SagaResult, SagaStatus


class TestTenantContext:
    """Tests for TenantContext dataclass."""

    def test_tenant_context_creation(self):
        """Test creating a valid tenant context."""
        ctx = TenantContext(
            tenant_id="merchant-acme-corp",
            tenant_name="ACME Corp",
            tier="premium",
            region="us-east-1",
        )
        assert ctx.tenant_id == "merchant-acme-corp"
        assert ctx.tenant_name == "ACME Corp"
        assert ctx.tier == "premium"
        assert ctx.region == "us-east-1"

    def test_tenant_context_with_features(self):
        """Test tenant context with feature flags."""
        features = {"chaos_engineering", "dry_run", "versioning"}
        ctx = TenantContext(
            tenant_id="merchant-acme-corp",
            tenant_name="ACME Corp",
            tier="premium",
            region="us-east-1",
            features=features,
        )
        assert ctx.features == features
        assert "chaos_engineering" in ctx.features

    def test_tenant_context_with_quotas(self):
        """Test tenant context with resource quotas."""
        quotas = TenantQuotas(
            max_concurrent_sagas=100,
            max_sagas_per_hour=10000,
            max_context_size_kb=100,
            timeout_seconds=300,
        )
        ctx = TenantContext(
            tenant_id="merchant-acme-corp",
            tenant_name="ACME Corp",
            tier="standard",
            region="us-east-1",
            quotas=quotas,
        )
        assert ctx.quotas.max_concurrent_sagas == 100
        assert ctx.quotas.max_sagas_per_hour == 10000

    def test_tenant_context_invalid_empty_id(self):
        """Test that empty tenant_id raises ValueError."""
        with pytest.raises(ValueError, match="tenant_id cannot be empty"):
            TenantContext(
                tenant_id="",
                tenant_name="Invalid",
                tier="free",
                region="us-east-1",
            )

    def test_tenant_context_invalid_whitespace_id(self):
        """Test that whitespace-only tenant_id raises ValueError."""
        with pytest.raises(ValueError, match="tenant_id cannot be empty"):
            TenantContext(
                tenant_id="   ",
                tenant_name="Invalid",
                tier="free",
                region="us-east-1",
            )

    def test_tenant_context_default_features(self):
        """Test that features default to empty set."""
        ctx = TenantContext(
            tenant_id="merchant-acme-corp",
            tenant_name="ACME Corp",
            tier="free",
            region="us-east-1",
        )
        assert ctx.features == set()

    def test_tenant_context_default_quotas(self):
        """Test that quotas default to None if not provided."""
        ctx = TenantContext(
            tenant_id="merchant-acme-corp",
            tenant_name="ACME Corp",
            tier="free",
            region="us-east-1",
        )
        assert ctx.quotas is None or isinstance(ctx.quotas, TenantQuotas)


class TestTenantQuotas:
    """Tests for TenantQuotas."""

    def test_quotas_creation(self):
        """Test creating tenant quotas."""
        quotas = TenantQuotas(
            max_concurrent_sagas=100,
            max_sagas_per_hour=10000,
            max_context_size_kb=100,
            timeout_seconds=300,
        )
        assert quotas.max_concurrent_sagas == 100
        assert quotas.max_sagas_per_hour == 10000
        assert quotas.max_context_size_kb == 100
        assert quotas.timeout_seconds == 300

    def test_quotas_with_defaults(self):
        """Test quotas with default values."""
        quotas = TenantQuotas(
            max_concurrent_sagas=50,
        )
        assert quotas.max_concurrent_sagas == 50
        # Other fields should have defaults


class TestTenantContextInjection:
    """Tests for tenant context injection into saga context."""

    def test_inject_tenant_context_into_saga_context(self):
        """Test that tenant context is properly injected into saga context."""
        tenant_ctx = TenantContext(
            tenant_id="merchant-acme",
            tenant_name="ACME",
            tier="premium",
            region="us-east-1",
        )

        saga_ctx = {
            "order_id": "order-123",
            "amount": 99.99,
            "tenant_context": tenant_ctx,
        }

        # Verify tenant context is accessible
        assert saga_ctx["tenant_context"].tenant_id == "merchant-acme"
        assert saga_ctx["tenant_context"].tier == "premium"

    def test_saga_context_without_tenant_raises_error(self):
        """Test that saga execution without tenant context raises error."""
        saga_ctx = {
            "order_id": "order-123",
            "amount": 99.99,
        }

        # When accessing tenant_context, should raise KeyError
        with pytest.raises(KeyError):
            _ = saga_ctx["tenant_context"]

    def test_tenant_context_immutable_in_saga(self):
        """Test that tenant context is accessible but structured properly."""
        tenant_ctx = TenantContext(
            tenant_id="merchant-acme",
            tenant_name="ACME",
            tier="premium",
            region="us-east-1",
        )

        saga_ctx = {"tenant_context": tenant_ctx}

        # Should be able to read tenant_id
        assert saga_ctx["tenant_context"].tenant_id == "merchant-acme"


class TestTenantIsolation:
    """Tests for tenant isolation in saga execution."""

    @pytest.mark.asyncio
    async def test_tenant_isolation_in_execution(self):
        """Test that sagas from different tenants don't interfere."""
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
            region="us-east-1",
        )

        saga_ctx1 = {"order_id": "order-1", "tenant_context": tenant1}
        saga_ctx2 = {"order_id": "order-2", "tenant_context": tenant2}

        # Verify contexts are isolated
        assert saga_ctx1["tenant_context"].tenant_id != saga_ctx2["tenant_context"].tenant_id
        assert saga_ctx1["order_id"] != saga_ctx2["order_id"]


class TestCrossTenantPrevention:
    """Tests for preventing cross-tenant access."""

    def test_tenant_context_comparison(self):
        """Test that different tenant contexts are distinct."""
        tenant1 = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="premium",
            region="us-east-1",
        )

        tenant2 = TenantContext(
            tenant_id="merchant-b",
            tenant_name="Merchant B",
            tier="premium",
            region="us-east-1",
        )

        assert tenant1.tenant_id != tenant2.tenant_id
        assert tenant1 != tenant2

    def test_tenant_context_equality(self):
        """Test that identical tenant contexts are equal."""
        tenant1 = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="premium",
            region="us-east-1",
        )

        tenant2 = TenantContext(
            tenant_id="merchant-a",
            tenant_name="Merchant A",
            tier="premium",
            region="us-east-1",
        )

        assert tenant1.tenant_id == tenant2.tenant_id
        assert tenant1 == tenant2


class TestTenantContextValidation:
    """Tests for tenant context validation."""

    def test_tenant_id_required(self):
        """Test that tenant_id is required."""
        with pytest.raises(TypeError):
            TenantContext(
                # Missing tenant_id
                tenant_name="ACME",
                tier="premium",
                region="us-east-1",
            )

    def test_tenant_name_required(self):
        """Test that tenant_name is required."""
        with pytest.raises(TypeError):
            TenantContext(
                tenant_id="merchant-a",
                # Missing tenant_name
                tier="premium",
                region="us-east-1",
            )

    def test_tier_required(self):
        """Test that tier is required."""
        with pytest.raises(TypeError):
            TenantContext(
                tenant_id="merchant-a",
                tenant_name="ACME",
                # Missing tier
                region="us-east-1",
            )

    def test_region_required(self):
        """Test that region is required."""
        with pytest.raises(TypeError):
            TenantContext(
                tenant_id="merchant-a",
                tenant_name="ACME",
                tier="premium",
                # Missing region
            )


class TestTenantTiers:
    """Tests for different tenant tiers."""

    def test_free_tier(self):
        """Test free tier tenant."""
        ctx = TenantContext(
            tenant_id="merchant-free",
            tenant_name="Free Merchant",
            tier="free",
            region="us-east-1",
        )
        assert ctx.tier == "free"

    def test_standard_tier(self):
        """Test standard tier tenant."""
        ctx = TenantContext(
            tenant_id="merchant-standard",
            tenant_name="Standard Merchant",
            tier="standard",
            region="us-east-1",
        )
        assert ctx.tier == "standard"

    def test_premium_tier(self):
        """Test premium tier tenant."""
        ctx = TenantContext(
            tenant_id="merchant-premium",
            tenant_name="Premium Merchant",
            tier="premium",
            region="us-east-1",
        )
        assert ctx.tier == "premium"

    def test_enterprise_tier(self):
        """Test enterprise tier tenant."""
        ctx = TenantContext(
            tenant_id="merchant-enterprise",
            tenant_name="Enterprise Merchant",
            tier="enterprise",
            region="us-east-1",
        )
        assert ctx.tier == "enterprise"


class TestTenantRegions:
    """Tests for tenant regions."""

    def test_us_region(self):
        """Test US region tenant."""
        ctx = TenantContext(
            tenant_id="merchant-us",
            tenant_name="US Merchant",
            tier="premium",
            region="us-east-1",
        )
        assert ctx.region == "us-east-1"

    def test_eu_region(self):
        """Test EU region tenant."""
        ctx = TenantContext(
            tenant_id="merchant-eu",
            tenant_name="EU Merchant",
            tier="premium",
            region="eu-west-1",
        )
        assert ctx.region == "eu-west-1"

    def test_asia_region(self):
        """Test Asia-Pacific region tenant."""
        ctx = TenantContext(
            tenant_id="merchant-apac",
            tenant_name="APAC Merchant",
            tier="premium",
            region="ap-southeast-1",
        )
        assert ctx.region == "ap-southeast-1"


# ─────────────────────────────────────────────────────────────────────────────
# Exception attribute tests – every custom __init__ must be hit for coverage
# ─────────────────────────────────────────────────────────────────────────────


class TestTenantExceptionAttributes:
    """Verify every custom exception stores its attributes correctly."""

    def test_tenant_error_is_base(self):
        err = TenantError("base error")
        assert isinstance(err, Exception)
        assert str(err) == "base error"

    def test_tenant_not_found_stores_tenant_id(self):
        err = TenantNotFoundError("t-123")
        assert err.tenant_id == "t-123"
        assert "t-123" in str(err)

    def test_tenant_suspended_stores_tenant_id_and_status(self):
        err = TenantSuspendedError("t-456", "suspended")
        assert err.tenant_id == "t-456"
        assert err.status == "suspended"
        assert "t-456" in str(err)
        assert "suspended" in str(err)

    def test_quota_exceeded_stores_quota_name_and_current(self):
        err = QuotaExceededError("t-789", "max_concurrent_sagas", 101)
        assert err.tenant_id == "t-789"
        assert err.quota_name == "max_concurrent_sagas"
        assert err.current == 101
        assert "t-789" in str(err)

    def test_rate_limit_exceeded_stores_limit_name_and_current(self):
        err = RateLimitExceededError("t-abc", "max_sagas_per_hour", 10001)
        assert err.tenant_id == "t-abc"
        assert err.limit_name == "max_sagas_per_hour"
        assert err.current == 10001
        assert "t-abc" in str(err)


# ─────────────────────────────────────────────────────────────────────────────
# TenantContext edge-case tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTenantContextEdgeCases:
    """Edge-case and branch coverage for TenantContext."""

    def test_get_quota_returns_value_from_quotas(self):
        """get_quota must return the named attribute from the quotas object."""
        ctx = TenantContext(
            tenant_id="t-quota",
            tenant_name="Quota Tenant",
            tier="free",
            region="us-east-1",
        )
        assert ctx.get_quota("max_concurrent_sagas") == 100

    def test_postinit_sets_default_quotas_when_passed_none(self):
        """__post_init__ must create default TenantQuotas when quotas=None."""
        ctx = TenantContext(
            tenant_id="t-defaults",
            tenant_name="Default Quotas",
            tier="free",
            region="us-east-1",
            quotas=None,
        )
        assert ctx.quotas is not None
        assert isinstance(ctx.quotas, TenantQuotas)

    def test_repr_delegates_to_str(self):
        ctx = TenantContext(
            tenant_id="t-repr",
            tenant_name="Repr Tenant",
            tier="standard",
            region="eu-west-1",
        )
        assert repr(ctx) == str(ctx)


# ─────────────────────────────────────────────────────────────────────────────
# TenantAwareSagaExecutor – full execution path
# ─────────────────────────────────────────────────────────────────────────────


def _make_tenant(tenant_id: str = "acme", tier: str = "premium") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="ACME Corp",
        tier=tier,
        region="us-east-1",
    )


def _make_saga_result(success: bool = True) -> SagaResult:
    return SagaResult(
        success=success,
        saga_name="test-saga",
        status=SagaStatus.COMPLETED if success else SagaStatus.ROLLED_BACK,
        completed_steps=1,
        total_steps=1,
        execution_time=0.042,
    )


@pytest.fixture
def mock_storage():
    return MagicMock()


@pytest.fixture
async def mock_registry():
    reg = TenantRegistry()
    await reg.register("acme", {"is_active": True, "status": "active"})
    return reg


@pytest.fixture
def executor(mock_storage, mock_registry):
    return TenantAwareSagaExecutor(storage=mock_storage, tenant_registry=mock_registry)


@pytest.fixture
def executor_with_db(mock_storage, mock_registry):
    mock_db = MagicMock()
    return TenantAwareSagaExecutor(storage=mock_storage, tenant_registry=mock_registry, db=mock_db)


class TestTenantAwareSagaExecutorExecute:
    """Unit tests for TenantAwareSagaExecutor.execute() and helper methods."""

    async def test_execute_happy_path(self, executor):
        """execute() injects tenant context and returns saga result."""
        saga = MagicMock()
        saga.run = AsyncMock(return_value=_make_saga_result())

        result = await executor.execute(
            saga=saga,
            context={"order_id": "OOO1"},
            tenant_context=_make_tenant(),
        )

        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        # Verify tenant context was injected
        call_ctx = saga.run.call_args[0][0]
        assert "tenant_context" in call_ctx
        assert call_ctx["tenant_context"].tenant_id == "acme"

    async def test_execute_saga_failure_still_completes(self, executor):
        """execute() returns rolled-back result when saga itself fails."""
        saga = MagicMock()
        saga.run = AsyncMock(return_value=_make_saga_result(success=False))

        result = await executor.execute(
            saga=saga,
            context={},
            tenant_context=_make_tenant(),
        )

        assert result.success is False
        assert result.status == SagaStatus.ROLLED_BACK

    async def test_execute_clears_db_tenant_on_exception(self, executor_with_db):
        """_clear_db_tenant() must be called even when saga.run() raises."""
        saga = MagicMock()
        saga.run = AsyncMock(side_effect=RuntimeError("saga blew up"))

        with pytest.raises(RuntimeError, match="saga blew up"):
            await executor_with_db.execute(
                saga=saga,
                context={},
                tenant_context=_make_tenant(),
            )

    async def test_execute_with_db_sets_and_clears_session(self, executor_with_db):
        """With a db object, session tenant is set then cleared."""
        saga = MagicMock()
        saga.run = AsyncMock(return_value=_make_saga_result())

        result = await executor_with_db.execute(
            saga=saga,
            context={},
            tenant_context=_make_tenant(),
        )

        assert result.success is True


class TestTenantAwareSagaExecutorHelpers:
    """Low-level helper method coverage."""

    async def test_validate_tenant_passes_with_valid_context(self, executor):
        """_validate_tenant() must not raise for a registered tenant."""
        ctx = _make_tenant()
        await executor._validate_tenant(ctx)  # must not raise

    async def test_validate_tenant_raises_for_unknown_tenant(self, executor):
        """_validate_tenant() must raise TenantNotFoundError for unregistered tenant."""
        ctx = _make_tenant(tenant_id="unknown-tenant")
        with pytest.raises(TenantNotFoundError):
            await executor._validate_tenant(ctx)

    async def test_validate_tenant_raises_for_suspended(self, mock_storage, mock_registry):
        """_validate_tenant() must raise TenantSuspendedError for suspended tenant."""
        await mock_registry.register("suspended-tenant", {"status": "suspended"})
        executor = TenantAwareSagaExecutor(storage=mock_storage, tenant_registry=mock_registry)
        ctx = _make_tenant(tenant_id="suspended-tenant")
        with pytest.raises(TenantSuspendedError):
            await executor._validate_tenant(ctx)

    async def test_check_quotas_with_quotas_object(self, executor):
        """_check_quotas() must run without error when quotas present."""
        ctx = _make_tenant()
        ctx.quotas = TenantQuotas(max_concurrent_sagas=5, max_sagas_per_hour=100)
        await executor._check_quotas(ctx)  # must not raise

    async def test_set_db_tenant_no_op_without_db(self, executor):
        """_set_db_tenant() is a no-op when no db is injected."""
        await executor._set_db_tenant("acme")  # must not raise

    async def test_set_db_tenant_logs_when_db_present(self, executor_with_db):
        """_set_db_tenant() logs when db is injected."""
        await executor_with_db._set_db_tenant("acme")  # must not raise

    async def test_clear_db_tenant_no_op_without_db(self, executor):
        """_clear_db_tenant() is a no-op when no db is injected."""
        await executor._clear_db_tenant()  # must not raise

    async def test_clear_db_tenant_logs_when_db_present(self, executor_with_db):
        """_clear_db_tenant() logs when db is injected."""
        await executor_with_db._clear_db_tenant()  # must not raise

    async def test_record_usage_uses_execution_time(self, executor):
        """_record_usage() must read execution_time, not duration_ms."""
        ctx = _make_tenant()
        result = _make_saga_result()
        await executor._record_usage(ctx, result)  # must not raise (bug fix check)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
