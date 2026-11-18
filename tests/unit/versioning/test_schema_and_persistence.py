"""Runtime context validation and the persistent registry (issue #112, ADR-018)."""

from __future__ import annotations

import pytest

from sagaz import Saga, action
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
from sagaz.versioning import (
    VERSION_RECORD_SAGA_NAME,
    SagaVersion,
    SagaVersionedMixin,
    SagaVersionError,
    SagaVersionNotFoundError,
    SagaVersionRegistry,
    SagaVersionSchemaError,
    Version,
    schema_violations,
    validate_context,
)

ORDER_SCHEMA = {"order_id": "str", "amount": "float", "express": "bool?"}


def _registry(*versions: tuple[str, dict]) -> SagaVersionRegistry:
    registry = SagaVersionRegistry()
    for version, schema in versions:
        registry.register(SagaVersion("order", Version.parse(version), ["charge"], schema))
    return registry


# --------------------------------------------------------------- validation


class TestSchemaViolations:
    def test_valid_context_has_no_violations(self):
        assert schema_violations(ORDER_SCHEMA, {"order_id": "o1", "amount": 10}) == []

    def test_every_violation_is_reported(self):
        violations = schema_violations(
            {**ORDER_SCHEMA, "items": "list", "meta": "dict", "note": "any", "n": "int"},
            {"amount": "10", "express": 1, "items": (), "meta": {}, "n": True},
        )
        assert violations == [
            "'order_id': required field is missing",
            "'amount': expected float, got str",
            "'express': expected bool, got int",
            "'items': expected list, got tuple",
            "'note': required field is missing",
            "'n': expected int, got bool",
        ]

    def test_optional_field_may_be_missing_or_none(self):
        assert schema_violations({"express": "bool?"}, {}) == []
        assert schema_violations({"express": "bool?"}, {"express": None}) == []

    def test_unknown_descriptor_is_a_violation(self):
        assert schema_violations({"x": "uuid"}, {"x": "a"}) == [
            "'x': unknown type descriptor 'uuid'"
        ]

    def test_empty_schema_accepts_anything(self):
        assert schema_violations({}, {"whatever": 1}) == []
        assert schema_violations(None, {}) == []

    def test_validate_context_raises_with_details(self):
        version = SagaVersion("order", Version(2, 0, 0), schema=ORDER_SCHEMA)
        with pytest.raises(SagaVersionSchemaError) as info:
            validate_context(version, {"order_id": 7})
        error = info.value
        assert (error.saga_name, error.version) == ("order", "2.0.0")
        assert error.violations == [
            "'order_id': expected str, got int",
            "'amount': required field is missing",
        ]
        assert "order' v2.0.0 violates its schema" in str(error)


class TestPydanticSchemas:
    pydantic = pytest.importorskip("pydantic")

    def _model(self):
        class Order(self.pydantic.BaseModel):
            order_id: str
            amount: float

        return Order

    def test_valid_and_invalid_context(self):
        model = self._model()
        assert schema_violations(model, {"order_id": "o1", "amount": 3}) == []
        violations = schema_violations(model, {"order_id": "o1"})
        assert violations == ["'amount': Field required"]

    def test_validator_errors_without_details_are_stringified(self):
        class Strict:
            @staticmethod
            def model_validate(data):
                msg = "nope"
                raise ValueError(msg)

        assert schema_violations(Strict, {}) == ["nope"]


# --------------------------------------------------------------- the mixin


class OrderSaga(SagaVersionedMixin, Saga):
    saga_name = "order"

    @action("charge")
    async def charge(self, ctx):
        return {"charged": ctx["amount"]}


class TestSagaVersionedMixin:
    @pytest.fixture(autouse=True)
    def _reset(self, monkeypatch):
        monkeypatch.setattr(OrderSaga, "saga_version", None)
        monkeypatch.setattr(
            OrderSaga, "version_registry", _registry(("1.0.0", {}), ("2.0.0", ORDER_SCHEMA))
        )

    async def test_valid_context_runs_the_saga(self):
        result = await OrderSaga().run({"order_id": "o1", "amount": 5.0})
        assert result["charged"] == 5.0

    async def test_invalid_context_raises_before_any_step(self):
        saga = OrderSaga()
        with pytest.raises(SagaVersionSchemaError, match="amount"):
            await saga.run({"order_id": "o1"})
        assert "charged" not in saga._context

    async def test_pinned_older_version_uses_its_own_schema(self, monkeypatch):
        monkeypatch.setattr(OrderSaga, "saga_version", "1.0.0")
        assert OrderSaga().active_saga_version().version == Version(1, 0, 0)
        result = await OrderSaga().run({"amount": 1})  # v1 schema is empty
        assert result["charged"] == 1

    async def test_latest_active_version_is_the_default(self):
        assert OrderSaga().active_saga_version().version == Version(2, 0, 0)

    async def test_unknown_pinned_version_is_reported(self, monkeypatch):
        monkeypatch.setattr(OrderSaga, "saga_version", "9.9.9")
        with pytest.raises(SagaVersionNotFoundError):
            await OrderSaga().run({})

    async def test_registry_is_required(self, monkeypatch):
        monkeypatch.setattr(OrderSaga, "version_registry", None)
        with pytest.raises(SagaVersionError, match="version_registry"):
            await OrderSaga().run({})


