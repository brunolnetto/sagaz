"""
Tests for the storage factory module
"""

import importlib
import sys
from unittest.mock import patch

import pytest

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.storage.factory import create_storage, get_available_backends, print_available_backends
from sagaz.core.storage.memory import InMemorySagaStorage


class TestCreateStorage:
    """Tests for create_storage factory function"""

    def test_create_memory_storage(self):
        """Test creating in-memory storage"""
        storage = create_storage("memory")
        assert isinstance(storage, InMemorySagaStorage)

    def test_create_memory_storage_uppercase(self):
        """Test backend name is case-insensitive"""
        storage = create_storage("MEMORY")
        assert isinstance(storage, InMemorySagaStorage)

    def test_create_memory_storage_with_whitespace(self):
        """Test backend name trims whitespace"""
        storage = create_storage("  memory  ")
        assert isinstance(storage, InMemorySagaStorage)

    def test_create_redis_storage(self):
        """Test creating Redis storage"""
        from sagaz.core.storage.backends.redis.saga import REDIS_AVAILABLE

        if not REDIS_AVAILABLE:
            with pytest.raises(MissingDependencyError) as exc_info:
                create_storage("redis")
            assert "redis" in str(exc_info.value).lower()
        else:
            storage = create_storage("redis", redis_url="redis://localhost:6379")
            assert storage is not None

    def test_create_postgresql_storage(self):
        """Test creating PostgreSQL storage"""
        from sagaz.core.storage.backends.postgresql.saga import ASYNCPG_AVAILABLE

        if not ASYNCPG_AVAILABLE:
            with pytest.raises(MissingDependencyError) as exc_info:
                create_storage("postgresql", connection_string="postgresql://test")
            assert "asyncpg" in str(exc_info.value).lower()
        else:
            storage = create_storage(
                "postgresql", connection_string="postgresql://test:test@localhost/test"
            )
            assert storage is not None

    def test_create_postgresql_without_connection_string(self):
        """Test PostgreSQL requires connection_string"""
        with pytest.raises(ValueError) as exc_info:
            create_storage("postgresql")
        assert "connection_string" in str(exc_info.value)

    def test_create_postgres_alias(self):
        """Test 'postgres' alias for postgresql"""
        from sagaz.core.storage.backends.postgresql.saga import ASYNCPG_AVAILABLE

        if not ASYNCPG_AVAILABLE:
            with pytest.raises(MissingDependencyError):
                create_storage("postgres", connection_string="postgresql://test")
        else:
            storage = create_storage(
                "postgres", connection_string="postgresql://test:test@localhost/test"
            )
            assert storage is not None

    def test_create_pg_alias(self):
        """Test 'pg' alias for postgresql"""
        from sagaz.core.storage.backends.postgresql.saga import ASYNCPG_AVAILABLE

        if not ASYNCPG_AVAILABLE:
            with pytest.raises(MissingDependencyError):
                create_storage("pg", connection_string="postgresql://test")
        else:
            storage = create_storage(
                "pg", connection_string="postgresql://test:test@localhost/test"
            )
            assert storage is not None

    def test_unknown_backend_raises_error(self):
        """Test unknown backend raises ValueError"""
        with pytest.raises(ValueError) as exc_info:
            create_storage("mongodb")

        error_msg = str(exc_info.value)
        assert "mongodb" in error_msg
        assert "memory" in error_msg
        assert "redis" in error_msg
        assert "postgresql" in error_msg

    def test_invalid_storage_type_raises_error(self):
        """Test invalid storage_type raises ValueError"""
        with pytest.raises(ValueError) as exc_info:
            create_storage("memory", storage_type="invalid")

        assert "storage_type" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)


