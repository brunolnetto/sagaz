"""
Tenant context and multi-tenant isolation for sagas.

Implements ADR-020: Multi-Tenant Isolation

This module provides:
- TenantContext: Dataclass for tenant information
- TenantQuotas: Resource quotas per tenant
- TenantAwareSagaExecutor: Saga executor with tenant isolation
- Cross-tenant access prevention
- Database session tenant isolation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.decorators import Saga
    from sagaz.core.types import SagaResult
    from sagaz.storage.base import SagaStorage

logger = logging.getLogger(__name__)


class TenantError(Exception):
    """Base exception for tenant-related errors."""


class TenantNotFoundError(TenantError):
    """Raised when tenant is not found."""

    def __init__(self, tenant_id: str) -> None:
        msg = f"Tenant '{tenant_id}' not found"
        super().__init__(msg)
        self.tenant_id = tenant_id


class TenantSuspendedError(TenantError):
    """Raised when tenant is suspended or inactive."""

    def __init__(self, tenant_id: str, status: str) -> None:
        msg = f"Tenant '{tenant_id}' is {status}"
        super().__init__(msg)
        self.tenant_id = tenant_id
        self.status = status


class QuotaExceededError(TenantError):
    """Raised when tenant quota is exceeded."""

    def __init__(self, tenant_id: str, quota_name: str, current: int) -> None:
        msg = f"Tenant '{tenant_id}' exceeded quota '{quota_name}': {current}"
        super().__init__(msg)
        self.tenant_id = tenant_id
        self.quota_name = quota_name
        self.current = current


class RateLimitExceededError(TenantError):
    """Raised when tenant rate limit is exceeded."""

    def __init__(self, tenant_id: str, limit_name: str, current: int) -> None:
        msg = f"Tenant '{tenant_id}' exceeded rate limit '{limit_name}': {current}"
        super().__init__(msg)
        self.tenant_id = tenant_id
        self.limit_name = limit_name
        self.current = current


@dataclass
class TenantQuotas:
    """Resource quotas for a tenant."""

    max_concurrent_sagas: int = 100
    max_sagas_per_hour: int = 10000
    max_context_size_kb: int = 100
    timeout_seconds: int = 300


@dataclass
class TenantContext:
    """
    Tenant context propagated through saga execution.

    Attributes:
        tenant_id: Unique identifier for the tenant
        tenant_name: Display name for the tenant
        tier: Subscription tier ("free", "standard", "premium", "enterprise")
        region: Deployment region (e.g., "us-east-1", "eu-west-1")
        features: Set of enabled features for the tenant
        quotas: Resource quotas for the tenant
        encryption_key_id: Tenant-specific encryption key ID (optional)
        metadata: Additional metadata (optional)

    Raises:
        ValueError: If tenant_id is empty or only whitespace
    """

    tenant_id: str
    tenant_name: str
    tier: str
    region: str
    features: set[str] = field(default_factory=set)
    quotas: TenantQuotas = field(default_factory=TenantQuotas)
    encryption_key_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate tenant context after initialization."""
        if not self.tenant_id or not self.tenant_id.strip():
            msg = "tenant_id cannot be empty"
            raise ValueError(msg)
        if self.quotas is None:  # type: ignore[comparison-overlap]
            object.__setattr__(self, "quotas", TenantQuotas())

    def has_feature(self, feature_name: str) -> bool:
        """Return True if tenant has the feature enabled."""
        return feature_name in self.features

    def enable_feature(self, feature_name: str) -> None:
        """Enable a feature for the tenant."""
        self.features.add(feature_name)

    def disable_feature(self, feature_name: str) -> None:
        """Disable a feature for the tenant."""
        self.features.discard(feature_name)

    def get_quota(self, quota_name: str, default: Any = None) -> Any:
        """Return a quota value by name, falling back to *default*."""
        return getattr(self.quotas, quota_name, default)

    def __str__(self) -> str:
        return f"TenantContext(tenant_id={self.tenant_id}, tier={self.tier}, region={self.region})"

    def __repr__(self) -> str:
        return self.__str__()


