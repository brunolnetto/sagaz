"""
Additional tests to improve coverage for config.py and other low-coverage files.

These tests cover edge cases and branches not covered by existing tests.
"""

import os
from unittest import mock

import pytest

from sagaz.config import SagaConfig, configure, get_config

# Check for optional dependencies
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    import aiokafka

    AIOKAFKA_AVAILABLE = True
except ImportError:
    AIOKAFKA_AVAILABLE = False

try:
    import aio_pika

    AIOPIKA_AVAILABLE = True
except ImportError:
    AIOPIKA_AVAILABLE = False


class TestSagaConfigCoverage:
    """Tests for SagaConfig coverage gaps."""

    def test_config_with_custom_listener_instances(self):
        """Test config with custom listener instances (lines 186, 192)."""
        from sagaz.listeners import (
            LoggingSagaListener,
            MetricsSagaListener,
            TracingSagaListener,
        )

        custom_logging = LoggingSagaListener()
        custom_metrics = MetricsSagaListener()
        custom_tracing = TracingSagaListener()

        config = SagaConfig(
            logging=custom_logging,
            metrics=custom_metrics,
            tracing=custom_tracing,
        )

        # The custom instances should be in the listeners list
        assert custom_logging in config.listeners
        assert custom_metrics in config.listeners
        assert custom_tracing in config.listeners

    def test_config_derives_postgresql_outbox_without_conn_string(self):
        """Test config falls back to memory when PostgreSQL storage lacks conn string (line 144)."""
        from unittest.mock import MagicMock

        from sagaz.outbox.brokers.memory import InMemoryBroker
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage

        # Mock PostgreSQLSagaStorage without connection_string attribute
        mock_storage = MagicMock()
        mock_storage.__class__.__name__ = "PostgreSQLSagaStorage"
        # Remove connection_string attribute
        del mock_storage.connection_string

        config = SagaConfig(
            storage=mock_storage,
            broker=InMemoryBroker(),
        )

        # Should fall back to memory outbox
        assert isinstance(config._derived_outbox_storage, InMemoryOutboxStorage)

    @pytest.mark.skipif(not ASYNCPG_AVAILABLE, reason="Requires optional dependency: asyncpg")
    def test_parse_storage_url_postgresql(self):
        """Test _parse_storage_url with postgresql:// (lines 293-295)."""
        from sagaz.storage.postgresql import PostgreSQLSagaStorage

        storage = SagaConfig._parse_storage_url("postgresql://localhost/testdb")
        assert isinstance(storage, PostgreSQLSagaStorage)

    @pytest.mark.skipif(not ASYNCPG_AVAILABLE, reason="Requires optional dependency: asyncpg")
    def test_parse_storage_url_postgres(self):
        """Test _parse_storage_url with postgres:// (lines 293-295)."""
        from sagaz.storage.postgresql import PostgreSQLSagaStorage

        storage = SagaConfig._parse_storage_url("postgres://localhost/testdb")
        assert isinstance(storage, PostgreSQLSagaStorage)

    @pytest.mark.skipif(not REDIS_AVAILABLE, reason="Requires optional dependency: redis")
    def test_parse_storage_url_redis(self):
        """Test _parse_storage_url with redis:// (lines 297-299)."""
        from sagaz.storage.redis import RedisSagaStorage

        storage = SagaConfig._parse_storage_url("redis://localhost:6379/0")
        assert isinstance(storage, RedisSagaStorage)

    def test_parse_storage_url_unknown(self):
        """Test _parse_storage_url with unknown scheme raises error."""
        with pytest.raises(ValueError, match="Unknown storage URL scheme"):
            SagaConfig._parse_storage_url("mysql://localhost/db")

    @pytest.mark.skipif(not AIOKAFKA_AVAILABLE, reason="Requires optional dependency: aiokafka")
    def test_parse_broker_url_kafka(self):
        """Test _parse_broker_url with kafka:// (lines 311-315)."""
        from sagaz.outbox.brokers.kafka import KafkaBroker

        broker = SagaConfig._parse_broker_url("kafka://localhost:9092")
        assert isinstance(broker, KafkaBroker)

    @pytest.mark.skipif(not REDIS_AVAILABLE, reason="Requires optional dependency: redis")
    def test_parse_broker_url_redis(self):
        """Test _parse_broker_url with redis:// (lines 317-319)."""
        from sagaz.outbox.brokers.redis import RedisBroker

        broker = SagaConfig._parse_broker_url("redis://localhost:6379/0")
        assert isinstance(broker, RedisBroker)

    @pytest.mark.skipif(not AIOPIKA_AVAILABLE, reason="Requires optional dependency: aio-pika")
    def test_parse_broker_url_rabbitmq(self):
        """Test _parse_broker_url with rabbitmq:// (lines 321-323)."""
        from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = SagaConfig._parse_broker_url("rabbitmq://localhost:5672")
        assert isinstance(broker, RabbitMQBroker)

    @pytest.mark.skipif(not AIOPIKA_AVAILABLE, reason="Requires optional dependency: aio-pika")
    def test_parse_broker_url_amqp(self):
        """Test _parse_broker_url with amqp:// (lines 321-323)."""
        from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

        broker = SagaConfig._parse_broker_url("amqp://localhost:5672")
        assert isinstance(broker, RabbitMQBroker)

    def test_parse_broker_url_memory(self):
        """Test _parse_broker_url with memory:// (lines 325-327)."""
        from sagaz.outbox.brokers.memory import InMemoryBroker

        broker = SagaConfig._parse_broker_url("memory://")
        assert isinstance(broker, InMemoryBroker)

    def test_parse_broker_url_unknown(self):
        """Test _parse_broker_url with unknown scheme raises error."""
        with pytest.raises(ValueError, match="Unknown broker URL scheme"):
            SagaConfig._parse_broker_url("unknown://localhost")


