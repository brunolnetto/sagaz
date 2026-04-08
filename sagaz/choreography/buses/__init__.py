"""
sagaz.choreography.buses — EventBus transport backends.

Two implementations are provided:

``EventBus``
    In-process asyncio pub/sub.  Zero dependencies; ideal for single-process
    sagas, unit tests, and local development.  Imported from
    ``sagaz.choreography.events``.

``RedisStreamsEventBus``
    Distributed pub/sub backed by Redis Streams (XADD / XREADGROUP).  Requires
    only the ``redis`` optional extra — no Kafka or RabbitMQ needed.  Suitable
    for multi-process / multi-service choreography.

Example::

    from sagaz.choreography.buses import RedisStreamsEventBus, RedisStreamsBusConfig

    config = RedisStreamsBusConfig(
        url="redis://localhost:6379/0",
        stream_name="sagaz.choreography",
        consumer_group="my-service",
        consumer_name="worker-1",
    )
    bus = RedisStreamsEventBus(config)
    await bus.start()
    try:
        ...
    finally:
        await bus.stop()
"""

from sagaz.choreography.buses.redis_streams import (
    RedisStreamsBusConfig,
    RedisStreamsEventBus,
)

__all__ = ["RedisStreamsBusConfig", "RedisStreamsEventBus"]
