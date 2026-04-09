"""
Unit tests for KafkaEventBus.

aiokafka is fully mocked — no real Kafka broker required.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.choreography.buses.kafka import (
    KafkaEventBus,
    KafkaEventBusConfig,
    _event_to_value,
    _value_to_event,
)
from sagaz.choreography.events import AbstractEventBus, Event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> KafkaEventBusConfig:
    return KafkaEventBusConfig(
        bootstrap_servers="localhost:9092",
        topic="test.topic",
        consumer_group="test-group",
        consumer_name="test-worker",
    )


def _make_bus(config: KafkaEventBusConfig | None = None) -> KafkaEventBus:
    return KafkaEventBus(config or _make_config())


def _make_event(
    event_type: str = "order.created", saga_id: str | None = "s-1"
) -> Event:
    return Event(event_type=event_type, data={"order_id": "ORD-1"}, saga_id=saga_id)


def _serialise(event: Event) -> bytes:
    return _event_to_value(event)


# ---------------------------------------------------------------------------
# Missing dependency guard
# ---------------------------------------------------------------------------


def test_missing_aiokafka_raises() -> None:
    with patch("sagaz.choreography.buses.kafka._KAFKA_AVAILABLE", False):
        from sagaz.core.exceptions import MissingDependencyError

        with pytest.raises(MissingDependencyError, match="aiokafka"):
            KafkaEventBus()


# ---------------------------------------------------------------------------
# ABC conformance
# ---------------------------------------------------------------------------


def test_kafka_bus_is_abstract_eventbus() -> None:
    bus = _make_bus()
    assert isinstance(bus, AbstractEventBus)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    config = KafkaEventBusConfig.from_env()
    assert config.bootstrap_servers == "localhost:9092"
    assert config.topic == "sagaz.choreography"
    assert config.consumer_group == "sagaz"
    assert config.consumer_name == "worker-1"


def test_from_env_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGAZ_BUS_KAFKA_BOOTSTRAP_SERVERS", "broker:9093")
    monkeypatch.setenv("SAGAZ_BUS_KAFKA_TOPIC", "my.topic")
    monkeypatch.setenv("SAGAZ_BUS_KAFKA_CONSUMER_GROUP", "my-group")
    monkeypatch.setenv("SAGAZ_BUS_KAFKA_CONSUMER_NAME", "worker-99")
    monkeypatch.setenv("SAGAZ_BUS_KAFKA_SASL_MECHANISM", "PLAIN")

    config = KafkaEventBusConfig.from_env()
    assert config.bootstrap_servers == "broker:9093"
    assert config.topic == "my.topic"
    assert config.consumer_group == "my-group"
    assert config.consumer_name == "worker-99"
    assert config.sasl_mechanism == "PLAIN"


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------


def test_event_serialise_deserialise_round_trip() -> None:
    original = _make_event()
    recovered = _value_to_event(_event_to_value(original))
    assert recovered.event_type == original.event_type
    assert recovered.data == original.data
    assert recovered.event_id == original.event_id
    assert recovered.saga_id == original.saga_id


def test_event_serialise_null_saga_id() -> None:
    event = _make_event(saga_id=None)
    recovered = _value_to_event(_event_to_value(event))
    assert recovered.saga_id is None


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
# Dispatch (internal)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_calls_exact_handler() -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("order.created", handler)

    await bus._dispatch(_serialise(_make_event("order.created")))

    handler.assert_awaited_once()
    dispatched: Event = handler.call_args.args[0]
    assert dispatched.event_type == "order.created"
    assert dispatched.saga_id == "s-1"


@pytest.mark.asyncio
async def test_dispatch_calls_wildcard_handler() -> None:
    bus = _make_bus()
    wildcard = AsyncMock()
    bus.subscribe("*", wildcard)

    await bus._dispatch(_serialise(_make_event("payment.initiated")))
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
async def test_dispatch_routing(
    event_type: str, subscribed_to: str, should_call: bool
) -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe(subscribed_to, handler)

    await bus._dispatch(_serialise(_make_event(event_type)))

    if should_call:
        handler.assert_awaited_once()
    else:
        handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_handler_error_does_not_propagate() -> None:
    bus = _make_bus()
    bad = AsyncMock(side_effect=ValueError("boom"))
    good = AsyncMock()
    bus.subscribe("order.created", bad)
    bus.subscribe("order.created", good)

    await bus._dispatch(_serialise(_make_event()))

    good.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_malformed_value_is_skipped() -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("*", handler)

    await bus._dispatch(b"not-json")
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
async def test_publish_calls_send_and_wait_with_correct_topic_and_key() -> None:
    bus = _make_bus()
    mock_producer = AsyncMock()
    bus._producer = mock_producer

    event = _make_event("order.created")
    await bus.publish(event)

    mock_producer.send_and_wait.assert_awaited_once()
    _, kwargs = mock_producer.send_and_wait.call_args
    # First positional arg is the topic
    topic = mock_producer.send_and_wait.call_args.args[0]
    assert topic == "test.topic"
    assert kwargs["key"] == b"order.created"
    payload = json.loads(kwargs["value"].decode())
    assert payload["event_type"] == "order.created"
    assert payload["data"]["order_id"] == "ORD-1"


@pytest.mark.asyncio
async def test_publish_records_history() -> None:
    bus = _make_bus()
    bus._producer = AsyncMock()
    event = _make_event()
    await bus.publish(event)
    assert event in bus.published


@pytest.mark.asyncio
async def test_clear_history() -> None:
    bus = _make_bus()
    bus._producer = AsyncMock()
    await bus.publish(_make_event())
    bus.clear_history()
    assert bus.published == []


# ---------------------------------------------------------------------------
# Start / stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_producer_consumer_and_reader_task() -> None:
    bus = _make_bus()
    mock_producer = AsyncMock()
    mock_consumer = AsyncMock()
    # getmany must block briefly to avoid tight loop during test
    mock_consumer.getmany = AsyncMock(return_value={})

    with (
        patch(
            "sagaz.choreography.buses.kafka.AIOKafkaProducer",
            return_value=mock_producer,
        ),
        patch(
            "sagaz.choreography.buses.kafka.AIOKafkaConsumer",
            return_value=mock_consumer,
        ),
    ):
        await bus.start()

    assert bus._reader_task is not None
    assert not bus._reader_task.done()
    bus._reader_task.cancel()
    try:
        await bus._reader_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    """Calling start() twice should not create a second reader task."""
    bus = _make_bus()
    mock_producer = AsyncMock()
    mock_consumer = AsyncMock()
    mock_consumer.getmany = AsyncMock(return_value={})

    with (
        patch(
            "sagaz.choreography.buses.kafka.AIOKafkaProducer",
            return_value=mock_producer,
        ),
        patch(
            "sagaz.choreography.buses.kafka.AIOKafkaConsumer",
            return_value=mock_consumer,
        ),
    ):
        await bus.start()
        first_task = bus._reader_task
        await bus.start()  # second call is a no-op

    assert bus._reader_task is first_task
    first_task.cancel()
    try:
        await first_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_stop_closes_producer_and_consumer() -> None:
    bus = _make_bus()
    mock_producer = AsyncMock()
    mock_consumer = AsyncMock()
    mock_consumer.getmany = AsyncMock(return_value={})

    with (
        patch(
            "sagaz.choreography.buses.kafka.AIOKafkaProducer",
            return_value=mock_producer,
        ),
        patch(
            "sagaz.choreography.buses.kafka.AIOKafkaConsumer",
            return_value=mock_consumer,
        ),
    ):
        await bus.start()
        await bus.stop()

    mock_producer.stop.assert_awaited_once()
    mock_consumer.stop.assert_awaited_once()
    assert bus._producer is None
    assert bus._consumer is None


@pytest.mark.asyncio
async def test_stop_when_not_started_is_safe() -> None:
    bus = _make_bus()
    await bus.stop()  # Should not raise


# ---------------------------------------------------------------------------
# Import-error fallback (module-level except ImportError branch)
# ---------------------------------------------------------------------------


def test_kafka_import_error_sets_unavailable_flag() -> None:
    """When aiokafka cannot be imported the module falls back gracefully."""
    import importlib
    import sys

    import sagaz.choreography.buses.kafka as kmod

    saved = sys.modules.pop("aiokafka", None)
    sys.modules["aiokafka"] = None  # type: ignore[assignment]
    try:
        importlib.reload(kmod)
        assert not kmod._KAFKA_AVAILABLE
        assert kmod.AIOKafkaProducer is None
        assert kmod.AIOKafkaConsumer is None
    finally:
        if saved is not None:
            sys.modules["aiokafka"] = saved
        else:
            sys.modules.pop("aiokafka", None)
        importlib.reload(kmod)  # Restore module to working state


# ---------------------------------------------------------------------------
# SASL configuration branch in start()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_with_sasl_mechanism_passes_sasl_options() -> None:
    """start() must include SASL kwargs when sasl_mechanism is configured."""
    config = KafkaEventBusConfig(
        bootstrap_servers="broker:9093",
        topic="test.topic",
        consumer_group="grp",
        consumer_name="w1",
        sasl_mechanism="PLAIN",
        sasl_username="user",
        sasl_password="pass",
        security_protocol="SASL_PLAINTEXT",
    )
    bus = _make_bus(config)
    mock_producer = AsyncMock()
    mock_consumer = AsyncMock()
    mock_consumer.getmany = AsyncMock(side_effect=asyncio.CancelledError())

    with (
        patch(
            "sagaz.choreography.buses.kafka.AIOKafkaProducer",
            return_value=mock_producer,
        ) as mock_producer_cls,
        patch(
            "sagaz.choreography.buses.kafka.AIOKafkaConsumer",
            return_value=mock_consumer,
        ) as mock_consumer_cls,
    ):
        await bus.start()
        task = bus._reader_task
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except (asyncio.CancelledError, TimeoutError):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # Both producer and consumer must have received SASL kwargs
    _, producer_kwargs = mock_producer_cls.call_args
    _, consumer_kwargs = mock_consumer_cls.call_args
    for kwargs in (producer_kwargs, producer_kwargs):
        assert kwargs.get("sasl_mechanism") == "PLAIN" or "sasl_mechanism" in str(
            mock_producer_cls.call_args
        )
    assert "sasl_mechanism" in str(mock_producer_cls.call_args)
    assert "sasl_mechanism" in str(mock_consumer_cls.call_args)


# ---------------------------------------------------------------------------
# _reader_loop coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reader_loop_cancelled_error_exits_cleanly() -> None:
    """CancelledError from getmany causes reader loop to exit via break."""
    bus = _make_bus()
    bus._consumer = AsyncMock()
    bus._consumer.getmany = AsyncMock(side_effect=asyncio.CancelledError())

    # Task should complete normally (loop breaks on CancelledError)
    await asyncio.wait_for(bus._reader_loop(), timeout=2.0)


@pytest.mark.asyncio
async def test_reader_loop_dispatches_messages() -> None:
    """Reader loop commits each message after successful dispatch."""
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("order.created", handler)

    event = _make_event("order.created")
    serialised = _serialise(event)

    call_count = 0
    tp = MagicMock()
    msg = MagicMock()
    msg.value = serialised
    msg.offset = 0

    async def fake_getmany(**kwargs: object) -> dict:  # type: ignore[type-arg]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {tp: [msg]}
        raise asyncio.CancelledError

    bus._consumer = AsyncMock()
    bus._consumer.getmany = fake_getmany

    await asyncio.wait_for(bus._reader_loop(), timeout=2.0)

    handler.assert_awaited()
    bus._consumer.commit.assert_awaited()


@pytest.mark.asyncio
async def test_reader_loop_exception_is_logged_and_loop_retries() -> None:
    """Non-CancelledError exceptions are caught, logged, and the loop retries."""
    bus = _make_bus()
    bus._consumer = AsyncMock()

    call_count = 0

    async def fake_getmany(**kwargs: object) -> dict:  # type: ignore[type-arg]
        nonlocal call_count
        call_count += 1
        msg = "broker gone"
        if call_count == 1:
            raise RuntimeError(msg)
        raise asyncio.CancelledError

    bus._consumer.getmany = fake_getmany

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await asyncio.wait_for(bus._reader_loop(), timeout=2.0)

    assert call_count == 2
