"""EncryptedSagaStorage over real backends (ADR-020, phase 2)."""

from __future__ import annotations

import base64
import json

import pytest

# Encryption needs the optional "cryptography" package (sagaz[encryption]).
pytest.importorskip("cryptography")

from sagaz import Saga, action  # noqa: E402
from sagaz.core.config import SagaConfig  # noqa: E402
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage  # noqa: E402
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage  # noqa: E402
from sagaz.core.tenant import (  # noqa: E402
    TenantContext,
    TenantDecryptionError,
    TenantKeyError,
    TenantRegistry,
    system_scope,
    tenant_scope,
)
from sagaz.core.tenant.encryption import (  # noqa: E402
    ENVELOPE_FIELD,
    EncryptedSagaStorage,
    EnvKeyProvider,
    is_encrypted,
)
from sagaz.core.types import SagaStatus, SagaStepStatus  # noqa: E402

SECRET = "123-45-6789"
KEYS = {
    "SAGAZ_TENANT_KEY_ACME": base64.b64encode(b"a" * 32).decode(),
    "SAGAZ_TENANT_KEY_GLOBEX": base64.b64encode(b"g" * 32).decode(),
    "SAGAZ_TENANT_KEY_DEFAULT": base64.b64encode(b"d" * 32).decode(),
}
STEPS = [{"name": "charge", "status": "completed", "result": {"card": SECRET}}]


@pytest.fixture(params=["memory", "sqlite"])
async def inner(request, tmp_path):
    if request.param == "memory":
        yield InMemorySagaStorage()
        return
    async with SQLiteSagaStorage(str(tmp_path / "sagas.db")) as storage:
        yield storage


@pytest.fixture
def storage(inner):
    return EncryptedSagaStorage(inner, EnvKeyProvider(KEYS))


async def _save(storage, tenant="acme", saga_id="s1", context=None):
    with tenant_scope(tenant):
        await storage.save_saga_state(
            saga_id, "PatientSaga", SagaStatus.COMPLETED, STEPS, context or {"ssn": SECRET}
        )


async def _raw(inner, tenant="acme", saga_id="s1"):
    with tenant_scope(tenant):
        return await inner.load_saga_state(saga_id)


class TestAtRest:
    async def test_context_and_step_results_are_encrypted_in_the_backend(self, storage, inner):
        await _save(storage)

        raw = await _raw(inner)
        assert is_encrypted(raw["context"])
        assert is_encrypted(raw["steps"][0]["result"])
        assert SECRET not in json.dumps(raw, default=str)
        # What listing and statistics need stays readable.
        assert (raw["saga_name"], raw["status"], raw["steps"][0]["name"]) == (
            "PatientSaga",
            "completed",
            "charge",
        )

    async def test_load_returns_plaintext(self, storage):
        await _save(storage)
        with tenant_scope("acme"):
            loaded = await storage.load_saga_state("s1")
        assert loaded["context"] == {"ssn": SECRET}
        assert loaded["steps"][0]["result"] == {"card": SECRET}

    async def test_missing_saga(self, storage):
        assert await storage.load_saga_state("nope") is None

    async def test_sqlite_file_contains_no_plaintext(self, tmp_path):
        path = tmp_path / "raw.db"
        async with SQLiteSagaStorage(str(path)) as inner:
            await _save(EncryptedSagaStorage(inner, EnvKeyProvider(KEYS)))
        assert SECRET.encode() not in path.read_bytes()


