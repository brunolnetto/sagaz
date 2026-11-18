"""Registry of tenants, optionally persisted to saga storage (ADR-020).

Persisted tenants are stored as records under the reserved saga name
:data:`TENANT_RECORD_SAGA_NAME`, always in the default tenant's partition, so
any process (including the ``sagaz tenant`` CLI) sharing the storage sees them.
"""

from __future__ import annotations

from typing import Any

from sagaz.core.tenant._context import DEFAULT_TENANT, TenantContext, TenantQuotas
from sagaz.core.tenant._errors import TenantError, TenantNotFoundError
from sagaz.core.tenant._scope import tenant_scope
from sagaz.core.types import SagaStatus

#: Saga name under which tenant registrations are stored in saga storage.
TENANT_RECORD_SAGA_NAME = "__sagaz_tenants__"


def _record_id(tenant_id: str) -> str:
    return f"{TENANT_RECORD_SAGA_NAME}:{tenant_id}"


class TenantRegistry:
    """Known tenants, their plans, quotas and status."""

    def __init__(self, storage: Any | None = None) -> None:
        self._tenants: dict[str, TenantContext] = {}
        self._storage = storage

    # ── persistence ──

    @classmethod
    async def from_storage(cls, storage: Any) -> TenantRegistry:
        """Create a registry bound to ``storage`` and load its tenants."""
        registry = cls(storage)
        await registry.load()
        return registry

    def _require_storage(self) -> Any:
        if self._storage is None:
            msg = "This registry has no storage: TenantRegistry(storage=...)"
            raise ValueError(msg)
        return self._storage

    async def load(self) -> int:
        """Replace in-memory tenants with the persisted ones; return how many."""
        storage = self._require_storage()
        loaded: dict[str, TenantContext] = {}
        with tenant_scope(DEFAULT_TENANT):
            summaries = await storage.list_sagas(saga_name=TENANT_RECORD_SAGA_NAME, limit=100_000)
            for summary in summaries:
                state = await storage.load_saga_state(summary["saga_id"])
                if state:
                    tenant = TenantContext.from_dict(state["context"])
                    loaded[tenant.tenant_id] = tenant
        self._tenants = loaded
        return len(loaded)

    async def save(self) -> int:
        """Persist every tenant and delete removed ones; return how many are stored."""
        storage = self._require_storage()
        with tenant_scope(DEFAULT_TENANT):
            stored = await storage.list_sagas(saga_name=TENANT_RECORD_SAGA_NAME, limit=100_000)
            wanted = {_record_id(tenant_id) for tenant_id in self._tenants}
            for summary in stored:
                if summary["saga_id"] not in wanted:
                    await storage.delete_saga_state(summary["saga_id"])
            for tenant in self._tenants.values():
                await storage.save_saga_state(
                    _record_id(tenant.tenant_id),
                    TENANT_RECORD_SAGA_NAME,
                    SagaStatus.COMPLETED,
                    [],
                    tenant.to_dict(),
                )
        return len(self._tenants)

    # ── read ──

    def get(self, tenant_id: str) -> TenantContext:
        try:
            return self._tenants[tenant_id]
        except KeyError:
            raise TenantNotFoundError(tenant_id) from None

    def list(self) -> list[TenantContext]:
        return sorted(self._tenants.values(), key=lambda tenant: tenant.tenant_id)

    def __contains__(self, tenant_id: object) -> bool:
        return tenant_id in self._tenants

    # ── write ──

    def register(self, tenant: TenantContext) -> TenantContext:
        if tenant.tenant_id in self._tenants:
            msg = f"Tenant '{tenant.tenant_id}' is already registered"
            raise TenantError(msg)
        self._tenants[tenant.tenant_id] = tenant
        return tenant

    def replace(self, tenant: TenantContext) -> TenantContext:
        """Store a new version of an existing tenant."""
        self.get(tenant.tenant_id)
        self._tenants[tenant.tenant_id] = tenant
        return tenant

    def set_quotas(self, tenant_id: str, quotas: TenantQuotas) -> TenantContext:
        current = self.get(tenant_id)
        return self.replace(
            TenantContext.from_dict({**current.to_dict(), "quotas": quotas.to_dict()})
        )

    def set_active(self, tenant_id: str, active: bool) -> TenantContext:
        current = self.get(tenant_id)
        return self.replace(TenantContext.from_dict({**current.to_dict(), "active": active}))

    def delete(self, tenant_id: str) -> TenantContext:
        tenant = self.get(tenant_id)
        del self._tenants[tenant_id]
        return tenant
