"""
Tests for SagaConfig - unified configuration for the Saga framework.
"""

import logging
import os
from unittest.mock import patch

import pytest

from sagaz import Saga, SagaConfig, action, configure, get_config
from sagaz.listeners import (
    LoggingSagaListener,
    MetricsSagaListener,
    OutboxSagaListener,
    SagaListener,
    TracingSagaListener,
)
from sagaz.outbox.brokers.memory import InMemoryBroker
from sagaz.outbox.storage.memory import InMemoryOutboxStorage
from sagaz.storage.memory import InMemorySagaStorage


class TestSagaConfigBasics:
    """Test basic SagaConfig functionality."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SagaConfig()

        assert isinstance(config.storage, InMemorySagaStorage)
        assert config.broker is None
        assert config.outbox_storage is None
        assert config.metrics is True
        assert config.tracing is False
        assert config.logging is True
        assert config.default_timeout == 60.0
        assert config.default_max_retries == 3
        assert config.failure_strategy == "FAIL_FAST_WITH_GRACE"

    def test_custom_storage(self):
        """Test with custom storage instance."""
        storage = InMemorySagaStorage()
        config = SagaConfig(storage=storage)

        assert config.storage is storage

    def test_custom_broker(self):
        """Test with custom broker instance."""
        broker = InMemoryBroker()
        config = SagaConfig(broker=broker)

        assert config.broker is broker

    def test_custom_timeout_and_retries(self):
        """Test with custom timeout and retry settings."""
        config = SagaConfig(
            default_timeout=120.0,
            default_max_retries=5,
            failure_strategy="WAIT_ALL",
        )

        assert config.default_timeout == 120.0
        assert config.default_max_retries == 5
        assert config.failure_strategy == "WAIT_ALL"


class TestSagaConfigListeners:
    """Test listener configuration."""

    def test_default_listeners(self):
        """Test default listeners (logging + metrics)."""
        config = SagaConfig()
        listeners = config.listeners

        assert len(listeners) == 2
        assert any(isinstance(l, LoggingSagaListener) for l in listeners)
        assert any(isinstance(l, MetricsSagaListener) for l in listeners)

    def test_disable_logging(self):
        """Test disabling logging listener."""
        config = SagaConfig(logging=False)
        listeners = config.listeners

        assert not any(isinstance(l, LoggingSagaListener) for l in listeners)

    def test_disable_metrics(self):
        """Test disabling metrics listener."""
        config = SagaConfig(metrics=False)
        listeners = config.listeners

        assert not any(isinstance(l, MetricsSagaListener) for l in listeners)

    def test_enable_tracing(self):
        """Test enabling tracing listener."""
        config = SagaConfig(tracing=True)
        listeners = config.listeners

        assert any(isinstance(l, TracingSagaListener) for l in listeners)

    def test_custom_listener_instance(self):
        """Test providing custom listener instance."""
        custom_logger = LoggingSagaListener(level=logging.DEBUG)
        config = SagaConfig(logging=custom_logger)
        listeners = config.listeners

        assert custom_logger in listeners

    def test_broker_adds_outbox_listener(self):
        """Test that broker configuration adds outbox listener."""
        broker = InMemoryBroker()
        config = SagaConfig(broker=broker)
        listeners = config.listeners

        assert any(isinstance(l, OutboxSagaListener) for l in listeners)


class TestSagaConfigOutboxStorageDerivation:
    """Test outbox storage derivation from saga storage."""

    def test_no_broker_no_outbox_derivation(self):
        """Test no outbox storage derived when broker is not set."""
        config = SagaConfig()

        assert config._derived_outbox_storage is None

    def test_broker_with_explicit_outbox_storage(self):
        """Test explicit outbox storage is used when provided."""
        outbox = InMemoryOutboxStorage()
        config = SagaConfig(
            broker=InMemoryBroker(),
            outbox_storage=outbox,
        )

        assert config._derived_outbox_storage is outbox

    def test_broker_with_memory_storage_warns(self, caplog):
        """Test warning when broker is set with in-memory storage."""
        with caplog.at_level(logging.WARNING):
            config = SagaConfig(broker=InMemoryBroker())

        assert "events will NOT survive restarts" in caplog.text
        assert isinstance(config._derived_outbox_storage, InMemoryOutboxStorage)

    def test_broker_with_postgresql_storage_derives(self, caplog):
        """Test PostgreSQL outbox storage derived from PostgreSQL saga storage."""
        with (
            patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True),
            patch("sagaz.storage.postgresql.asyncpg"),
            patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True),
            patch("sagaz.outbox.storage.postgresql.asyncpg"),
        ):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            storage = PostgreSQLSagaStorage("postgresql://localhost/db")

            with caplog.at_level(logging.WARNING):
                SagaConfig(storage=storage, broker=InMemoryBroker())

            assert "PostgreSQLOutboxStorage" in caplog.text
            assert "transactional guarantees" in caplog.text

    def test_broker_with_redis_storage_warns(self, caplog):
        """Test warning when broker is set with Redis storage."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.redis.redis"):
                from sagaz.storage.redis import RedisSagaStorage

                storage = RedisSagaStorage("redis://localhost")

                with caplog.at_level(logging.WARNING):
                    SagaConfig(storage=storage, broker=InMemoryBroker())

                assert "events will NOT survive restarts" in caplog.text