class TestTenantKeys:
    async def test_tenants_use_their_own_keys_for_the_same_saga_id(self, storage, inner):
        await _save(storage, "acme", context={"ssn": "acme-secret"})
        await _save(storage, "globex", context={"ssn": "globex-secret"})

        acme, globex = await _raw(inner, "acme"), await _raw(inner, "globex")
        assert acme["context"][ENVELOPE_FIELD]["ct"] != globex["context"][ENVELOPE_FIELD]["ct"]
        for tenant in ("acme", "globex"):
            with tenant_scope(tenant):
                assert (await storage.load_saga_state("s1"))["context"]["ssn"] == f"{tenant}-secret"

    async def test_ciphertext_copied_to_another_tenant_does_not_decrypt(self, storage, inner):
        await _save(storage, "acme")
        stolen = (await _raw(inner, "acme"))["context"]
        with tenant_scope("globex"):
            await inner.save_saga_state("s1", "PatientSaga", SagaStatus.COMPLETED, [], stolen)
            with pytest.raises(TenantDecryptionError):
                await storage.load_saga_state("s1")

    async def test_ciphertext_copied_to_another_saga_does_not_decrypt(self, storage, inner):
        await _save(storage, "acme")
        stolen = (await _raw(inner, "acme"))["context"]
        with tenant_scope("acme"):
            await inner.save_saga_state("s2", "PatientSaga", SagaStatus.COMPLETED, [], stolen)
            with pytest.raises(TenantDecryptionError):
                await storage.load_saga_state("s2")

    async def test_tenant_without_a_key_cannot_write(self, inner):
        storage = EncryptedSagaStorage(inner, EnvKeyProvider({}))
        with pytest.raises(TenantKeyError):
            await _save(storage)
        with tenant_scope("acme"):
            assert await inner.load_saga_state("s1") is None  # nothing written in clear


class TestCompatibility:
    async def test_plaintext_records_stay_readable_and_are_encrypted_on_save(self, storage, inner):
        with tenant_scope("acme"):
            await inner.save_saga_state("old", "Legacy", SagaStatus.COMPLETED, [], {"a": 1})
            assert (await storage.load_saga_state("old"))["context"] == {"a": 1}
            await storage.save_saga_state("old", "Legacy", SagaStatus.COMPLETED, [], {"a": 1})
            assert is_encrypted((await inner.load_saga_state("old"))["context"])

    async def test_reserved_records_stay_plaintext(self, storage, inner):
        registry = TenantRegistry(storage)
        registry.register(TenantContext("acme", plan="premium"))
        await registry.save()

        # The CLI reads the registry without keys.
        assert (await TenantRegistry.from_storage(inner)).get("acme").plan == "premium"
        assert (await TenantRegistry.from_storage(storage)).get("acme").plan == "premium"

    async def test_default_tenant_is_encrypted_too(self, storage, inner):
        await storage.save_saga_state("s1", "X", SagaStatus.COMPLETED, [], {"ssn": SECRET})
        assert is_encrypted((await inner.load_saga_state("s1"))["context"])


class TestSteps:
    async def test_update_step_state_encrypts_the_result(self, storage, inner):
        await _save(storage)
        with tenant_scope("acme"):
            await storage.update_step_state("s1", "charge", SagaStepStatus.COMPLETED, {"x": SECRET})
            assert is_encrypted((await inner.load_saga_state("s1"))["steps"][0]["result"])
            assert (await storage.load_saga_state("s1"))["steps"][0]["result"] == {"x": SECRET}

    async def test_status_only_updates_need_no_key(self, inner):
        storage = EncryptedSagaStorage(inner, EnvKeyProvider({}))
        with tenant_scope("acme"):
            await inner.save_saga_state("s1", "X", SagaStatus.EXECUTING, [{"name": "a"}], {})
            await storage.update_step_state("s1", "a", SagaStepStatus.FAILED, error="boom")

    async def test_results_cannot_be_written_in_the_system_scope(self, storage):
        await _save(storage)
        with system_scope(), pytest.raises(RuntimeError, match="tenant scope"):
            await storage.update_step_state("s1", "charge", SagaStepStatus.COMPLETED, {"x": 1})


