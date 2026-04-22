"""
Tests for sagaz.demonstrations.utils.service_manager context manager.

Tests the ServiceManager for provisioning and managing testcontainer services.
"""

from unittest.mock import MagicMock, patch

import pytest

from sagaz.demonstrations.utils.service_manager import ServiceManager, ServiceURLs


class TestServiceURLs:
    """Tests for ServiceURLs dataclass."""

    def test_service_urls_creation_empty(self):
        """Test creating empty ServiceURLs."""
        urls = ServiceURLs()
        assert urls.postgres_url is None
        assert urls.redis_url is None

    def test_service_urls_creation_with_values(self):
        """Test creating ServiceURLs with values."""
        urls = ServiceURLs(
            postgres_url="postgresql://localhost/test", redis_url="redis://localhost:6379"
        )
        assert urls.postgres_url == "postgresql://localhost/test"
        assert urls.redis_url == "redis://localhost:6379"

    def test_service_urls_partial_values(self):
        """Test ServiceURLs with only some values set."""
        urls = ServiceURLs(postgres_url="postgresql://localhost/test")
        assert urls.postgres_url == "postgresql://localhost/test"
        assert urls.redis_url is None


class TestServiceManagerContextManager:
    """Tests for ServiceManager context manager."""

    def test_service_manager_no_services(self):
        """Test ServiceManager with no services requested."""
        with ServiceManager() as svc:
            assert svc.postgres_url is None
            assert svc.redis_url is None

    @patch("testcontainers.postgres.PostgresContainer")
    def test_service_manager_postgres_only(self, mock_pg_container):
        """Test ServiceManager with only PostgreSQL requested."""
        # Setup mock
        mock_pg = MagicMock()
        mock_pg.get_connection_url.return_value = "postgresql+psycopg2://user:pass@localhost:5432/test"
        mock_pg_container.return_value = mock_pg

        with ServiceManager(postgres=True) as svc:
            assert svc.postgres_url == "postgresql://user:pass@localhost:5432/test"
            assert svc.redis_url is None
            mock_pg.start.assert_called_once()

        # Verify cleanup
        mock_pg.stop.assert_called_once()

    @patch("testcontainers.redis.RedisContainer")
    def test_service_manager_redis_only(self, mock_redis_container):
        """Test ServiceManager with only Redis requested."""
        # Setup mock
        mock_redis = MagicMock()
        mock_redis.get_container_host_ip.return_value = "localhost"
        mock_redis.get_exposed_port.return_value = 6379
        mock_redis_container.return_value = mock_redis

        with ServiceManager(redis=True) as svc:
            assert svc.redis_url == "redis://localhost:6379/0"
            assert svc.postgres_url is None
            mock_redis.start.assert_called_once()

        # Verify cleanup
        mock_redis.stop.assert_called_once()

    @patch("testcontainers.redis.RedisContainer")
    @patch("testcontainers.postgres.PostgresContainer")
    def test_service_manager_both_services(self, mock_pg_container, mock_redis_container):
        """Test ServiceManager with both PostgreSQL and Redis."""
        # Setup mocks
        mock_pg = MagicMock()
        mock_pg.get_connection_url.return_value = "postgresql+psycopg2://user:pass@localhost:5432/db"
        mock_pg_container.return_value = mock_pg

        mock_redis = MagicMock()
        mock_redis.get_container_host_ip.return_value = "127.0.0.1"
        mock_redis.get_exposed_port.return_value = 6380
        mock_redis_container.return_value = mock_redis

        with ServiceManager(postgres=True, redis=True) as svc:
            assert svc.postgres_url == "postgresql://user:pass@localhost:5432/db"
            assert svc.redis_url == "redis://127.0.0.1:6380/0"
            mock_pg.start.assert_called_once()
            mock_redis.start.assert_called_once()

        # Verify cleanup (in reverse order)
        mock_redis.stop.assert_called_once()
        mock_pg.stop.assert_called_once()

    @patch("testcontainers.postgres.PostgresContainer")
    def test_service_manager_postgres_connection_url_conversion(self, mock_pg_container):
        """Test that PostgreSQL URL is converted from psycopg2 to postgresql scheme."""
        mock_pg = MagicMock()
        # Original URL uses postgresql+psycopg2
        mock_pg.get_connection_url.return_value = (
            "postgresql+psycopg2://myuser:mypass@localhost:5432/mydb"
        )
        mock_pg_container.return_value = mock_pg

        with ServiceManager(postgres=True) as svc:
            # Should be converted to postgresql scheme
            assert svc.postgres_url == "postgresql://myuser:mypass@localhost:5432/mydb"
            assert "psycopg2" not in svc.postgres_url

    @patch("testcontainers.redis.RedisContainer")
    def test_service_manager_redis_custom_port(self, mock_redis_container):
        """Test ServiceManager with Redis on a custom port."""
        mock_redis = MagicMock()
        mock_redis.get_container_host_ip.return_value = "192.168.1.100"
        mock_redis.get_exposed_port.return_value = 6390
        mock_redis_container.return_value = mock_redis

        with ServiceManager(redis=True) as svc:
            assert svc.redis_url == "redis://192.168.1.100:6390/0"

    @patch("testcontainers.postgres.PostgresContainer")
    def test_service_manager_cleanup_on_exception(self, mock_pg_container):
        """Test that containers are cleaned up even if context block raises exception."""
        mock_pg = MagicMock()
        mock_pg.get_connection_url.return_value = "postgresql+psycopg2://user@localhost/db"
        mock_pg_container.return_value = mock_pg

        with pytest.raises(ValueError):
            with ServiceManager(postgres=True) as svc:
                assert svc.postgres_url is not None
                msg = "Test error"
                raise ValueError(msg)

        # Verify cleanup happened despite exception
        mock_pg.stop.assert_called_once()

    @patch("testcontainers.redis.RedisContainer")
    @patch("testcontainers.postgres.PostgresContainer")
    def test_service_manager_cleanup_order(self, mock_pg_container, mock_redis_container):
        """Test that containers are cleaned up in reverse order (LIFO)."""
        mock_pg = MagicMock()
        mock_pg.get_connection_url.return_value = "postgresql+psycopg2://user@localhost/db"
        mock_pg_container.return_value = mock_pg

        mock_redis = MagicMock()
        mock_redis.get_container_host_ip.return_value = "localhost"
        mock_redis.get_exposed_port.return_value = 6379
        mock_redis_container.return_value = mock_redis

        call_order = []

        def track_pg_stop():
            call_order.append("pg_stop")

        def track_redis_stop():
            call_order.append("redis_stop")

        mock_pg.stop.side_effect = track_pg_stop
        mock_redis.stop.side_effect = track_redis_stop

        with ServiceManager(postgres=True, redis=True):
            pass

        # Redis should be stopped before PostgreSQL (reverse order)
        assert call_order == ["redis_stop", "pg_stop"]

    @patch("testcontainers.postgres.PostgresContainer")
    def test_service_manager_postgres_container_image(self, mock_pg_container):
        """Test that PostgreSQL container is created with correct image."""
        mock_pg = MagicMock()
        mock_pg.get_connection_url.return_value = "postgresql+psycopg2://user@localhost/db"
        mock_pg_container.return_value = mock_pg

        with ServiceManager(postgres=True):
            mock_pg_container.assert_called_once_with("postgres:16-alpine")

    @patch("testcontainers.redis.RedisContainer")
    def test_service_manager_redis_container_image(self, mock_redis_container):
        """Test that Redis container is created with correct image."""
        mock_redis = MagicMock()
        mock_redis.get_container_host_ip.return_value = "localhost"
        mock_redis.get_exposed_port.return_value = 6379
        mock_redis_container.return_value = mock_redis

        with ServiceManager(redis=True):
            mock_redis_container.assert_called_once_with("redis:7-alpine")

    @patch("testcontainers.postgres.PostgresContainer")
    def test_service_manager_postgres_stop_error_handled(self, mock_pg_container):
        """Test that errors during container stop are logged but don't propagate."""
        mock_pg = MagicMock()
        mock_pg.get_connection_url.return_value = "postgresql+psycopg2://user@localhost/db"
        mock_pg.stop.side_effect = RuntimeError("Stop error")
        mock_pg_container.return_value = mock_pg

        # Should not raise even though stop() raises
        with ServiceManager(postgres=True):
            pass

        # Verify stop was attempted
        mock_pg.stop.assert_called_once()

    @patch("testcontainers.redis.RedisContainer")
    @patch("testcontainers.postgres.PostgresContainer")
    def test_service_manager_partial_failure_in_cleanup(
        self, mock_pg_container, mock_redis_container
    ):
        """Test that all containers are cleaned up even if one fails."""
        mock_pg = MagicMock()
        mock_pg.get_connection_url.return_value = "postgresql+psycopg2://user@localhost/db"
        mock_pg.stop.side_effect = RuntimeError("PG stop error")
        mock_pg_container.return_value = mock_pg

        mock_redis = MagicMock()
        mock_redis.get_container_host_ip.return_value = "localhost"
        mock_redis.get_exposed_port.return_value = 6379
        mock_redis_container.return_value = mock_redis

        with ServiceManager(postgres=True, redis=True):
            pass

        # Both should be cleaned up
        mock_pg.stop.assert_called_once()
        mock_redis.stop.assert_called_once()

    @patch("testcontainers.redis.RedisContainer")
    @patch("testcontainers.postgres.PostgresContainer")
    def test_service_manager_empty_context_list_on_error(
        self, mock_pg_container, mock_redis_container
    ):
        """Test that both services are tracked for cleanup."""
        mock_pg = MagicMock()
        mock_pg.get_connection_url.return_value = "postgresql+psycopg2://user@localhost/db"
        mock_pg_container.return_value = mock_pg

        mock_redis = MagicMock()
        mock_redis.get_container_host_ip.return_value = "localhost"
        mock_redis.get_exposed_port.return_value = 6379
        mock_redis_container.return_value = mock_redis

        with ServiceManager(postgres=True, redis=True) as svc:
            assert svc.postgres_url is not None
            assert svc.redis_url is not None

        # Both containers should have been stopped
        mock_pg.stop.assert_called_once()
        mock_redis.stop.assert_called_once()