class TestCreateStorageTypes:
    """Tests for storage_type parameter in factory."""

    def test_create_memory_saga_storage(self):
        """Test creating saga storage explicitly."""
        storage = create_storage("memory", storage_type="saga")
        assert isinstance(storage, InMemorySagaStorage)

    def test_create_memory_outbox_storage(self):
        """Test creating outbox storage."""
        from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

        storage = create_storage("memory", storage_type="outbox")
        assert isinstance(storage, InMemoryOutboxStorage)

    def test_create_memory_both_storages(self):
        """Test creating both storages at once."""
        from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

        saga, outbox = create_storage("memory", storage_type="both")

        assert isinstance(saga, InMemorySagaStorage)
        assert isinstance(outbox, InMemoryOutboxStorage)

    def test_create_redis_outbox_storage(self):
        """Test creating Redis outbox storage."""
        from sagaz.core.storage.backends.redis.saga import REDIS_AVAILABLE

        if not REDIS_AVAILABLE:
            pytest.skip("Redis not available")

        from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage

        storage = create_storage(
            "redis",
            storage_type="outbox",
            redis_url="redis://localhost:6379",
        )
        assert isinstance(storage, RedisOutboxStorage)

    def test_create_redis_both_storages(self):
        """Test creating both Redis storages."""
        from sagaz.core.storage.backends.redis.saga import REDIS_AVAILABLE

        if not REDIS_AVAILABLE:
            pytest.skip("Redis not available")

        from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage
        from sagaz.core.storage.redis import RedisSagaStorage

        saga, outbox = create_storage(
            "redis",
            storage_type="both",
            redis_url="redis://localhost:6379",
        )

        assert isinstance(saga, RedisSagaStorage)
        assert isinstance(outbox, RedisOutboxStorage)

    def test_create_postgresql_outbox_without_connection_string(self):
        """Test PostgreSQL outbox requires connection_string."""
        with pytest.raises(ValueError) as exc_info:
            create_storage("postgresql", storage_type="outbox")
        assert "connection_string" in str(exc_info.value)

    def test_create_postgresql_outbox_storage(self):
        """Test creating PostgreSQL outbox storage."""
        from sagaz.core.storage.backends.postgresql.saga import ASYNCPG_AVAILABLE

        if not ASYNCPG_AVAILABLE:
            pytest.skip("asyncpg not available")

        from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

        storage = create_storage(
            "postgresql",
            storage_type="outbox",
            connection_string="postgresql://test:test@localhost/test",
        )
        assert isinstance(storage, PostgreSQLOutboxStorage)

    def test_default_storage_type_is_saga(self):
        """Test default storage_type is saga."""
        storage = create_storage("memory")
        assert isinstance(storage, InMemorySagaStorage)


class TestGetAvailableBackends:
    """Tests for get_available_backends function"""

    def test_returns_dict(self):
        """Test function returns a dictionary"""
        backends = get_available_backends()
        assert isinstance(backends, dict)

    def test_memory_always_available(self):
        """Test memory backend is always available"""
        backends = get_available_backends()
        assert "memory" in backends
        assert backends["memory"]["available"] is True

    def test_contains_expected_keys(self):
        """Test each backend has expected keys"""
        backends = get_available_backends()

        for _name, info in backends.items():
            assert "available" in info
            assert "description" in info
            assert "install" in info
            assert "best_for" in info

    def test_includes_redis_info(self):
        """Test Redis backend info is included"""
        backends = get_available_backends()
        assert "redis" in backends

    def test_includes_postgresql_info(self):
        """Test PostgreSQL backend info is included"""
        backends = get_available_backends()
        assert "postgresql" in backends


class TestPrintAvailableBackends:
    """Tests for print_available_backends function"""

    def test_prints_output(self, capsys):
        """Test function prints to stdout"""
        print_available_backends()

        captured = capsys.readouterr()
        assert "Available Storage Backends" in captured.out
        assert "memory" in captured.out

    def test_shows_status_indicators(self, capsys):
        """Test output shows status indicators"""
        print_available_backends()

        captured = capsys.readouterr()
        # Should have at least one checkmark for memory
        assert "✓" in captured.out


