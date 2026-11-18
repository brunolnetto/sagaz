"""Transfers and `sagaz migrate` across tenants (ADR-020, #54)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from sagaz.cli.migrate import migrate_cmd
from sagaz.core.storage import create_storage_manager
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.storage.core import TransferError
from sagaz.core.storage.transfer import TransferConfig, TransferService
from sagaz.core.tenant import system_scope, tenant_scope
from sagaz.core.types import SagaStatus


async def _save(storage, tenant, saga_id="s1", name="order"):
    with tenant_scope(tenant):
        await storage.save_saga_state(saga_id, name, SagaStatus.COMPLETED, [], {"t": tenant})


async def test_validation_looks_records_up_in_their_own_tenant(monkeypatch):
    source, target = InMemorySagaStorage(), InMemorySagaStorage()
    await _save(source, "acme")
    await _save(target, "globex")  # same saga id, other tenant

    async def lost_import(record):
        return None  # the import silently does nothing

    monkeypatch.setattr(target, "import_record", lost_import)
    service = TransferService(source, target, TransferConfig(validate=True, batch_size=10))

    with system_scope():
        result = await service.transfer_all()

    # globex's s1 must not satisfy acme's s1: validation rejects the record
    # (the default error policy skips it instead of aborting the transfer).
    assert result.transferred == 0
    assert any("record s1 not found in target" in error for error in result.errors)


async def test_transfer_in_the_system_scope_keeps_every_tenant():
    source, target = InMemorySagaStorage(), InMemorySagaStorage()
    for tenant in ("default", "acme", "globex"):
        await _save(source, tenant)

    with system_scope():
        result = await TransferService(source, target, TransferConfig(validate=True)).transfer_all()

    assert (result.transferred, result.failed) == (3, 0)
    for tenant in ("default", "acme", "globex"):
        with tenant_scope(tenant):
            assert (await target.load_saga_state("s1"))["context"] == {"t": tenant}


@pytest.fixture
def sqlite_urls(tmp_path):
    return f"sqlite://{tmp_path / 'source.db'}", f"sqlite://{tmp_path / 'target.db'}"


async def _seed_sqlite(url):
    async with create_storage_manager(url=url) as manager:
        for tenant in ("default", "acme"):
            await _save(manager.saga, tenant)


async def _load_all(url):
    async with create_storage_manager(url=url) as manager:
        with system_scope():
            return sorted([(r["tenant_id"], r["saga_id"]) async for r in manager.saga.export_all()])


def test_migrate_cli_moves_every_tenant(sqlite_urls):
    import asyncio

    source, target = sqlite_urls
    asyncio.run(_seed_sqlite(source))

    result = CliRunner().invoke(migrate_cmd, ["run", "--source", source, "--target", target])

    assert result.exit_code == 0, result.output
    assert asyncio.run(_load_all(target)) == [("acme", "s1"), ("default", "s1")]
    status = CliRunner().invoke(migrate_cmd, ["status", "--source", source])
    assert "sagas=2" in status.output
