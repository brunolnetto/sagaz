"""
Unit tests for RabbitMQEventBus.

aio-pika is fully mocked — no real RabbitMQ broker required.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.choreography.buses.rabbitmq import (
    RabbitMQEventBus,
    RabbitMQEventBusConfig,
)
from sagaz.choreography.events import AbstractEventBus, Event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> RabbitMQEventBusConfig:
    return RabbitMQEventBusConfig(
        url="amqp://guest:guest@localhost/",
        exchange_name="test.exchange",
        queue_name="test.queue",
    )


def _make_bus(config: RabbitMQEventBusConfig | None = None) -> RabbitMQEventBus:
    return RabbitMQEventBus(config or _make_config())


def _make_event(
    event_type: str = "order.created", saga_id: str | None = "s-1"
) -> Event:
    return Event(event_type=event_type, data={"order_id": "ORD-1"}, saga_id=saga_id)


def _build_amqp_message(event: Event) -> MagicMock:
    """Build a mock aio-pika message with the event as JSON body."""
    payload = json.dumps(
        {
            "event_type": event.event_type,
            "data": event.data,
            "event_id": event.event_id,
            "saga_id": event.saga_id,
            "created_at": event.created_at.isoformat(),
        }
    ).encode()
    msg = MagicMock()
    msg.body = payload
    # Simulate `async with message.process():` context manager
    msg.process.return_value.__aenter__ = AsyncMock(return_value=None)
    msg.process.return_value.__aexit__ = AsyncMock(return_value=None)
    return msg


# ---------------------------------------------------------------------------
# Missing dependency guard
# ---------------------------------------------------------------------------


def test_missing_aio_pika_raises() -> None:
    with patch("sagaz.choreography.buses.rabbitmq._RABBITMQ_AVAILABLE", False):
        from sagaz.core.exceptions import MissingDependencyError

        with pytest.raises(MissingDependencyError, match="aio-pika"):
            RabbitMQEventBus()


# ---------------------------------------------------------------------------
# ABC conformance
# ---------------------------------------------------------------------------


def test_rabbitmq_bus_is_abstract_eventbus() -> None:
    bus = _make_bus()
    assert isinstance(bus, AbstractEventBus)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_from_env_defaults() -> None:
    config = RabbitMQEventBusConfig.from_env()
    assert config.url == "amqp://guest:guest@localhost/"
    assert config.exchange_name == "sagaz.choreography"
    assert config.queue_name == "sagaz.choreography.queue"
    assert config.prefetch_count == 100
    assert config.heartbeat == 60


def test_from_env_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGAZ_BUS_RABBITMQ_URL", "amqp://user:pass@myhost/myvhost")
    monkeypatch.setenv("SAGAZ_BUS_RABBITMQ_EXCHANGE", "my.exchange")
    monkeypatch.setenv("SAGAZ_BUS_RABBITMQ_QUEUE", "my.queue")
    monkeypatch.setenv("SAGAZ_BUS_RABBITMQ_PREFETCH", "50")
    monkeypatch.setenv("SAGAZ_BUS_RABBITMQ_HEARTBEAT", "30")

    config = RabbitMQEventBusConfig.from_env()
    assert config.url == "amqp://user:pass@myhost/myvhost"
    assert config.exchange_name == "my.exchange"
    assert config.queue_name == "my.queue"
    assert config.prefetch_count == 50
    assert config.heartbeat == 30


# ---------------------------------------------------------------------------
# Subscribe / unsubscribe
# ---------------------------------------------------------------------------


def test_subscribe_registers_handler() -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("order.created", handler)
    assert bus.handler_count("order.created") == 1


def test_unsubscribe_removes_handler() -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("order.created", handler)
    bus.unsubscribe("order.created", handler)
    assert bus.handler_count("order.created") == 0


def test_unsubscribe_nonexistent_is_silent() -> None:
    bus = _make_bus()
    bus.unsubscribe("order.created", AsyncMock())


def test_wildcard_and_specific_handler_counts() -> None:
    bus = _make_bus()
    bus.subscribe("*", AsyncMock())
    bus.subscribe("order.created", AsyncMock())
    assert bus.handler_count("*") == 1
    assert bus.handler_count("order.created") == 1


# ---------------------------------------------------------------------------
# Message dispatch (internal)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_message_calls_exact_handler() -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("order.created", handler)

    await bus._on_message(_build_amqp_message(_make_event("order.created")))

    handler.assert_awaited_once()
    dispatched: Event = handler.call_args.args[0]
    assert dispatched.event_type == "order.created"
    assert dispatched.saga_id == "s-1"


@pytest.mark.asyncio
async def test_on_message_calls_wildcard_handler() -> None:
    bus = _make_bus()
    wildcard = AsyncMock()
    bus.subscribe("*", wildcard)

    await bus._on_message(_build_amqp_message(_make_event("payment.initiated")))
    wildcard.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "subscribed_to", "should_call"),
    [
        ("order.created", "order.created", True),
        ("order.created", "payment.initiated", False),
        ("order.created", "*", True),
    ],
)
async def test_on_message_routing(
    event_type: str, subscribed_to: str, should_call: bool
) -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe(subscribed_to, handler)

    await bus._on_message(_build_amqp_message(_make_event(event_type)))

    if should_call:
        handler.assert_awaited_once()
    else:
        handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_handler_error_does_not_propagate() -> None:
    bus = _make_bus()
    bad = AsyncMock(side_effect=ValueError("boom"))
    good = AsyncMock()
    bus.subscribe("order.created", bad)
    bus.subscribe("order.created", good)

    await bus._on_message(_build_amqp_message(_make_event()))

    good.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_message_null_saga_id() -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("order.created", handler)

    await bus._on_message(_build_amqp_message(_make_event(saga_id=None)))

    dispatched: Event = handler.call_args.args[0]
    assert dispatched.saga_id is None


@pytest.mark.asyncio
async def test_on_message_malformed_body_is_skipped() -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("*", handler)

    bad_msg = MagicMock()
    bad_msg.body = b"not-json"
    bad_msg.process.return_value.__aenter__ = AsyncMock(return_value=None)
    bad_msg.process.return_value.__aexit__ = AsyncMock(return_value=None)

    await bus._on_message(bad_msg)
    handler.assert_not_awaited()


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_without_start_raises() -> None:
    bus = _make_bus()
    with pytest.raises(RuntimeError, match="start()"):
        await bus.publish(_make_event())


@pytest.mark.asyncio
async def test_publish_calls_exchange_publish_with_routing_key() -> None:
    bus = _make_bus()
    mock_exchange = AsyncMock()
    bus._exchange = mock_exchange

    event = _make_event("order.created")
    await bus.publish(event)

    mock_exchange.publish.assert_awaited_once()
    _, kwargs = mock_exchange.publish.call_args
    assert kwargs["routing_key"] == "order.created"


@pytest.mark.asyncio
async def test_publish_records_history() -> None:
    bus = _make_bus()
    bus._exchange = AsyncMock()
    event = _make_event()
    await bus.publish(event)
    assert event in bus.published


@pytest.mark.asyncio
async def test_clear_history() -> None:
    bus = _make_bus()
    bus._exchange = AsyncMock()
    await bus.publish(_make_event())
    bus.clear_history()
    assert bus.published == []


# ---------------------------------------------------------------------------
# Start / stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_declares_exchange_and_queue_and_binds() -> None:
    bus = _make_bus()
    mock_connection = AsyncMock()
    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_queue = AsyncMock()
    mock_queue.consume = AsyncMock(return_value="consumer-tag-1")

    mock_connection.channel = AsyncMock(return_value=mock_channel)
    mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    with patch(
        "sagaz.choreography.buses.rabbitmq.aio_pika.connect_robust",
        return_value=mock_connection,
    ):
        await bus.start()

    mock_channel.declare_exchange.assert_awaited_once()
    mock_channel.declare_queue.assert_awaited_once()
    mock_queue.bind.assert_awaited_once()
    mock_queue.consume.assert_awaited_once()
    assert bus._consumer_tag == "consumer-tag-1"


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    """A second call to start() when already connected should be a no-op."""
    bus = _make_bus()
    mock_connection = AsyncMock()
    mock_channel = AsyncMock()
    mock_queue = AsyncMock()
    mock_queue.consume = AsyncMock(return_value="tag")

    mock_connection.channel = AsyncMock(return_value=mock_channel)
    mock_channel.declare_exchange = AsyncMock(return_value=AsyncMock())
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    with patch(
        "sagaz.choreography.buses.rabbitmq.aio_pika.connect_robust",
        return_value=mock_connection,
    ) as mock_connect:
        await bus.start()
        await bus.start()  # second call should be no-op

    assert mock_connect.call_count == 1


@pytest.mark.asyncio
async def test_stop_cancels_consumer_and_closes_connection() -> None:
    bus = _make_bus()
    mock_connection = AsyncMock()
    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_queue = AsyncMock()
    mock_queue.consume = AsyncMock(return_value="consumer-tag-1")

    mock_connection.channel = AsyncMock(return_value=mock_channel)
    mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    with patch(
        "sagaz.choreography.buses.rabbitmq.aio_pika.connect_robust",
        return_value=mock_connection,
    ):
        await bus.start()
        await bus.stop()

    mock_queue.cancel.assert_awaited_once_with("consumer-tag-1")
    mock_channel.close.assert_awaited_once()
    mock_connection.close.assert_awaited_once()
    assert bus._connection is None
    assert bus._channel is None


@pytest.mark.asyncio
async def test_stop_when_not_started_is_safe() -> None:
    bus = _make_bus()
    await bus.stop()  # Should not raise