class TestMissingDependencyError:
    """Tests for MissingDependencyError exception"""

    def test_error_message_contains_package(self):
        """Test error message includes package name"""
        error = MissingDependencyError("redis")
        assert "redis" in str(error)

    def test_error_message_contains_install_command(self):
        """Test error message includes install command"""
        error = MissingDependencyError("redis")
        assert "pip install redis" in str(error)

    def test_error_message_contains_feature(self):
        """Test error message includes feature description"""
        error = MissingDependencyError("asyncpg", "PostgreSQL storage")
        assert "PostgreSQL storage" in str(error)

    def test_error_attributes(self):
        """Test error has expected attributes"""
        error = MissingDependencyError("redis", "Redis backend")
        assert error.package == "redis"
        assert error.feature == "Redis backend"

    def test_unknown_package_uses_default_install(self):
        """Test unknown packages get default pip install command"""
        error = MissingDependencyError("some-unknown-package")
        assert "pip install some-unknown-package" in str(error)


class TestFactoryMissingDependencyRaise:
    """Line 246: re-raise MissingDependencyError in 'both' storage_type."""

    def test_missing_dep_reraises_on_both(self):
        """Trigger MissingDependencyError inside create_storage("both")."""
        import sagaz.core.storage.backends.postgresql.saga as pg_mod

        original = pg_mod.ASYNCPG_AVAILABLE
        try:
            pg_mod.ASYNCPG_AVAILABLE = False
            with pytest.raises(MissingDependencyError):
                create_storage(
                    "postgresql",
                    storage_type="both",
                    connection_string="postgresql://localhost/test",
                )
        finally:
            pg_mod.ASYNCPG_AVAILABLE = original


class TestGetAvailableBackendsImportErrors:
    """Lines 286-287, 306-307, 326-327: ImportError branches in get_available_backends."""

    def test_redis_unavailable_branch(self, capsys):
        """Lines 286-287: redis.asyncio import error path."""
        import sagaz.core.storage.factory as factory_mod

        original = sys.modules.get("redis.asyncio")
        try:
            sys.modules["redis.asyncio"] = None  # type: ignore[assignment]
            importlib.reload(factory_mod)
            backends = factory_mod.get_available_backends()
            assert backends.get("redis", {}).get("available") is False
        finally:
            if original is not None:
                sys.modules["redis.asyncio"] = original
            else:
                sys.modules.pop("redis.asyncio", None)
            importlib.reload(factory_mod)

    def test_asyncpg_unavailable_branch(self, capsys):
        """Lines 306-307: asyncpg import error path."""
        import sagaz.core.storage.factory as factory_mod

        original = sys.modules.get("asyncpg")
        try:
            sys.modules["asyncpg"] = None  # type: ignore[assignment]
            importlib.reload(factory_mod)
            backends = factory_mod.get_available_backends()
            assert backends.get("postgresql", {}).get("available") is False
        finally:
            if original is not None:
                sys.modules["asyncpg"] = original
            else:
                sys.modules.pop("asyncpg", None)
            importlib.reload(factory_mod)

    def test_aiosqlite_unavailable_branch(self, capsys):
        """Lines 326-327: aiosqlite import error path."""
        import sagaz.core.storage.factory as factory_mod

        original = sys.modules.get("aiosqlite")
        try:
            sys.modules["aiosqlite"] = None  # type: ignore[assignment]
            importlib.reload(factory_mod)
            backends = factory_mod.get_available_backends()
            assert backends.get("sqlite", {}).get("available") is False
        finally:
            if original is not None:
                sys.modules["aiosqlite"] = original
            else:
                sys.modules.pop("aiosqlite", None)
            importlib.reload(factory_mod)

    def test_print_with_unavailable_backend_shows_install(self, capsys):
        """Line 355: print_available_backends shows install line for unavailable backend."""
        import sagaz.core.storage.factory as factory_mod

        original_asyncpg = sys.modules.get("asyncpg")
        try:
            sys.modules["asyncpg"] = None  # type: ignore[assignment]
            importlib.reload(factory_mod)
            factory_mod.print_available_backends()
        finally:
            if original_asyncpg is not None:
                sys.modules["asyncpg"] = original_asyncpg
            else:
                sys.modules.pop("asyncpg", None)
            importlib.reload(factory_mod)

        captured = capsys.readouterr()
        assert "Install" in captured.out or "pip install" in captured.out
