"""Tenant identity and quotas (ADR-020)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from sagaz.core.tenant._errors import InvalidTenantIdError

#: Tenant used when no tenant is set, so single-tenant code and data keep working.
DEFAULT_TENANT = "default"

#: Pseudo-tenant of :func:`sagaz.core.tenant.system_scope` (infrastructure that
#: must see every tenant, such as the outbox worker). Never a valid tenant id.
SYSTEM_TENANT = "*"

_TENANT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,62}")


def validate_tenant_id(tenant_id: object) -> str:
    """Return ``tenant_id`` if it is a valid tenant id, else raise.

    The format is safe to embed in Redis keys, PostgreSQL settings and file
    names: lowercase letters, digits, ``-``, ``_`` and ``.``, 1-63 characters.
    """
    if not isinstance(tenant_id, str) or not _TENANT_ID.fullmatch(tenant_id):
        raise InvalidTenantIdError(tenant_id)
    return tenant_id


@dataclass(frozen=True)
class TenantQuotas:
    """Per-tenant resource limits; ``None`` means unlimited.

    Attributes:
        max_concurrent_sagas: Sagas of this tenant that may run at once in this
            process.
        max_step_duration_seconds: Upper bound applied to every step timeout.
        max_retries: Upper bound applied to every step's retry count.
    """

    max_concurrent_sagas: int | None = None
    max_step_duration_seconds: float | None = None
    max_retries: int | None = None

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value is not None and value < 0:
                msg = f"Quota '{name}' must be >= 0 or None, got {value}"
                raise ValueError(msg)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TenantQuotas:
        return cls(**(data or {}))


@dataclass(frozen=True)
class TenantContext:
    """A tenant as seen by saga execution and storage.

    Attributes:
        tenant_id: Unique, validated identifier (see :func:`validate_tenant_id`).
        plan: Free-form plan or tier name (e.g. ``"free"``, ``"premium"``).
        quotas: Resource limits enforced while this tenant's sagas run.
        active: Suspended tenants (``False``) cannot run sagas.
        name: Optional display name.
        metadata: Free-form, JSON-serializable attributes.
    """

    tenant_id: str
    plan: str = "standard"
    quotas: TenantQuotas = field(default_factory=TenantQuotas)
    active: bool = True
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_tenant_id(self.tenant_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "plan": self.plan,
            "quotas": self.quotas.to_dict(),
            "active": self.active,
            "name": self.name,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenantContext:
        return cls(
            tenant_id=data["tenant_id"],
            plan=data.get("plan", "standard"),
            quotas=TenantQuotas.from_dict(data.get("quotas")),
            active=data.get("active", True),
            name=data.get("name"),
            metadata=dict(data.get("metadata") or {}),
        )
