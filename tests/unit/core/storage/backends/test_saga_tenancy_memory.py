"""Tenant scenarios on the in-memory saga storage (ADR-020)."""

from __future__ import annotations

from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from tests.unit.core.storage.backends import _saga_tenancy_scenarios as scenarios


async def test_reserved_records_survive_cleanup():
    await scenarios.reserved_records_survive_cleanup(InMemorySagaStorage())


def test_sagaz_registries_use_the_reserved_prefix():
    from sagaz.core.storage._reserved import is_reserved_saga_name
    from sagaz.core.tenant._registry import TENANT_RECORD_SAGA_NAME
    from sagaz.versioning.registry import VERSION_RECORD_SAGA_NAME

    assert is_reserved_saga_name(TENANT_RECORD_SAGA_NAME)
    assert is_reserved_saga_name(VERSION_RECORD_SAGA_NAME)
    assert not is_reserved_saga_name("OrderSaga")
    assert not is_reserved_saga_name(None)