class TestSagaConfigImmutableUpdates:
    """Test immutable update methods."""

    def test_with_storage(self):
        """Test with_storage creates new config."""
        original = SagaConfig()
        new_storage = InMemorySagaStorage()

        updated = original.with_storage(new_storage)

        assert updated is not original
        assert updated.storage is new_storage
        assert original.storage is not new_storage

    def test_with_broker(self):
        """Test with_broker creates new config."""
        original = SagaConfig()
        broker = InMemoryBroker()

        updated = original.with_broker(broker)

        assert updated is not original
        assert updated.broker is broker
        assert original.broker is None

    def test_with_broker_and_outbox(self):
        """Test with_broker can set outbox storage too."""
        original = SagaConfig()
        broker = InMemoryBroker()
        outbox = InMemoryOutboxStorage()

        updated = original.with_broker(broker, outbox_storage=outbox)

        assert updated.broker is broker
        assert updated.outbox_storage is outbox


class TestSagaConfigFromEnv:
    """Test environment variable configuration."""

    def test_from_env_default(self):
        """Test from_env with no environment variables."""
        with patch.dict(os.environ, {}, clear=True):
            config = SagaConfig.from_env()

        assert isinstance(config.storage, InMemorySagaStorage)
        assert config.broker is None
        assert config.metrics is True
        assert config.logging is True
        assert config.tracing is False

    def test_from_env_memory_storage(self):
        """Test from_env with memory:// storage URL."""
        with patch.dict(os.environ, {"SAGAZ_STORAGE_URL": "memory://"}):
            config = SagaConfig.from_env()

        assert isinstance(config.storage, InMemorySagaStorage)

    def test_from_env_metrics_disabled(self):
        """Test from_env with metrics disabled."""
        with patch.dict(os.environ, {"SAGAZ_METRICS": "false"}):
            config = SagaConfig.from_env()

        assert config.metrics is False

    def test_from_env_tracing_enabled(self):
        """Test from_env with tracing enabled."""
        with patch.dict(os.environ, {"SAGAZ_TRACING": "true"}):
            config = SagaConfig.from_env()

        assert config.tracing is True

    def test_from_env_invalid_storage_url(self):
        """Test from_env raises on invalid storage URL."""
        with patch.dict(os.environ, {"SAGAZ_STORAGE_URL": "invalid://foo"}):
            with pytest.raises(ValueError, match="Unknown storage URL"):
                SagaConfig.from_env()

    def test_from_env_invalid_broker_url(self):
        """Test from_env raises on invalid broker URL."""
        with patch.dict(os.environ, {"SAGAZ_BROKER_URL": "invalid://foo"}):
            with pytest.raises(ValueError, match="Unknown broker URL"):
                SagaConfig.from_env()


class TestGlobalConfiguration:
    """Test global configuration functions."""

    def test_get_config_default(self):
        """Test get_config returns default config."""
        # Reset global config
        import sagaz.config

        sagaz.config._global_config = None

        config = get_config()
        assert isinstance(config, SagaConfig)

    def test_configure_sets_global(self):
        """Test configure sets the global config."""
        custom = SagaConfig(default_timeout=999.0)
        configure(custom)

        retrieved = get_config()
        assert retrieved.default_timeout == 999.0


class TestSagaIntegrationWithConfig:
    """Test Saga class integration with SagaConfig."""

    def test_saga_uses_global_config_listeners(self):
        """Test that Saga uses listeners from global config."""
        # Configure with specific listener
        custom_logger = LoggingSagaListener(level=logging.DEBUG)
        config = SagaConfig(
            logging=custom_logger,
            metrics=False,
            tracing=False,
        )
        configure(config)

        class TestSaga(Saga):
            saga_name = "test"

            @action("step1")
            async def step1(self, ctx):
                return {"ok": True}

        saga = TestSaga()

        # Saga should have the custom logger from config
        assert custom_logger in saga._instance_listeners

    def test_saga_class_listeners_override_config(self):
        """Test that class-level listeners override config."""
        # Configure global
        configure(SagaConfig(metrics=True, logging=True))

        # Class defines its own listeners
        class_listener = LoggingSagaListener()

        class TestSaga(Saga):
            saga_name = "test"
            listeners = [class_listener]

            @action("step1")
            async def step1(self, ctx):
                return {"ok": True}

        saga = TestSaga()

        # Class listeners should be used, not config listeners
        assert class_listener in saga._instance_listeners

    def test_saga_with_explicit_config(self):
        """Test creating saga with explicit config."""
        explicit_config = SagaConfig(default_timeout=30.0)

        class TestSaga(Saga):
            saga_name = "test"

            @action("step1")
            async def step1(self, ctx):
                return {"ok": True}

        saga = TestSaga(config=explicit_config)

        assert saga._config.default_timeout == 30.0


class TestSagaConfigRepr:
    """Test SagaConfig string representation."""

    def test_repr_shows_key_fields(self):
        """Test repr shows important configuration."""
        config = SagaConfig()
        repr_str = repr(config)

        assert "SagaConfig" in repr_str
        assert "storage=" in repr_str
        assert "broker=" in repr_str
        assert "metrics=" in repr_str
