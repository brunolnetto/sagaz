"""Tenant scenarios on the in-memory saga storage (ADR-020)."""

from __future__ import annotations

from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from tests.unit.core.storage.backends import _saga_tenancy_scenarios as scenarios


async def test_reserved_records_survive_cleanup():
    await scenarios.reserved_records_survive_cleanup(InMemorySagaStorage())
