"""
Tests for outbox pattern components including:
- Broker factory (create_broker, get_available_brokers)
- State machine (SagaStateMachine, SagaStepStateMachine)
- Outbox types (OutboxEvent, OutboxConfig)
- Outbox storage (InMemoryOutboxStorage)
- Compensation graph edge cases
- Declarative saga decorators
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

# ============================================
# BROKER FACTORY TESTS
# ============================================


class TestBrokerFactory:
    def test_get_available_brokers_returns_list(self):
        """Test get_available_brokers returns at least memory"""
        from sagaz.outbox.brokers.factory import get_available_brokers

        available = get_available_brokers()

        assert isinstance(available, list)
        assert "memory" in available

    def test_print_available_brokers_output(self, capsys):
        """Test print_available_brokers produces output"""
        from sagaz.outbox.brokers.factory import print_available_brokers

        print_available_brokers()

        captured = capsys.readouterr()
        assert "Available Message Brokers" in captured.out
        assert "memory" in captured.out

    def test_create_broker_memory(self):
        """Test creating memory broker"""
        from sagaz.outbox.brokers.factory import create_broker
        from sagaz.outbox.brokers.memory import InMemoryBroker

        broker = create_broker("memory")

        assert isinstance(broker, InMemoryBroker)

    def test_create_broker_memory_uppercase(self):
        """Test creating memory broker with uppercase"""
        from sagaz.outbox.brokers.factory import create_broker
        from sagaz.outbox.brokers.memory import InMemoryBroker

        broker = create_broker("MEMORY")

        assert isinstance(broker, InMemoryBroker)

    def test_create_broker_memory_whitespace(self):
        """Test creating memory broker with whitespace"""
        from sagaz.outbox.brokers.factory import create_broker
        from sagaz.outbox.brokers.memory import InMemoryBroker

        broker = create_broker("  memory  ")

        assert isinstance(broker, InMemoryBroker)

    def test_create_broker_unknown_type(self):
        """Test creating broker with unknown type raises ValueError"""
        from sagaz.outbox.brokers.factory import create_broker

        with pytest.raises(ValueError) as exc_info:
            create_broker("unknown_broker")

        assert "Unknown broker type:" in str(exc_info.value)
        assert "unknown_broker" in str(exc_info.value)

    def test_create_broker_kafka_available(self):
        """Test creating Kafka broker when available"""
        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.factory import create_broker

            broker = create_broker("kafka")
            assert broker is not None

    def test_create_broker_kafka_with_config(self):
        """Test creating Kafka broker with configuration"""
        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.factory import create_broker

            broker = create_broker(
                "kafka", bootstrap_servers="localhost:9092", client_id="test-client"
            )
            assert broker is not None

    def test_create_broker_rabbitmq_available(self):
        """Test creating RabbitMQ broker when available"""
        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.factory import create_broker

            broker = create_broker("rabbitmq")
            assert broker is not None

    def test_create_broker_rabbitmq_aliases(self):
        """Test creating RabbitMQ broker with aliases"""
        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.factory import create_broker

            # Test 'rabbit' alias
            broker1 = create_broker("rabbit")
            assert broker1 is not None

            # Test 'amqp' alias
            broker2 = create_broker("amqp")
            assert broker2 is not None

    def test_create_broker_from_env_memory(self, monkeypatch):
        """Test create_broker_from_env with memory"""
        from sagaz.outbox.brokers.factory import create_broker_from_env
        from sagaz.outbox.brokers.memory import InMemoryBroker

        monkeypatch.setenv("BROKER_TYPE", "memory")

        broker = create_broker_from_env()

        assert isinstance(broker, InMemoryBroker)

    def test_create_broker_from_env_default(self, monkeypatch):
        """Test create_broker_from_env defaults to memory"""
        from sagaz.outbox.brokers.factory import create_broker_from_env
        from sagaz.outbox.brokers.memory import InMemoryBroker

        # Remove env var if set
        monkeypatch.delenv("BROKER_TYPE", raising=False)

        broker = create_broker_from_env()

        assert isinstance(broker, InMemoryBroker)

    def test_create_broker_from_env_unknown(self, monkeypatch):
        """Test create_broker_from_env with unknown type raises ValueError"""
        from sagaz.outbox.brokers.factory import create_broker_from_env

        monkeypatch.setenv("BROKER_TYPE", "unknown_type")

        with pytest.raises(ValueError) as exc_info:
            create_broker_from_env()

        assert "Unknown BROKER_TYPE" in str(exc_info.value)


# ============================================
# STATE MACHINE TESTS
# ============================================


class TestSagaStateMachine:
    @pytest.mark.asyncio
    async def test_state_machine_with_saga_with_steps(self):
        """Test state machine has_steps guard with saga that has steps"""
        from sagaz.state_machine import SagaStateMachine

        # Mock saga with steps
        mock_saga = Mock()
        mock_saga.steps = [Mock(), Mock()]
        mock_saga.completed_steps = []

        sm = SagaStateMachine(saga=mock_saga)

        assert sm.has_steps() is True

    @pytest.mark.asyncio
    async def test_state_machine_with_saga_no_steps(self):
        """Test state machine has_steps guard with saga without steps"""
        from sagaz.state_machine import SagaStateMachine

        # Mock saga without steps
        mock_saga = Mock()
        mock_saga.steps = []
        mock_saga.completed_steps = []

        sm = SagaStateMachine(saga=mock_saga)

        assert sm.has_steps() is False

    @pytest.mark.asyncio
    async def test_state_machine_has_completed_steps_true(self):
        """Test has_completed_steps guard returns True when steps completed"""
        from sagaz.state_machine import SagaStateMachine

        mock_saga = Mock()
        mock_saga.steps = [Mock()]
        mock_saga.completed_steps = [Mock()]

        sm = SagaStateMachine(saga=mock_saga)

        assert sm.has_completed_steps() is True

    @pytest.mark.asyncio
    async def test_state_machine_has_completed_steps_false(self):
        """Test has_completed_steps guard returns False when no steps completed"""
        from sagaz.state_machine import SagaStateMachine

        mock_saga = Mock()
        mock_saga.steps = [Mock()]
        mock_saga.completed_steps = []

        sm = SagaStateMachine(saga=mock_saga)

        assert sm.has_completed_steps() is False

    @pytest.mark.asyncio
    async def test_state_machine_callbacks_with_saga(self):
        """Test state machine callbacks invoke saga methods"""
        from sagaz.state_machine import SagaStateMachine

        # Mock saga with callback methods
        mock_saga = Mock()
        mock_saga.steps = [Mock()]
        mock_saga.completed_steps = []
        mock_saga._on_enter_executing = AsyncMock()
        mock_saga._on_exit_pending = AsyncMock()

        sm = SagaStateMachine(saga=mock_saga)
        await sm.activate_initial_state()

        # Trigger start transition
        await sm.start()

        # Verify callbacks were called
        mock_saga._on_enter_executing.assert_awaited_once()
        mock_saga._on_exit_pending.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_state_machine_callback_saga_without_method(self):
        """Test state machine handles saga without callback methods gracefully"""
        from sagaz.state_machine import SagaStateMachine

        # Mock saga without callback methods - use spec to strictly control attributes
        mock_saga = Mock(spec=["steps", "completed_steps"])
        mock_saga.steps = [Mock()]
        mock_saga.completed_steps = []

        sm = SagaStateMachine(saga=mock_saga)
        await sm.activate_initial_state()

        # Should not raise even without callbacks
        await sm.start()
        assert sm.current_state.id == "executing"

    def test_validate_state_transition_valid(self):
        """Test validate_state_transition with valid transitions"""
        from sagaz.state_machine import validate_state_transition

        assert validate_state_transition("Pending", "Executing") is True
        assert validate_state_transition("Executing", "Completed") is True
        assert validate_state_transition("Executing", "Compensating") is True
        assert validate_state_transition("Executing", "Failed") is True
        assert validate_state_transition("Compensating", "RolledBack") is True
        assert validate_state_transition("Compensating", "Failed") is True

    def test_validate_state_transition_invalid(self):
        """Test validate_state_transition with invalid transitions"""
        from sagaz.state_machine import validate_state_transition

        assert validate_state_transition("Pending", "Completed") is False
        assert validate_state_transition("Completed", "Executing") is False
        assert validate_state_transition("Failed", "Completed") is False
        assert validate_state_transition("RolledBack", "Pending") is False

    def test_get_valid_next_states(self):
        """Test get_valid_next_states returns correct states"""
        from sagaz.state_machine import get_valid_next_states

        assert get_valid_next_states("Pending") == ["Executing"]
        assert set(get_valid_next_states("Executing")) == {"Completed", "Compensating", "Failed"}
        assert set(get_valid_next_states("Compensating")) == {"RolledBack", "Failed"}
        assert get_valid_next_states("Completed") == []
        assert get_valid_next_states("Failed") == []
        assert get_valid_next_states("RolledBack") == []

    def test_get_valid_next_states_unknown(self):
        """Test get_valid_next_states with unknown state"""
        from sagaz.state_machine import get_valid_next_states

        assert get_valid_next_states("Unknown") == []


class TestSagaStepStateMachine:
    @pytest.mark.asyncio
    async def test_step_state_machine_initialization(self):
        """Test step state machine initializes correctly"""
        from sagaz.state_machine import SagaStepStateMachine

        sm = SagaStepStateMachine(step_name="test_step")
        await sm.activate_initial_state()

        assert sm.step_name == "test_step"
        assert sm.current_state.id == "pending"

    @pytest.mark.asyncio
    async def test_step_state_machine_full_success_path(self):
        """Test step state machine through success path"""
        from sagaz.state_machine import SagaStepStateMachine

        sm = SagaStepStateMachine(step_name="payment")
        await sm.activate_initial_state()

        await sm.start()
        assert sm.current_state.id == "executing"

        await sm.succeed()
        assert sm.current_state.id == "completed"

    @pytest.mark.asyncio
    async def test_step_state_machine_failure_path(self):
        """Test step state machine through failure path"""
        from sagaz.state_machine import SagaStepStateMachine

        sm = SagaStepStateMachine(step_name="failing_step")
        await sm.activate_initial_state()

        await sm.start()
        await sm.fail()

        assert sm.current_state.id == "failed"

    @pytest.mark.asyncio
    async def test_step_state_machine_compensation_path(self):
        """Test step state machine through compensation path"""
        from sagaz.state_machine import SagaStepStateMachine

        sm = SagaStepStateMachine(step_name="compensated_step")
        await sm.activate_initial_state()

        await sm.start()
        await sm.succeed()
        await sm.compensate()

        assert sm.current_state.id == "compensating"

        await sm.compensation_success()
        assert sm.current_state.id == "compensated"

    @pytest.mark.asyncio
    async def test_step_state_machine_compensation_failure(self):
        """Test step compensation failure transitions to failed"""
        from sagaz.state_machine import SagaStepStateMachine

        sm = SagaStepStateMachine(step_name="comp_fail_step")
        await sm.activate_initial_state()

        await sm.start()
        await sm.succeed()
        await sm.compensate()
        await sm.compensation_failure()

        assert sm.current_state.id == "failed"


# ============================================
# OUTBOX TYPES TESTS
# ============================================


class TestOutboxTypes:
    def test_outbox_config_defaults(self):
        """Test OutboxConfig has sensible defaults"""
        from sagaz.outbox.types import OutboxConfig

        config = OutboxConfig()

        assert config.batch_size == 100
        assert config.poll_interval_seconds == 1.0
        assert config.max_retries == 10

    def test_outbox_config_custom_values(self):
        """Test OutboxConfig with custom values"""
        from sagaz.outbox.types import OutboxConfig

        config = OutboxConfig(batch_size=50, poll_interval_seconds=2.5, max_retries=5)

        assert config.batch_size == 50
        assert config.poll_interval_seconds == 2.5
        assert config.max_retries == 5

    def test_outbox_config_from_env(self, monkeypatch):
        """Test OutboxConfig.from_env reads environment"""
        from sagaz.outbox.types import OutboxConfig

        monkeypatch.setenv("OUTBOX_BATCH_SIZE", "200")
        monkeypatch.setenv("OUTBOX_MAX_RETRIES", "15")

        config = OutboxConfig.from_env()

        assert config.batch_size == 200
        assert config.max_retries == 15

    def test_outbox_event_to_dict(self):
        """Test OutboxEvent to_dict method"""
        from sagaz.outbox.types import OutboxEvent

        event = OutboxEvent(
            saga_id="saga-123",
            event_type="order.created",
            payload={"order_id": "123", "amount": 99.99},
        )

        event_dict = event.to_dict()

        assert event_dict["saga_id"] == "saga-123"
        assert event_dict["event_type"] == "order.created"
        assert "payload" in event_dict
        assert "created_at" in event_dict

    def test_outbox_event_from_dict(self):
        """Test OutboxEvent from_dict method"""

        from sagaz.outbox.types import OutboxEvent, OutboxStatus

        data = {
            "event_id": "evt-123",
            "saga_id": "saga-456",
            "event_type": "payment.processed",
            "payload": {"amount": 50.00},
            "status": "pending",
        }

        event = OutboxEvent.from_dict(data)

        assert event.event_id == "evt-123"
        assert event.saga_id == "saga-456"
        assert event.event_type == "payment.processed"
        assert event.status == OutboxStatus.PENDING

    def test_outbox_event_aggregate_id_defaults_to_saga_id(self):
        """Test aggregate_id defaults to saga_id"""
        from sagaz.outbox.types import OutboxEvent

        event = OutboxEvent(saga_id="saga-789", event_type="test.event", payload={})

        assert event.aggregate_id == "saga-789"


# ============================================
# OUTBOX STORAGE MEMORY TESTS
# ============================================


class TestOutboxMemoryStorage:
    @pytest.mark.asyncio
    async def test_memory_storage_get_nonexistent_event(self):
        """Test getting nonexistent event returns None"""
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage

        storage = InMemoryOutboxStorage()

        event = await storage.get_by_id("nonexistent-id")

        assert event is None

    @pytest.mark.asyncio
    async def test_memory_storage_update_nonexistent_raises(self):
        """Test updating nonexistent event raises error"""
        from sagaz.outbox.storage.base import OutboxStorageError
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage
        from sagaz.outbox.types import OutboxStatus

        storage = InMemoryOutboxStorage()

        with pytest.raises(OutboxStorageError):
            await storage.update_status("nonexistent-id", OutboxStatus.SENT)

    @pytest.mark.asyncio
    async def test_memory_storage_claim_empty(self):
        """Test claiming events when none available"""
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage

        storage = InMemoryOutboxStorage()

        events = await storage.claim_batch(worker_id="worker-1", batch_size=10)

        assert events == []

    @pytest.mark.asyncio
    async def test_memory_storage_insert_and_claim(self):
        """Test inserting and claiming events"""
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage
        from sagaz.outbox.types import OutboxEvent, OutboxStatus

        storage = InMemoryOutboxStorage()

        # Insert event
        event = OutboxEvent(saga_id="saga-1", event_type="test.event", payload={"data": "test"})
        await storage.insert(event)

        # Claim it
        claimed = await storage.claim_batch(worker_id="worker-1", batch_size=10)

        assert len(claimed) == 1
        assert claimed[0].event_id == event.event_id
        assert claimed[0].status == OutboxStatus.CLAIMED
        assert claimed[0].worker_id == "worker-1"

    @pytest.mark.asyncio
    async def test_memory_storage_get_pending_count(self):
        """Test getting pending event count"""
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage
        from sagaz.outbox.types import OutboxEvent

        storage = InMemoryOutboxStorage()

        # Initially empty
        assert await storage.get_pending_count() == 0

        # Add event
        event = OutboxEvent(saga_id="saga-1", event_type="test.event", payload={})
        await storage.insert(event)

        assert await storage.get_pending_count() == 1

    @pytest.mark.asyncio
    async def test_memory_storage_clear(self):
        """Test clearing all events"""
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage
        from sagaz.outbox.types import OutboxEvent

        storage = InMemoryOutboxStorage()

        event = OutboxEvent(saga_id="saga-1", event_type="test.event", payload={})
        await storage.insert(event)

        storage.clear()

        assert await storage.get_pending_count() == 0


# ============================================
# KAFKA/RABBITMQ BROKER TESTS (Mock-based)
# ============================================


class TestKafkaBrokerMocked:
    """Tests for Kafka broker using mocks"""

    def test_kafka_broker_config_defaults(self):
        """Test KafkaBrokerConfig has sensible defaults"""
        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.kafka import KafkaBrokerConfig

            config = KafkaBrokerConfig()

            assert config.bootstrap_servers is not None
            assert config.client_id is not None

    def test_kafka_broker_from_env(self, monkeypatch):
        """Test KafkaBroker.from_env creates broker from environment"""
        with (
            patch("sagaz.outbox.brokers.kafka.KAFKA_AVAILABLE", True),
            patch("sagaz.outbox.brokers.kafka.AIOKafkaProducer"),
        ):
            from sagaz.outbox.brokers.kafka import KafkaBroker

            monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
            monkeypatch.setenv("KAFKA_CLIENT_ID", "test-client")

            broker = KafkaBroker.from_env()

            assert broker is not None
            assert broker.config.bootstrap_servers == "localhost:9092"


class TestRabbitMQBrokerMocked:
    """Tests for RabbitMQ broker using mocks"""

    def test_rabbitmq_broker_config_defaults(self):
        """Test RabbitMQBrokerConfig has sensible defaults"""
        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBrokerConfig

            config = RabbitMQBrokerConfig()

            assert config.url is not None
            assert config.exchange_name is not None

    def test_rabbitmq_broker_from_env(self, monkeypatch):
        """Test RabbitMQBroker.from_env creates broker from environment"""
        with (
            patch("sagaz.outbox.brokers.rabbitmq.RABBITMQ_AVAILABLE", True),
            patch("sagaz.outbox.brokers.rabbitmq.aio_pika"),
        ):
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

            monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
            monkeypatch.setenv("RABBITMQ_EXCHANGE", "test-exchange")

            broker = RabbitMQBroker.from_env()

            assert broker is not None
            assert broker.config.exchange_name == "test-exchange"


# ============================================
# COMPENSATION GRAPH EDGE CASES
# ============================================


class TestCompensationGraph:
    def test_compensation_graph_empty(self):
        """Test compensation graph with no nodes"""
        from sagaz.compensation_graph import SagaCompensationGraph

        graph = SagaCompensationGraph()

        order = graph.get_compensation_order()

        assert order == []

    def test_compensation_graph_single_step(self):
        """Test compensation graph with single registered step"""
        from sagaz.compensation_graph import CompensationType, SagaCompensationGraph

        async def compensate(ctx):
            pass

        graph = SagaCompensationGraph()
        graph.register_compensation(
            "step1", compensate, compensation_type=CompensationType.MECHANICAL
        )
        graph.mark_step_executed("step1")

        order = graph.get_compensation_order()

        assert len(order) == 1
        assert "step1" in order[0]

    def test_compensation_graph_multiple_independent(self):
        """Test compensation graph with independent steps"""
        from sagaz.compensation_graph import SagaCompensationGraph

        async def compensate(ctx):
            pass

        graph = SagaCompensationGraph()
        graph.register_compensation("step1", compensate)
        graph.register_compensation("step2", compensate)
        graph.register_compensation("step3", compensate)
        graph.mark_step_executed("step1")
        graph.mark_step_executed("step2")
        graph.mark_step_executed("step3")

        order = graph.get_compensation_order()

        # All independent, should be in single level
        assert len(order) == 1
        assert set(order[0]) == {"step1", "step2", "step3"}

    def test_compensation_graph_repr(self):
        """Test compensation graph string representation"""
        from sagaz.compensation_graph import SagaCompensationGraph

        graph = SagaCompensationGraph()

        repr_str = repr(graph)

        assert "SagaCompensationGraph" in repr_str
        assert "nodes=0" in repr_str


# ============================================
# DECORATORS EDGE CASES
# ============================================


class TestDeclarativeSaga:
    @pytest.mark.asyncio
    async def test_saga_empty_run(self):
        """Test running saga with no steps"""
        from sagaz.decorators import Saga

        class EmptySaga(Saga):
            pass

        saga = EmptySaga()
        # run() returns the context dict for declarative sagas
        result = await saga.run({})

        assert isinstance(result, dict)
        # Empty saga returns empty context
        assert len(saga.get_steps()) == 0

    @pytest.mark.asyncio
    async def test_saga_step_with_no_compensation(self):
        """Test saga step without compensation defined"""
        from sagaz.decorators import Saga, step

        class NoCompSaga(Saga):
            @step(name="action_only")
            async def action_only(self, ctx):
                return {"done": True}

        saga = NoCompSaga()
        result = await saga.run({})

        assert isinstance(result, dict)
        assert result.get("done") is True
        assert len(saga.get_steps()) == 1


# ============================================
# OUTBOX ERRORS COVERAGE
# ============================================


class TestOutboxErrors:
    def test_outbox_publish_error(self):
        """Test OutboxPublishError includes event info"""
        from sagaz.outbox.types import OutboxEvent, OutboxPublishError

        event = OutboxEvent(saga_id="saga-1", event_type="test.event", payload={})

        original_error = ValueError("Connection refused")
        error = OutboxPublishError(event, "Broker unavailable", cause=original_error)

        assert event.event_id in str(error)
        assert "Broker unavailable" in str(error)
        assert error.cause == original_error

    def test_outbox_claim_error(self):
        """Test OutboxClaimError"""
        from sagaz.outbox.types import OutboxClaimError

        error = OutboxClaimError("Failed to acquire lock")

        assert "lock" in str(error)
