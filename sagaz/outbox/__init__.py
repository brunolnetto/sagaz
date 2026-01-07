"""
Sagaz Outbox Pattern - Transactional Outbox for Reliable Messaging

The outbox pattern ensures exactly-once message delivery by:
1. Storing messages atomically with saga state changes
2. Polling and publishing messages reliably
3. Handling retries and dead-letter queue

Quick Start:
    >>> from sagaz.outbox import (
    ...     OutboxEvent,
    ...     OutboxWorker,
    ...     InMemoryOutboxStorage,
    ...     create_broker,
    ... )
    >>>
    >>> # Create storage and broker
    >>> storage = InMemoryOutboxStorage()
    >>> broker = create_broker("memory")  # or "kafka", "rabbitmq"
    >>> await broker.connect()
    >>>
    >>> # Insert an event
    >>> event = OutboxEvent(
    ...     saga_id="order-123",
    ...     event_type="OrderCreated",
    ...     payload={"order_id": "ORD-456"},
    ... )
    >>> await storage.insert(event)
    >>>
    >>> # Process with worker
    >>> worker = OutboxWorker(storage, broker)
    >>> await worker.process_batch()

Components:
    - OutboxEvent: Event payload and metadata
    - OutboxStatus: Event lifecycle states
    - OutboxConfig: Worker configuration

Storage (sagaz.storage.backends):
    - OutboxStorage: Storage interface (sagaz.storage.interfaces)
    - InMemoryOutboxStorage: For testing
    - PostgreSQLOutboxStorage: Production (requires asyncpg)

Brokers (sagaz.outbox.brokers):
    - MessageBroker: Broker interface
    - InMemoryBroker: For testing
    - KafkaBroker: Apache Kafka (requires aiokafka)
    - RabbitMQBroker: RabbitMQ/AMQP (requires aio-pika)

Worker:
    - OutboxWorker: Background processor
    - OutboxStateMachine: Event state transitions

Factory Functions:
    - create_broker(): Create a broker by type
    - get_available_brokers(): List available broker backends
"""

# Broker imports
from sagaz.outbox.brokers import (
    BaseBroker,
    BrokerConfig,
    BrokerConnectionError,
    BrokerError,
    BrokerPublishError,
    InMemoryBroker,
    KafkaBroker,
    MessageBroker,
    RabbitMQBroker,
    create_broker,
    create_broker_from_env,
    get_available_brokers,
    print_available_brokers,
)
from sagaz.outbox.consumer_inbox import ConsumerInbox

# Optimistic sending and consumer inbox
from sagaz.outbox.optimistic_publisher import OptimisticPublisher
from sagaz.outbox.state_machine import (
    InvalidStateTransitionError,
    OutboxStateMachine,
)

# Types - these don't cause circular imports
from sagaz.outbox.types import (
    OutboxClaimError,
    OutboxConfig,
    OutboxError,
    OutboxEvent,
    OutboxPublishError,
    OutboxStatus,
)
from sagaz.outbox.worker import OutboxWorker


# Lazy imports for storage classes to avoid circular imports
def __getattr__(name: str):
    """Lazy import for storage classes to avoid circular imports."""
    if name == "InMemoryOutboxStorage":
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage
        return InMemoryOutboxStorage
    if name == "OutboxStorage":
        from sagaz.storage.interfaces.outbox import OutboxStorage
        return OutboxStorage
    if name == "OutboxStorageError":
        from sagaz.storage.interfaces.outbox import OutboxStorageError
        return OutboxStorageError
    if name == "PostgreSQLOutboxStorage":
        from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
        return PostgreSQLOutboxStorage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseBroker",
    "BrokerConfig",
    "BrokerConnectionError",
    "BrokerError",
    "BrokerPublishError",
    "ConsumerInbox",
    "InMemoryBroker",
    "InMemoryOutboxStorage",
    "InvalidStateTransitionError",
    # Broker implementations
    "KafkaBroker",
    # Broker interface
    "MessageBroker",
    # Optimistic sending & consumer inbox
    "OptimisticPublisher",
    "OutboxClaimError",
    "OutboxConfig",
    # Exceptions
    "OutboxError",
    # Core types
    "OutboxEvent",
    "OutboxPublishError",
    # State machine
    "OutboxStateMachine",
    "OutboxStatus",
    # Storage
    "OutboxStorage",
    "OutboxStorageError",
    # Worker
    "OutboxWorker",
    "PostgreSQLOutboxStorage",
    "RabbitMQBroker",
    # Broker factory
    "create_broker",
    "create_broker_from_env",
    "get_available_brokers",
    "print_available_brokers",
]
