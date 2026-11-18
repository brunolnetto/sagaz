"""Helpers for writing transferred saga records into their own tenant (ADR-020)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sagaz.core.storage._tenancy import TENANT_FIELD, write_tenant
from sagaz.core.tenant import tenant_scope


@contextmanager
def record_tenant_scope(record: dict[str, Any]) -> Iterator[str]:
    """Run the enclosed writes as the tenant ``record`` belongs to.

    Used by ``import_record``: in the system scope the record keeps its own
    ``tenant_id`` (``"default"`` when it has none); in a tenant scope it is
    written to that tenant, and a record naming another tenant is rejected.
    """
    with tenant_scope(write_tenant(record.get(TENANT_FIELD))) as tenant_id:
        yield tenant_id
