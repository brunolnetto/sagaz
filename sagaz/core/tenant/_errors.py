"""Exceptions raised by multi-tenant isolation (ADR-020)."""

from __future__ import annotations


class TenantError(Exception):
    """Base class for tenant errors."""


class InvalidTenantIdError(TenantError, ValueError):
    """Raised when a tenant id does not match the allowed format."""

    def __init__(self, tenant_id: object) -> None:
        super().__init__(
            f"Invalid tenant id {tenant_id!r}: use 1-63 characters from a-z, 0-9, '-', '_' "
            "and '.', starting with a letter or digit"
        )
        self.tenant_id = tenant_id


class TenantNotFoundError(TenantError, KeyError):
    """Raised when a tenant is not registered."""

    def __init__(self, tenant_id: str) -> None:
        super().__init__(f"Tenant '{tenant_id}' is not registered")
        self.tenant_id = tenant_id

    def __str__(self) -> str:
        return str(self.args[0])


class TenantSuspendedError(TenantError):
    """Raised when a suspended tenant tries to run a saga."""

    def __init__(self, tenant_id: str) -> None:
        super().__init__(f"Tenant '{tenant_id}' is suspended")
        self.tenant_id = tenant_id


class QuotaExceededError(TenantError):
    """Raised when running a saga would exceed one of the tenant's quotas."""

    def __init__(self, tenant_id: str, quota: str, limit: float, current: float) -> None:
        super().__init__(
            f"Tenant '{tenant_id}' exceeded quota '{quota}': {current:g} > limit {limit:g}"
        )
        self.tenant_id = tenant_id
        self.quota = quota
        self.limit = limit
        self.current = current


class CrossTenantAccessError(TenantError):
    """Raised when a record of one tenant is accessed from another tenant's scope."""

    def __init__(self, record_tenant: str, current_tenant: str) -> None:
        super().__init__(
            f"Record belongs to tenant '{record_tenant}', "
            f"but the current scope is '{current_tenant}'"
        )
        self.record_tenant = record_tenant
        self.current_tenant = current_tenant
