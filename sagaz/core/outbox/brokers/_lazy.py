"""Lazy constructors for optional broker backends.

Each wrapper defers importing its backend module (and therefore its optional
third-party dependency) until a broker is actually instantiated.
"""


def KafkaBroker(*args, **kwargs):
    """Kafka message broker (requires aiokafka)."""
    from sagaz.core.outbox.brokers.kafka import KafkaBroker as _Impl

    return _Impl(*args, **kwargs)


def RabbitMQBroker(*args, **kwargs):
    """RabbitMQ message broker (requires aio-pika)."""
    from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker as _Impl

    return _Impl(*args, **kwargs)


def RedisBroker(*args, **kwargs):
    """Redis Streams message broker (requires redis)."""
    from sagaz.core.outbox.brokers.redis import RedisBroker as _Impl

    return _Impl(*args, **kwargs)
