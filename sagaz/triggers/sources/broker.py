"""
Broker integration for message-driven saga triggering.

Connects existing Sagaz message brokers (Kafka, RabbitMQ, Redis, etc.)
to the trigger system, allowing sagas to start from message events.

Example:
    class OrderProcessor(Saga):
        @trigger(source="broker", topic="orders.created")
        def on_order(self, event):
            return {"order_id": event["id"]}

        @action("process")
        async def process(self, ctx):
            await process_order(ctx["order_id"])

    # Create consumer with broker
    from sagaz.outbox.brokers.kafka import KafkaBroker
    broker = KafkaBroker(bootstrap_servers="localhost:9092")
    consumer = BrokerTriggerConsumer(broker=broker)
    await consumer.start()
"""

import asyncio
from typing import Any

from sagaz.core.logger import get_logger
from sagaz.triggers import fire_event
from sagaz.triggers.registry import TriggerRegistry

logger = get_logger(__name__)


class BrokerTriggerConsumer:
    """
    Consumes messages from a broker and triggers matching sagas.

    Works with any Sagaz-compatible broker (Kafka, RabbitMQ, Redis, Memory).

    Example:
        from sagaz.outbox.brokers.kafka import KafkaBroker

        broker = KafkaBroker(bootstrap_servers="localhost:9092")
        consumer = BrokerTriggerConsumer(broker=broker)

        await consumer.start()  # Start consuming
        await consumer.stop()   # Stop when done
    """

    def __init__(self, broker: Any):
        """
        Initialize the consumer.

        Args:
            broker: A Sagaz broker instance (KafkaBroker, RabbitMQBroker, etc.)
        """
        self._broker = broker
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        """Check if consumer is running."""
        return self._running

    async def start(self, topics: list[str] | None = None) -> None:
        """
        Start consuming messages.

        Args:
            topics: List of topics to consume. If None, discovers from triggers.
        """
        if self._running:
            return

        # Discover topics from registered triggers
        if topics is None:
            topics = self._discover_topics()

        if not topics:
            logger.warning("No topics to consume - no broker triggers registered")
            return

        self._running = True
        logger.info(f"Broker trigger consumer starting for topics: {topics}")

        # Note: Actual consumption depends on broker implementation
        # This is a simplified version that relies on handle_message being called

    async def stop(self) -> None:
        """Stop consuming messages."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Broker trigger consumer stopped")

    def _discover_topics(self) -> list[str]:
        """Discover topics from registered broker triggers."""
        topics = set()

        for trigger in TriggerRegistry.get_triggers("broker"):
            topic = trigger.metadata.config.get("topic")
            if topic:
                topics.add(topic)

        return list(topics)

    async def handle_message(self, topic: str, message: dict) -> list[str]:
        """
        Handle an incoming message from the broker.

        This method should be called when a message is received.
        It finds matching triggers and fires events.

        Args:
            topic: The topic the message was received on
            message: The message payload (dict)

        Returns:
            List of triggered saga IDs
        """
        import asyncio
        import uuid

        triggered_ids = []

        # Find triggers that match this topic
        for trigger in TriggerRegistry.get_triggers("broker"):
            trigger_topic = trigger.metadata.config.get("topic")

            if trigger_topic == topic:
                logger.debug(
                    f"Broker message matched: {trigger.saga_class.__name__}.{trigger.method_name}"
                )

                # Prepare event data
                event_data = {
                    "topic": topic,
                    **message
                }

                # Run transformer
                saga_instance = trigger.saga_class()
                transformer = getattr(saga_instance, trigger.method_name)

                if asyncio.iscoroutinefunction(transformer):
                    context = await transformer(event_data)
                else:
                    context = transformer(event_data)

                if context is None or not isinstance(context, dict):
                    continue

                # Generate saga ID
                saga_id = str(uuid.uuid4())

                # Create and run saga
                execution_saga = trigger.saga_class()
                loop = asyncio.get_running_loop()
                loop.create_task(execution_saga.run(context, saga_id=saga_id))

                triggered_ids.append(saga_id)

        return triggered_ids


async def create_broker_consumer(broker_type: str, **config) -> BrokerTriggerConsumer:
    """
    Factory function to create a broker consumer.

    Args:
        broker_type: Type of broker ("kafka", "rabbitmq", "redis", "memory")
        **config: Broker-specific configuration

    Returns:
        Configured BrokerTriggerConsumer

    Example:
        consumer = await create_broker_consumer(
            "kafka",
            bootstrap_servers="localhost:9092"
        )
    """
    from sagaz.outbox.brokers.factory import create_broker

    broker = create_broker(broker_type, **config)
    await broker.connect()

    return BrokerTriggerConsumer(broker=broker)