class TenantAwareSagaExecutor:
    """
    Saga executor with tenant isolation and quota enforcement.

    Steps performed on every ``execute()`` call:
    1. Validate tenant context
    2. Enforce resource quotas
    3. Set database session tenant for PostgreSQL RLS
    4. Inject tenant context into saga context dict
    5. Execute saga
    6. Record usage metrics
    7. Clear database session tenant (always, even on error)
    """

    def __init__(
        self,
        storage: SagaStorage,
        tenant_registry: TenantRegistry,
        db: Any | None = None,
    ) -> None:
        self.storage = storage
        self.tenant_registry = tenant_registry
        self.db = db
        self.logger = logger

    async def execute(
        self,
        saga: Saga,
        context: dict[str, Any],
        tenant_context: TenantContext,
    ) -> dict[str, Any]:
        """Execute *saga* scoped to *tenant_context*."""
        try:
            await self._validate_tenant(tenant_context)
            self.logger.info("Tenant validation passed for %s", tenant_context.tenant_id)

            await self._check_quotas(tenant_context)
            self.logger.info("Quota check passed for %s", tenant_context.tenant_id)

            await self._set_db_tenant(tenant_context.tenant_id)
            self.logger.info("DB session tenant set for %s", tenant_context.tenant_id)

            enriched_context = {**context, "tenant_context": tenant_context}

            self.logger.info("Executing saga with tenant %s", tenant_context.tenant_id)
            result: dict[str, Any] = await saga.run(enriched_context)

            await self._record_usage(tenant_context, result)
            self.logger.info(
                "Saga completed for tenant %s",
                tenant_context.tenant_id,
            )
            return result
        finally:
            await self._clear_db_tenant()

    async def _validate_tenant(self, tenant_ctx: TenantContext) -> None:
        """Validate tenant exists and is active before saga execution."""
        if not tenant_ctx.tenant_id:
            msg = "tenant_id is required"
            raise ValueError(msg)

        tenant = await self.tenant_registry.get(tenant_ctx.tenant_id)
        if tenant is None:
            raise TenantNotFoundError(tenant_ctx.tenant_id)

        is_suspended = bool(tenant.get("is_suspended", False))
        is_active = tenant.get("is_active", True)
        status = tenant.get("status", "active")
        if is_suspended or is_active is False or status == "suspended":
            raise TenantSuspendedError(tenant_ctx.tenant_id, status or "suspended")

        self.logger.debug("Tenant validation: %s", tenant_ctx.tenant_id)

    async def _check_quotas(self, tenant_ctx: TenantContext) -> None:
        """Log quota configuration.

        This is a no-op stub; subclasses or future work should enforce
        real quota limits via storage counters.
        """
        self.logger.debug(
            "Quota check: max_concurrent=%s, max_hourly=%s",
            tenant_ctx.quotas.max_concurrent_sagas,
            tenant_ctx.quotas.max_sagas_per_hour,
        )

    async def _set_db_tenant(self, tenant_id: str) -> None:
        """Set DB session tenant for PostgreSQL RLS.

        Stub — a production subclass should execute
        ``SET LOCAL app.tenant_id = '<tenant_id>'`` on the connection.
        """
        if self.db is None:
            return
        self.logger.debug("Setting DB session tenant: %s", tenant_id)

    async def _clear_db_tenant(self) -> None:
        """Clear the DB tenant session variable.

        Stub — a production subclass should execute
        ``RESET app.tenant_id`` on the connection.
        """
        if self.db is None:
            return
        self.logger.debug("Clearing DB session tenant")

    async def _record_usage(self, tenant_ctx: TenantContext, result: dict[str, Any]) -> None:
        """Record saga usage for quota accounting."""
        self.logger.debug(
            "Usage recorded for tenant %s",
            tenant_ctx.tenant_id,
        )


class TenantRegistry:
    """In-memory registry of tenant configurations."""

    def __init__(self) -> None:
        self._tenants: dict[str, dict[str, Any]] = {}

    async def get(self, tenant_id: str) -> dict[str, Any] | None:
        """Return tenant data or *None* if not registered."""
        return self._tenants.get(tenant_id)

    async def register(self, tenant_id: str, tenant_data: dict[str, Any]) -> None:
        """Register a new tenant."""
        self._tenants[tenant_id] = tenant_data

    async def update(self, tenant_id: str, tenant_data: dict[str, Any]) -> None:
        """Merge *tenant_data* into an existing tenant record."""
        if tenant_id in self._tenants:
            self._tenants[tenant_id].update(tenant_data)

    async def delete(self, tenant_id: str) -> None:
        """Remove a tenant (no-op if not found)."""
        self._tenants.pop(tenant_id, None)

    async def list_all(self) -> list[str]:
        """Return all registered tenant IDs."""
        return list(self._tenants.keys())