class TestTransfers:
    async def test_export_keeps_ciphertext_and_import_round_trips(self, storage):
        await _save(storage, "acme")
        await _save(storage, "globex")
        with system_scope():
            exported = [record async for record in storage.export_all()]
        assert all(is_encrypted(r["context"]) for r in exported)

        target = EncryptedSagaStorage(InMemorySagaStorage(), EnvKeyProvider(KEYS))
        with system_scope():
            for record in exported:
                await target.import_record(record)
        for tenant in ("acme", "globex"):
            with tenant_scope(tenant):
                assert (await target.load_saga_state("s1"))["context"] == {"ssn": SECRET}

    async def test_importing_plaintext_encrypts_it_with_the_record_tenant(self, storage, inner):
        plain = InMemorySagaStorage()
        with tenant_scope("globex"):
            await plain.save_saga_state("s9", "X", SagaStatus.COMPLETED, STEPS, {"ssn": SECRET})
        with system_scope():
            async for record in plain.export_all():
                await storage.import_record(record)
        raw = await _raw(inner, "globex", "s9")
        assert is_encrypted(raw["context"])
        assert is_encrypted(raw["steps"][0]["result"])
        with tenant_scope("globex"):
            assert (await storage.load_saga_state("s9"))["context"] == {"ssn": SECRET}

    async def test_reserved_and_stepless_records_import(self, storage, inner):
        reserved = {
            "saga_id": "__sagaz_tenants__:x",
            "saga_name": "__sagaz_tenants__",
            "status": "completed",
            "context": {"tenant_id": "x"},
            "steps": [],
        }
        stepless = {
            "saga_id": "s5",
            "saga_name": "X",
            "status": "completed",
            "context": {"ssn": SECRET},
        }
        with system_scope():
            await storage.import_record(reserved)
            await storage.import_record(stepless)
        assert (await inner.load_saga_state("__sagaz_tenants__:x"))["context"] == {"tenant_id": "x"}
        assert is_encrypted((await inner.load_saga_state("s5"))["context"])

    async def test_records_without_steps_load(self, storage):
        class NoSteps(InMemorySagaStorage):
            async def load_saga_state(self, saga_id):
                record = await super().load_saga_state(saga_id)
                return record and {k: v for k, v in record.items() if k != "steps"}

        wrapped = EncryptedSagaStorage(NoSteps(), EnvKeyProvider(KEYS))
        await wrapped.save_saga_state("s1", "X", SagaStatus.COMPLETED, [], {"ssn": SECRET})
        loaded = await wrapped.load_saga_state("s1")
        assert loaded["context"] == {"ssn": SECRET}
        assert "steps" not in loaded


class TestDelegation:
    async def test_maintenance_calls_reach_the_backend(self, storage):
        from datetime import UTC, datetime, timedelta

        await _save(storage)
        with tenant_scope("acme"):
            assert [s["saga_id"] for s in await storage.list_sagas()] == ["s1"]
            assert await storage.get_saga_statistics() == await storage.inner.get_saga_statistics()
            assert await storage.count() == 1
            assert (await storage.health_check())["status"] == "healthy"
            future = datetime.now(UTC) + timedelta(days=1)
            assert await storage.cleanup_completed_sagas(future) == 1
            await _save(storage)
            assert await storage.delete_saga_state("s1") is True

    async def test_backend_specific_attributes_and_context_manager(self, tmp_path):
        inner = SQLiteSagaStorage(str(tmp_path / "x.db"))
        async with EncryptedSagaStorage(inner, EnvKeyProvider(KEYS)) as storage:
            assert storage.db_path == inner.db_path
        await storage.close()


class PatientSaga(Saga):
    saga_name = "patient"

    @action("register")
    async def register(self, ctx):
        return {"mrn": f"MRN-{ctx['ssn'][-4:]}"}


async def test_declarative_saga_run_as_tenant_is_stored_encrypted(inner):
    storage = EncryptedSagaStorage(inner, EnvKeyProvider(KEYS))
    saga = PatientSaga(config=SagaConfig(storage=storage, metrics=False, logging=False))

    await saga.run({"ssn": SECRET}, saga_id="p-1", tenant="acme")

    raw = await _raw(inner, "acme", "p-1")
    assert raw["status"] == "completed"
    assert SECRET not in json.dumps(raw, default=str)
    with tenant_scope("acme"):
        loaded = await storage.load_saga_state("p-1")
    assert loaded["context"]["ssn"] == SECRET
    assert loaded["context"]["tenant_id"] == "acme"
