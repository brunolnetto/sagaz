"""Multi-tenant isolation (ADR-020).

Run code as a tenant with :func:`tenant_scope` (or ``Saga.run(...,
tenant_context=...)``); storage backends scope every read and write to
:func:`current_tenant_id`. Code that sets no tenant runs as
:data:`DEFAULT_TENANT`, and :func:`system_scope` spans every tenant for
infrastructure such as the outbox worker.
"""

from sagaz.core.tenant._context import (
    DEFAULT_TENANT,
    SYSTEM_TENANT,
    TenantContext,
    TenantQuotas,
    validate_tenant_id,
)
from sagaz.core.tenant._errors import (
    CrossTenantAccessError,
    InvalidTenantIdError,
    QuotaExceededError,
    TenantError,
    TenantNotFoundError,
    TenantSuspendedError,
)
from sagaz.core.tenant._quotas import QuotaEnforcer, capped_retries, capped_timeout, quota_enforcer
from sagaz.core.tenant._registry import TENANT_RECORD_SAGA_NAME, TenantRegistry
from sagaz.core.tenant._scope import (
    current_tenant_context,
    current_tenant_id,
    ensure_tenant_access,
    is_system_scope,
    system_scope,
    tenant_scope,
)

__all__ = [
    "DEFAULT_TENANT",
    "SYSTEM_TENANT",
    "TENANT_RECORD_SAGA_NAME",
    "CrossTenantAccessError",
    "InvalidTenantIdError",
    "QuotaEnforcer",
    "QuotaExceededError",
    "TenantContext",
    "TenantError",
    "TenantNotFoundError",
    "TenantQuotas",
    "TenantRegistry",
    "TenantSuspendedError",
    "capped_retries",
    "capped_timeout",
    "current_tenant_context",
    "current_tenant_id",
    "ensure_tenant_access",
    "is_system_scope",
    "quota_enforcer",
    "system_scope",
    "tenant_scope",
    "validate_tenant_id",
]
