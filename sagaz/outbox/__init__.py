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
    
Storage (sagaz.outbox.storage):
    - OutboxStorage: Storage interface
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

# Storage imports
from sagaz.outbox.storage import (
    InMemoryOutboxStorage,
    OutboxStorage,
    OutboxStorageError,
    PostgreSQLOutboxStorage,
)
from sagaz.outbox.types import (
    OutboxClaimError,
    OutboxConfig,
    OutboxError,
    OutboxEvent,
    OutboxPublishError,
    OutboxStatus,
)
from sagaz.outbox.worker import OutboxWorker

__all__ = [
    # Core types
    "OutboxEvent",
    "OutboxStatus",
    "OutboxConfig",

    # Storage
    "OutboxStorage",
    "InMemoryOutboxStorage",
    "PostgreSQLOutboxStorage",
    "OutboxStorageError",

    # Broker interface
    "MessageBroker",
    "BaseBroker",
    "InMemoryBroker",
    "BrokerConfig",
    "BrokerError",
    "BrokerConnectionError",
    "BrokerPublishError",

    # Broker implementations
    "KafkaBroker",
    "RabbitMQBroker",

    # Broker factory
    "create_broker",
    "create_broker_from_env",
    "get_available_brokers",
    "print_available_brokers",

    # State machine
    "OutboxStateMachine",
    "InvalidStateTransitionError",

    # Worker
    "OutboxWorker",

    # Optimistic sending & consumer inbox
    "OptimisticPublisher",
    "ConsumerInbox",

    # Exceptions
    "OutboxError",
    "OutboxPublishError",
    "OutboxClaimError",
]