# --------------------------------------------------------------- persistence


class PydanticOrder:
    """Stand-in model class: importable by path, validates nothing."""

    @staticmethod
    def model_validate(data):
        return data


@pytest.fixture(params=["memory", "sqlite"])
async def storage(request, tmp_path):
    if request.param == "memory":
        yield InMemorySagaStorage()
        return
    sqlite = SQLiteSagaStorage(str(tmp_path / "versions.db"))
    yield sqlite
    await sqlite.close()


class TestPersistentRegistry:
    async def test_registry_survives_a_reload(self, storage):
        registry = SagaVersionRegistry(storage)
        registry.register(SagaVersion("order", Version(1, 0, 0), ["a"], {"x": "int"}))
        registry.register(SagaVersion("order", Version(2, 0, 0), ["a", "b"], PydanticOrder))
        registry.deprecate("order", Version(1, 0, 0))
        assert await registry.save() == 2

        reloaded = await SagaVersionRegistry.from_storage(storage)

        v1 = reloaded.get("order", Version(1, 0, 0))
        v2 = reloaded.get_latest("order")
        assert v1.is_deprecated
        assert v1.schema == {"x": "int"}
        assert (v2.version, v2.step_names, v2.schema) == (
            Version(2, 0, 0),
            ["a", "b"],
            PydanticOrder,
        )

    async def test_saving_again_updates_instead_of_duplicating(self, storage):
        registry = SagaVersionRegistry(storage)
        registry.register(SagaVersion("order", Version(1, 0, 0)))
        await registry.save()
        registry.deprecate("order", Version(1, 0, 0))
        await registry.save()

        reloaded = await SagaVersionRegistry.from_storage(storage)
        assert len(reloaded.list_versions("order")) == 1
        assert reloaded.list_versions("order")[0].is_deprecated

    async def test_load_replaces_in_memory_state(self, storage):
        await SagaVersionRegistry(storage).save()  # nothing persisted
        registry = SagaVersionRegistry(storage)
        registry.register(SagaVersion("order", Version(1, 0, 0)))
        assert await registry.load() == 0
        assert registry.list_versions("order") == []

    async def test_records_use_the_reserved_saga_name(self, storage):
        registry = SagaVersionRegistry(storage)
        registry.register(SagaVersion("order", Version(1, 2, 3)))
        await registry.save()
        summaries = await storage.list_sagas(saga_name=VERSION_RECORD_SAGA_NAME)
        assert [s["saga_id"] for s in summaries] == [f"{VERSION_RECORD_SAGA_NAME}:order:1.2.3"]

    async def test_persistence_requires_storage(self):
        registry = SagaVersionRegistry()
        with pytest.raises(ValueError, match="storage"):
            await registry.save()
        with pytest.raises(ValueError, match="storage"):
            await registry.load()

    async def test_vanished_record_is_skipped(self, storage, monkeypatch):
        registry = SagaVersionRegistry(storage)
        registry.register(SagaVersion("order", Version(1, 0, 0)))
        await registry.save()

        async def gone(saga_id):
            return None

        monkeypatch.setattr(storage, "load_saga_state", gone)
        assert await SagaVersionRegistry(storage).load() == 0


async def test_analytics_ignores_version_records():
    pytest.importorskip("duckdb")
    from sagaz.analytics.sources import bronze_records_from_storage

    storage = InMemorySagaStorage()
    registry = SagaVersionRegistry(storage)
    registry.register(SagaVersion("order", Version(1, 0, 0)))
    await registry.save()

    sagas, steps = await bronze_records_from_storage(storage)
    assert (sagas, steps) == ([], [])


def test_any_descriptor_accepts_any_present_value():
    assert schema_violations({"payload": "any"}, {"payload": object()}) == []


@pytest.mark.integration
async def test_registry_survives_reload_on_postgres(postgres_connection_string):
    if not postgres_connection_string:
        pytest.skip("PostgreSQL container not available")
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    async with PostgreSQLSagaStorage(
        postgres_connection_string, pool_min_size=1, pool_max_size=2
    ) as storage:
        pool = await storage._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE sagas CASCADE")
        registry = SagaVersionRegistry(storage)
        registry.register(SagaVersion("order", Version(3, 1, 0), ["a"], ORDER_SCHEMA))
        await registry.save()

        reloaded = await SagaVersionRegistry.from_storage(storage)

    assert reloaded.get_latest("order").schema == ORDER_SCHEMA
