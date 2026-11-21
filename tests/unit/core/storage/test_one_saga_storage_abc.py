"""There is one ``SagaStorage``: the exported class is the backends' base (#599)."""

from __future__ import annotations

import pytest

from sagaz.core.storage import InMemorySagaStorage, SagaStorage
from sagaz.core.storage import base as legacy_path
from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage
from sagaz.core.storage.backends.redis.saga import RedisSagaStorage
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
from sagaz.core.storage.core import TransferError
from sagaz.core.storage.interfaces import SagaStepState
from sagaz.core.storage.interfaces.saga import implements
from sagaz.core.storage.migration import _storage_checksum
from sagaz.core.storage.transfer.service import TransferService
from sagaz.core.tenant.encryption._storage import EncryptedSagaStorage


class MinimalStorage(SagaStorage):
    """A third-party storage: the abstract methods only, no transfer support."""

    async def save_saga_state(self, *args, **kwargs): ...

    async def load_saga_state(self, saga_id): ...

    async def delete_saga_state(self, saga_id): ...

    async def list_sagas(self, *args, **kwargs): ...

    async def update_step_state(self, *args, **kwargs): ...

    async def get_saga_statistics(self): ...

    async def cleanup_completed_sagas(self, *args, **kwargs): ...

    async def health_check(self): ...


def test_the_old_import_path_gives_the_same_classes():
    assert legacy_path.SagaStorage is SagaStorage
    assert legacy_path.SagaStepState is SagaStepState


@pytest.mark.parametrize(
    "backend",
    [
        InMemorySagaStorage,
        SQLiteSagaStorage,
        PostgreSQLSagaStorage,
        RedisSagaStorage,
        EncryptedSagaStorage,
    ],
)
def test_every_backend_is_a_saga_storage(backend):
    assert issubclass(backend, SagaStorage)


def test_an_instance_passes_isinstance_with_the_exported_name():
    assert isinstance(InMemorySagaStorage(), SagaStorage)


def test_implements_tells_a_real_method_from_the_default():
    assert implements(InMemorySagaStorage(), "export_all")
    assert not implements(MinimalStorage(), "export_all")
    assert not implements(MinimalStorage(), "import_record")
    assert not implements(object(), "export_all")


async def test_transfer_from_a_storage_without_export_says_so():
    service = TransferService(MinimalStorage(), InMemorySagaStorage())
    with pytest.raises(TransferError, match="does not support export"):
        async for _ in service._export_records():
            pass


async def test_transfer_into_a_storage_without_import_says_so():
    service = TransferService(InMemorySagaStorage(), MinimalStorage())
    with pytest.raises(TransferError, match="does not support import"):
        await service._transfer_record({"saga_id": "s"})


async def test_checksum_of_a_storage_without_export_says_so():
    with pytest.raises(TypeError, match="does not support export_all"):
        await _storage_checksum(MinimalStorage())
