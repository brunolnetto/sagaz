"""
In-Memory Message Broker - For testing and development.
"""

from sagaz.outbox.brokers.base import BaseBroker, BrokerConfig, BrokerConnectionError


class InMemoryBroker(BaseBroker):
    """
    In-memory message broker for testing and development.

    Messages are stored in memory and can be inspected for testing.

    Usage:
        >>> broker = InMemoryBroker()
        >>> await broker.connect()
        >>> await broker.publish("orders", b'{"id": 1}')
        >>>
        >>> # Inspect published messages
        >>> messages = broker.get_messages("orders")
        >>> assert len(messages) == 1
    """

    def __init__(self, config: BrokerConfig | None = None):
        super().__init__(config)
        self._messages: dict[str, list] = {}

    async def connect(self) -> None:
        """Connect (no-op for in-memory)."""
        self._connected = True

    async def publish(
        self,
        topic: str,
        message: bytes,
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        """Publish message to in-memory storage."""
        if not self._connected:
            msg = "Broker not connected"
            raise BrokerConnectionError(msg)

        if topic not in self._messages:
            self._messages[topic] = []

        self._messages[topic].append(
            {
                "message": message,
                "headers": headers or {},
                "key": key,
            }
        )

    async def close(self) -> None:
        """Close connection."""
        self._connected = False

    async def health_check(self) -> bool:
        """Check health (always healthy for in-memory)."""
        return self._connected

    def get_messages(self, topic: str) -> list:
        """Get all messages for a topic (for testing)."""
        return self._messages.get(topic, [])

    def clear(self) -> None:
        """Clear all messages (for testing)."""
        self._messages.clear()
