"""
Tests for the storage factory module
"""

import pytest

from sagaz.exceptions import MissingDependencyError
from sagaz.storage.factory import create_storage, get_available_backends, print_available_backends
from sagaz.storage.memory import InMemorySagaStorage


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
        from sagaz.storage.redis import REDIS_AVAILABLE

        if not REDIS_AVAILABLE:
            with pytest.raises(MissingDependencyError) as exc_info:
                create_storage("redis")
            assert "redis" in str(exc_info.value).lower()
        else:
            storage = create_storage("redis", redis_url="redis://localhost:6379")
            assert storage is not None

    def test_create_postgresql_storage(self):
        """Test creating PostgreSQL storage"""
        from sagaz.storage.postgresql import ASYNCPG_AVAILABLE

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
        from sagaz.storage.postgresql import ASYNCPG_AVAILABLE

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
        from sagaz.storage.postgresql import ASYNCPG_AVAILABLE

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
