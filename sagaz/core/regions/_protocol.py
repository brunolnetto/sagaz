"""Messages between coordinators and regional workers, and buses from URLs."""

from __future__ import annotations

from typing import Any

from sagaz.choreography.events import AbstractEventBus

#: A coordinator asks a region to run a step (or its compensation).
REQUEST = "sagaz.region.request"
#: Prefix of the reply type; the coordinator's id completes it.
REPLY_PREFIX = "sagaz.region.reply."
#: Workers announce that their region is up.
HEARTBEAT = "sagaz.region.heartbeat"
#: A manual failover (or its end), published by ``sagaz region failover``.
FAILOVER = "sagaz.region.failover"

ACTION, COMPENSATION = "action", "compensation"

#: Topic / stream every region bus uses.
TOPIC = "sagaz.regions"


class RemoteStepError(RuntimeError):
    """A step (or compensation) raised on a regional worker."""

    def __init__(self, region: str, error_type: str, message: str) -> None:
        super().__init__(f"{error_type} in region {region}: {message}")
        self.region, self.error_type, self.remote_message = region, error_type, message


def bus_from_url(url: str, group: str, member: str) -> AbstractEventBus:
    """An event bus for *url*, consuming as *member* of consumer group *group*.

    ``redis://...`` (Redis Streams), ``kafka://host:port[,host:port]``,
    ``amqp://...`` (RabbitMQ) or ``memory://`` (in-process, for tests).
    """
    config: Any
    if url.startswith("memory://"):
        from sagaz.choreography.events import EventBus

        return EventBus()
    if url.startswith(("redis://", "rediss://")):
        from sagaz.choreography.buses.redis_streams import (
            RedisStreamsBusConfig,
            RedisStreamsEventBus,
        )

        config = RedisStreamsBusConfig(
            url=url,
            stream_name=TOPIC,
            consumer_group=group,
            consumer_name=member,
            block_timeout_ms=200,
        )
        return RedisStreamsEventBus(config)
    if url.startswith("kafka://"):
        from sagaz.choreography.buses.kafka import KafkaEventBus, KafkaEventBusConfig

        config = KafkaEventBusConfig(
            bootstrap_servers=url[len("kafka://") :],
            topic=TOPIC,
            consumer_group=group,
            consumer_name=member,
        )
        return KafkaEventBus(config)
    if url.startswith(("amqp://", "amqps://")):
        from sagaz.choreography.buses.rabbitmq import RabbitMQEventBus, RabbitMQEventBusConfig

        config = RabbitMQEventBusConfig(url=url, exchange_name=TOPIC, queue_name=f"{TOPIC}.{group}")
        return RabbitMQEventBus(config)
    msg = f"Unsupported region bus URL {url!r}: use redis://, kafka://, amqp:// or memory://"
    raise ValueError(msg)