class TestSagaConfigFromEnv:
    """Tests for SagaConfig.from_env() method."""

    def test_from_env_with_all_options(self):
        """Test from_env with all environment variables set."""
        env_vars = {
            "SAGAZ_STORAGE_URL": "memory://",
            "SAGAZ_BROKER_URL": "memory://",
            "SAGAZ_METRICS": "true",
            "SAGAZ_TRACING": "true",
            "SAGAZ_LOGGING": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            config = SagaConfig.from_env()

            from sagaz.storage.memory import InMemorySagaStorage

            assert isinstance(config.storage, InMemorySagaStorage)
            assert config.broker is not None
            assert config.metrics is True
            assert config.tracing is True
            assert config.logging is False

    def test_from_env_with_no_env_vars(self):
        """Test from_env with no environment variables (defaults)."""
        with mock.patch.dict(os.environ, {}, clear=True):
            # Clear specific SAGAZ vars if they exist
            for key in list(os.environ.keys()):
                if key.startswith("SAGAZ_"):
                    del os.environ[key]

            config = SagaConfig.from_env()

            # Default storage is InMemory
            from sagaz.storage.memory import InMemorySagaStorage

            assert isinstance(config.storage, InMemorySagaStorage)
            assert config.broker is None
            # Defaults: metrics=True, tracing=False, logging=True
            assert config.metrics is True
            assert config.tracing is False
            assert config.logging is True

    def test_from_env_boolean_parsing(self):
        """Test from_env boolean parsing variants."""
        # Test "1", "yes" variants
        env_vars = {
            "SAGAZ_METRICS": "1",
            "SAGAZ_TRACING": "yes",
            "SAGAZ_LOGGING": "0",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            config = SagaConfig.from_env()
            assert config.metrics is True
            assert config.tracing is True
            assert config.logging is False

        # Test "no" variant
        env_vars = {
            "SAGAZ_METRICS": "no",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            config = SagaConfig.from_env()
            assert config.metrics is False


class TestSagaStateMachineCoverage:
    """Tests for state_machine.py coverage gaps."""

    @pytest.mark.asyncio
    async def test_state_machine_without_saga(self):
        """Test SagaStateMachine without saga instance (line 36)."""
        from sagaz.state_machine import SagaStateMachine

        sm = SagaStateMachine(saga=None)

        # Guards should return True when saga is None
        assert sm.has_steps() is True
        assert sm.has_completed_steps() is True

    @pytest.mark.asyncio
    async def test_state_machine_callbacks_without_saga_methods(self):
        """Test callbacks when saga doesn't have the callback methods (lines 128, 133, 138, 143)."""
        from sagaz.state_machine import SagaStateMachine

        # Create a minimal saga-like object without callback methods
        class MinimalSaga:
            steps = ["step1"]
            completed_steps = []

        saga = MinimalSaga()
        sm = SagaStateMachine(saga=saga)

        # These should not raise even without callback methods
        await sm.on_enter_executing()
        await sm.on_enter_compensating()
        await sm.on_enter_completed()
        await sm.on_enter_rolled_back()
        await sm.on_enter_failed()

    @pytest.mark.asyncio
    async def test_state_machine_on_exit_executing(self):
        """Test on_exit_executing callback (line 155)."""
        from sagaz.state_machine import SagaStateMachine

        class SagaWithExit:
            steps = ["step1"]
            completed_steps = ["step1"]
            exit_called = False

            async def _on_exit_executing(self):
                self.exit_called = True

        saga = SagaWithExit()
        sm = SagaStateMachine(saga=saga)

        await sm.on_exit_executing()
        assert saga.exit_called is True


class TestDecoratorsCoverage:
    """Tests for decorators.py coverage gaps."""

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_compensating_status(self):
        """Test to_mermaid_with_execution with 'compensating' status (lines 453-455)."""
        from unittest.mock import AsyncMock, MagicMock

        from sagaz import Saga, action, compensate

        class TestSaga(Saga):
            saga_name = "test"

            @action("step_a")
            async def step_a(self, ctx):
                return {}

            @compensate("step_a")
            async def undo_a(self, ctx):
                pass

        saga = TestSaga()

        # Mock saga state with 'compensating' status
        mock_data = {
            "steps": [
                {"name": "step_a", "status": "compensating"},
            ]
        }

        mock_storage = MagicMock()
        mock_storage.load_saga_state = AsyncMock(return_value=mock_data)

        mermaid = await saga.to_mermaid_with_execution("saga-id", mock_storage)

        # step_a should be in completed (it completed before compensating)
        assert "step_a" in mermaid

    def test_saga_get_step_not_found(self):
        """Test Saga.get_step returns None for non-existent step (line 320)."""
        from sagaz import Saga, action

        class TestSaga(Saga):
            @action("existing_step")
            async def existing_step(self, ctx):
                return {}

        saga = TestSaga()

        # Get existing step
        step = saga.get_step("existing_step")
        assert step is not None

        # Get non-existent step
        step = saga.get_step("nonexistent")
        assert step is None


class TestCompensationGraphCoverage:
    """Tests for compensation_graph.py coverage gaps."""

    def test_compensation_graph_edge_cases(self):
        """Test compensation graph edge cases (lines 285, 296-297, 304)."""
        from sagaz.compensation_graph import SagaCompensationGraph

        graph = SagaCompensationGraph()

        # Register a compensation
        async def comp_fn(ctx):
            pass

        graph.register_compensation("step1", comp_fn)

        # Get compensation info for non-existent step
        info = graph.get_compensation_info("nonexistent")
        assert info is None

        # Get compensation order when nothing is executed
        order = graph.get_compensation_order()
        assert order == []


class TestMermaidAdditionalCoverage:
    """Additional tests for mermaid.py coverage."""

    def test_mermaid_add_start_to_roots_skips_unexecuted(self):
        """Test _add_start_to_roots skips unexecuted steps (line 249)."""
        from sagaz.mermaid import HighlightTrail, MermaidGenerator, StepInfo

        steps = [
            StepInfo(name="root_a", has_compensation=True),
            StepInfo(name="root_b", has_compensation=True),
        ]
        # Only root_a was executed
        trail = HighlightTrail(
            completed={"root_a"},
        )

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        # root_a should have START connection, root_b should not appear
        assert "START --> root_a" in mermaid

    def test_mermaid_add_leaves_to_success_skips_unexecuted(self):
        """Test _add_leaves_to_success skips unexecuted steps (line 280)."""
        from sagaz.mermaid import HighlightTrail, MermaidGenerator, StepInfo

        steps = [
            StepInfo(name="leaf_a", has_compensation=True),
            StepInfo(name="leaf_b", has_compensation=True),
        ]
        # Only leaf_a completed
        trail = HighlightTrail(
            completed={"leaf_a"},
        )

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        # leaf_a should have SUCCESS connection
        assert "leaf_a --> SUCCESS" in mermaid

    def test_mermaid_failure_edges_no_compensable_steps(self):
        """Test _add_failure_edges with no compensable steps (line 293)."""
        from sagaz.mermaid import MermaidGenerator, StepInfo

        steps = [
            StepInfo(name="step_a", has_compensation=False),
        ]

        generator = MermaidGenerator(steps=steps)
        mermaid = generator.generate()

        # No compensation edges should exist
        assert "comp_" not in mermaid

    def test_mermaid_dag_compensation_chain_skip_non_compensated(self):
        """Test _add_dag_compensation_chain skips non-compensated steps (lines 368, 385)."""
        from sagaz.mermaid import HighlightTrail, MermaidGenerator, StepInfo

        steps = [
            StepInfo(name="root", has_compensation=True),
            StepInfo(name="child_a", has_compensation=True, depends_on={"root"}),
            StepInfo(name="child_b", has_compensation=True, depends_on={"root"}),
        ]
        # Only child_a was compensated
        trail = HighlightTrail(
            completed={"root", "child_a", "child_b"},
            failed_step="child_b",
            compensated={"child_a"},
        )

        generator = MermaidGenerator(steps=steps, highlight_trail=trail)
        mermaid = generator.generate()

        # child_a compensation should appear
        assert "comp_child_a" in mermaid


class TestGlobalConfigFunctions:
    """Tests for global config functions."""

    def test_get_config_creates_default(self):
        """Test get_config creates default config when none exists."""
        import sagaz.config as config_module

        # Reset global config
        config_module._global_config = None

        config = get_config()
        assert config is not None

        from sagaz.storage.memory import InMemorySagaStorage

        assert isinstance(config.storage, InMemorySagaStorage)

    def test_configure_sets_global_config(self):
        """Test configure sets global config."""
        import sagaz.config as config_module

        new_config = SagaConfig()
        configure(new_config)

        assert config_module._global_config is new_config
