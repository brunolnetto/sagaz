"""
Unit tests for Saga Versioning & Schema Evolution (ADR-018).

TDD red phase — tests define the exact public API before implementation.

Coverage targets:
- Version value object: parsing, comparison, compatibility
- SagaVersion dataclass: fields and deprecation helpers
- SagaVersionRegistry: register, latest, lookup, deprecate, remove
- MigrationEngine: register, single-hop, multi-hop, no-op, missing path
- SagaVersionResolver: new saga → latest; resume → pinned version
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest

from sagaz.versioning import (
    MigrationEngine,
    MigrationPathNotFoundError,
    SagaVersion,
    SagaVersionNotFoundError,
    SagaVersionRegistry,
    SagaVersionResolver,
    Version,
    VersionAlreadyRegisteredError,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_saga_version(
    saga_name: str = "order-processing",
    version: str = "1.0.0",
    step_names: list[str] | None = None,
    schema: dict | None = None,
    deprecated_at: datetime | None = None,
) -> SagaVersion:
    return SagaVersion(
        saga_name=saga_name,
        version=Version.parse(version),
        step_names=step_names or ["reserve", "charge"],
        schema=schema or {},
        deprecated_at=deprecated_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Version value object
# ─────────────────────────────────────────────────────────────────────────────


class TestVersion:
    def test_parse_semver_string(self):
        v = Version.parse("2.3.1")
        assert v.major == 2
        assert v.minor == 3
        assert v.patch == 1

    def test_str_roundtrip(self):
        assert str(Version.parse("1.0.0")) == "1.0.0"

    def test_repr_contains_version(self):
        assert "1.2.3" in repr(Version.parse("1.2.3"))

    def test_equality(self):
        assert Version.parse("1.0.0") == Version.parse("1.0.0")

    def test_ordering_major(self):
        assert Version.parse("2.0.0") > Version.parse("1.9.9")

    def test_ordering_minor(self):
        assert Version.parse("1.2.0") > Version.parse("1.1.9")

    def test_ordering_patch(self):
        assert Version.parse("1.0.2") > Version.parse("1.0.1")

    def test_ordering_less_than(self):
        assert Version.parse("1.0.0") < Version.parse("2.0.0")

    def test_is_compatible_with_same_version(self):
        """Same version is always compatible."""
        v = Version.parse("2.1.0")
        assert v.is_compatible_with(Version.parse("2.1.0"))

    def test_is_compatible_same_major_higher_minor(self):
        """New minor release is backward-compatible with older minor."""
        assert Version.parse("1.3.0").is_compatible_with(Version.parse("1.1.0"))

    def test_is_not_compatible_different_major(self):
        """Different major versions are incompatible."""
        assert not Version.parse("2.0.0").is_compatible_with(Version.parse("1.9.9"))

    def test_invalid_semver_raises(self):
        with pytest.raises(ValueError, match="semver"):
            Version.parse("not-a-version")

    def test_eq_with_non_version_returns_not_implemented(self):
        assert Version.parse("1.0.0").__eq__("1.0.0") is NotImplemented

    def test_lt_with_non_version_returns_not_implemented(self):
        assert Version.parse("1.0.0").__lt__("1.0.0") is NotImplemented


# ─────────────────────────────────────────────────────────────────────────────
# SagaVersion dataclass
# ─────────────────────────────────────────────────────────────────────────────


class TestSagaVersion:
    def test_fields_stored(self):
        sv = _make_saga_version(version="1.2.3")
        assert sv.saga_name == "order-processing"
        assert str(sv.version) == "1.2.3"
        assert "reserve" in sv.step_names

    def test_is_deprecated_false_by_default(self):
        sv = _make_saga_version()
        assert sv.is_deprecated is False

    def test_is_deprecated_when_deprecated_at_set(self):
        sv = _make_saga_version(deprecated_at=datetime.now(UTC))
        assert sv.is_deprecated is True

    def test_schema_stored(self):
        sv = _make_saga_version(schema={"amount": "int", "currency": "str"})
        assert sv.schema["amount"] == "int"


# ─────────────────────────────────────────────────────────────────────────────
# SagaVersionRegistry
# ─────────────────────────────────────────────────────────────────────────────


class TestSagaVersionRegistry:
    def test_register_and_get(self):
        reg = SagaVersionRegistry()
        sv = _make_saga_version(version="1.0.0")
        reg.register(sv)
        result = reg.get("order-processing", Version.parse("1.0.0"))
        assert result == sv

    def test_get_latest_single_version(self):
        reg = SagaVersionRegistry()
        sv = _make_saga_version(version="1.0.0")
        reg.register(sv)
        assert reg.get_latest("order-processing") == sv

    def test_get_latest_multiple_versions_returns_highest(self):
        reg = SagaVersionRegistry()
        v1 = _make_saga_version(version="1.0.0")
        v2 = _make_saga_version(version="2.0.0")
        v11 = _make_saga_version(version="1.1.0")
        reg.register(v1)
        reg.register(v2)
        reg.register(v11)
        assert reg.get_latest("order-processing") == v2

    def test_get_latest_excludes_deprecated(self):
        reg = SagaVersionRegistry()
        v1 = _make_saga_version(version="1.0.0")
        v2 = _make_saga_version(version="2.0.0", deprecated_at=datetime.now(UTC))
        reg.register(v1)
        reg.register(v2)
        assert reg.get_latest("order-processing") == v1

    def test_duplicate_registration_raises(self):
        reg = SagaVersionRegistry()
        sv = _make_saga_version(version="1.0.0")
        reg.register(sv)
        with pytest.raises(VersionAlreadyRegisteredError):
            reg.register(sv)

    def test_get_unknown_saga_raises(self):
        reg = SagaVersionRegistry()
        with pytest.raises(SagaVersionNotFoundError):
            reg.get("unknown-saga", Version.parse("1.0.0"))

    def test_list_versions_returns_all_registered(self):
        reg = SagaVersionRegistry()
        reg.register(_make_saga_version(version="1.0.0"))
        reg.register(_make_saga_version(version="2.0.0"))
        versions = reg.list_versions("order-processing")
        assert len(versions) == 2

    def test_list_versions_unknown_saga_returns_empty(self):
        reg = SagaVersionRegistry()
        assert reg.list_versions("no-such-saga") == []

    def test_deprecate_marks_version(self):
        reg = SagaVersionRegistry()
        reg.register(_make_saga_version(version="1.0.0"))
        reg.deprecate("order-processing", Version.parse("1.0.0"))
        sv = reg.get("order-processing", Version.parse("1.0.0"))
        assert sv.is_deprecated is True

    def test_deprecate_unknown_raises(self):
        reg = SagaVersionRegistry()
        with pytest.raises(SagaVersionNotFoundError):
            reg.deprecate("no-saga", Version.parse("1.0.0"))


# ─────────────────────────────────────────────────────────────────────────────
# MigrationEngine
# ─────────────────────────────────────────────────────────────────────────────


class TestMigrationEngine:
    def test_same_version_returns_context_unchanged(self):
        engine = MigrationEngine()
        ctx = {"amount": 100}
        result = engine.migrate("order-processing", "1.0.0", "1.0.0", ctx)
        assert result == ctx

    def test_single_hop_migration(self):
        engine = MigrationEngine()

        def v1_to_v2(ctx: dict) -> dict:
            return {**ctx, "customer_tier": "standard"}

        engine.register("order-processing", "1.0.0", "2.0.0", v1_to_v2)
        result = engine.migrate("order-processing", "1.0.0", "2.0.0", {"amount": 50})
        assert result["customer_tier"] == "standard"
        assert result["amount"] == 50

    def test_migration_does_not_mutate_original(self):
        engine = MigrationEngine()
        engine.register("order-processing", "1.0.0", "2.0.0", lambda ctx: {**ctx, "new": True})
        original = {"amount": 50}
        engine.migrate("order-processing", "1.0.0", "2.0.0", original)
        assert "new" not in original

    def test_multi_hop_migration(self):
        """v1 → v2 → v3 applied in sequence."""
        engine = MigrationEngine()
        engine.register(
            "saga", "1.0.0", "2.0.0", lambda ctx: {**ctx, "step": ctx.get("step", []) + ["v1->v2"]}
        )
        engine.register(
            "saga", "2.0.0", "3.0.0", lambda ctx: {**ctx, "step": ctx.get("step", []) + ["v2->v3"]}
        )
        result = engine.migrate("saga", "1.0.0", "3.0.0", {})
        assert result["step"] == ["v1->v2", "v2->v3"]

    def test_missing_path_raises(self):
        engine = MigrationEngine()
        with pytest.raises(MigrationPathNotFoundError):
            engine.migrate("order-processing", "1.0.0", "3.0.0", {})

    def test_missing_path_with_partial_graph_raises(self):
        """Graph has edges but no path from source to target."""
        engine = MigrationEngine()
        engine.register("saga", "1.0.0", "2.0.0", lambda ctx: ctx)
        # No edge from 2.0.0 to 3.0.0
        with pytest.raises(MigrationPathNotFoundError):
            engine.migrate("saga", "1.0.0", "3.0.0", {})

    def test_list_migrations_empty(self):
        engine = MigrationEngine()
        assert engine.list_migrations("order-processing") == []

    def test_list_migrations_returns_registered(self):
        engine = MigrationEngine()
        engine.register("order-processing", "1.0.0", "2.0.0", lambda ctx: ctx)
        migrations = engine.list_migrations("order-processing")
        assert len(migrations) == 1
        assert migrations[0] == ("1.0.0", "2.0.0")


# ─────────────────────────────────────────────────────────────────────────────
# SagaVersionResolver
# ─────────────────────────────────────────────────────────────────────────────


class TestSagaVersionResolver:
    def _make_resolver(self) -> SagaVersionResolver:
        registry = SagaVersionRegistry()
        registry.register(_make_saga_version(version="1.0.0"))
        registry.register(_make_saga_version(version="2.0.0"))
        return SagaVersionResolver(registry=registry)

    def test_new_saga_gets_latest_version(self):
        resolver = self._make_resolver()
        sv = resolver.resolve("order-processing", saga_id=None)
        assert str(sv.version) == "2.0.0"

    def test_resuming_saga_gets_pinned_version(self):
        resolver = self._make_resolver()
        sv = resolver.resolve(
            "order-processing",
            saga_id="abc-123",
            pinned_version="1.0.0",
        )
        assert str(sv.version) == "1.0.0"

    def test_unknown_saga_raises(self):
        resolver = SagaVersionResolver(registry=SagaVersionRegistry())
        with pytest.raises(SagaVersionNotFoundError):
            resolver.resolve("no-such-saga", saga_id=None)

    def test_pinned_unknown_version_raises(self):
        resolver = self._make_resolver()
        with pytest.raises(SagaVersionNotFoundError):
            resolver.resolve("order-processing", saga_id="x", pinned_version="9.9.9")


# ─────────────────────────────────────────────────────────────────────────────
# Exception classes
# ─────────────────────────────────────────────────────────────────────────────


class TestVersioningExceptions:
    def test_saga_version_not_found_error_attrs(self):
        exc = SagaVersionNotFoundError("order-processing", "1.0.0")
        assert exc.saga_name == "order-processing"
        assert exc.version == "1.0.0"
        assert "order-processing" in str(exc)

    def test_migration_path_not_found_error_attrs(self):
        exc = MigrationPathNotFoundError("saga", "1.0.0", "3.0.0")
        assert exc.saga_name == "saga"
        assert exc.from_version == "1.0.0"
        assert exc.to_version == "3.0.0"

    def test_version_already_registered_error(self):
        exc = VersionAlreadyRegisteredError("order-processing", "1.0.0")
        assert "order-processing" in str(exc)
        assert "1.0.0" in str(exc)
