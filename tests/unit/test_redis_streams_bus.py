"""
Unit tests for RedisStreamsEventBus.

Redis is fully mocked — no real Redis server required.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.choreography.buses import RedisStreamsBusConfig, RedisStreamsEventBus
from sagaz.choreography.events import Event

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_bus(config: RedisStreamsBusConfig | None = None) -> RedisStreamsEventBus:
    config = config or RedisStreamsBusConfig(
        url="redis://localhost:6379/0",
        stream_name="test.stream",
        consumer_group="test-group",
        consumer_name="test-worker",
    )
    return RedisStreamsEventBus(config)


def _make_event(event_type: str = "order.created", saga_id: str | None = "s-1") -> Event:
    return Event(
        event_type=event_type,
        data={"order_id": "ORD-1"},
        saga_id=saga_id,
    )


def _serialise_event(event: Event) -> dict[bytes, bytes]:
    """Build the bytes-keyed field dict that Redis returns."""
    return {
        b"event_type": event.event_type.encode(),
        b"data": json.dumps(event.data).encode(),
        b"event_id": event.event_id.encode(),
        b"saga_id": (event.saga_id or "").encode(),
        b"created_at": event.created_at.isoformat().encode(),
    }


# ---------------------------------------------------------------------------
# Missing dependency guard
# ---------------------------------------------------------------------------


def test_missing_redis_raises() -> None:
    """Constructor raises MissingDependencyError when redis is not installed."""
    with patch("sagaz.choreography.buses.redis_streams._REDIS_AVAILABLE", False):
        from sagaz.core.exceptions import MissingDependencyError

        with pytest.raises(MissingDependencyError, match="redis"):
            RedisStreamsEventBus()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    config = RedisStreamsBusConfig.from_env()
    assert config.url == "redis://localhost:6379/0"
    assert config.stream_name == "sagaz.choreography"
    assert config.consumer_group == "sagaz"


def test_from_env_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGAZ_BUS_REDIS_URL", "redis://myhost:6380/1")
    monkeypatch.setenv("SAGAZ_BUS_REDIS_STREAM_NAME", "my.stream")
    monkeypatch.setenv("SAGAZ_BUS_REDIS_CONSUMER_GROUP", "my-group")
    monkeypatch.setenv("SAGAZ_BUS_REDIS_CONSUMER_NAME", "worker-42")
    monkeypatch.setenv("SAGAZ_BUS_REDIS_BLOCK_TIMEOUT_MS", "500")

    config = RedisStreamsBusConfig.from_env()
    assert config.url == "redis://myhost:6380/1"
    assert config.stream_name == "my.stream"
    assert config.consumer_group == "my-group"
    assert config.consumer_name == "worker-42"
    assert config.block_timeout_ms == 500


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
    handler = AsyncMock()
    # Should not raise
    bus.unsubscribe("order.created", handler)


def test_wildcard_handler_count() -> None:
    bus = _make_bus()
    h1, h2 = AsyncMock(), AsyncMock()
    bus.subscribe("*", h1)
    bus.subscribe("order.created", h2)
    assert bus.handler_count("*") == 1
    assert bus.handler_count("order.created") == 1


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_calls_xadd() -> None:
    bus = _make_bus()
    mock_client = AsyncMock()
    bus._client = mock_client  # inject mock

    event = _make_event()
    await bus.publish(event)

    mock_client.xadd.assert_awaited_once()
    call_args = mock_client.xadd.call_args
    stream_name, fields = call_args.args
    assert stream_name == "test.stream"
    assert fields["event_type"] == "order.created"
    assert fields["saga_id"] == "s-1"
    assert json.loads(fields["data"])["order_id"] == "ORD-1"


@pytest.mark.asyncio
async def test_publish_without_start_raises() -> None:
    bus = _make_bus()
    with pytest.raises(RuntimeError, match="start()"):
        await bus.publish(_make_event())


@pytest.mark.asyncio
async def test_publish_records_history() -> None:
    bus = _make_bus()
    bus._client = AsyncMock()
    event = _make_event()
    await bus.publish(event)
    assert event in bus.published


@pytest.mark.asyncio
async def test_clear_history() -> None:
    bus = _make_bus()
    bus._client = AsyncMock()
    await bus.publish(_make_event())
    bus.clear_history()
    assert bus.published == []


# ---------------------------------------------------------------------------
# Dispatch (internal — unit test of the deserialise + handler routing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_calls_exact_handler() -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("order.created", handler)

    event = _make_event("order.created")
    fields = _serialise_event(event)
    await bus._dispatch(fields)

    handler.assert_awaited_once()
    dispatched: Event = handler.call_args.args[0]
    assert dispatched.event_type == "order.created"
    assert dispatched.saga_id == "s-1"


@pytest.mark.asyncio
async def test_dispatch_calls_wildcard_handler() -> None:
    bus = _make_bus()
    wildcard = AsyncMock()
    bus.subscribe("*", wildcard)

    await bus._dispatch(_serialise_event(_make_event("payment.initiated")))
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
async def test_dispatch_routing(event_type: str, subscribed_to: str, should_call: bool) -> None:
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe(subscribed_to, handler)

    await bus._dispatch(_serialise_event(_make_event(event_type)))

    if should_call:
        handler.assert_awaited_once()
    else:
        handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_handler_error_does_not_propagate() -> None:
    """A failing handler must not prevent other handlers from running."""
    bus = _make_bus()
    bad_handler = AsyncMock(side_effect=ValueError("boom"))
    good_handler = AsyncMock()
    bus.subscribe("order.created", bad_handler)
    bus.subscribe("order.created", good_handler)

    await bus._dispatch(_serialise_event(_make_event()))

    good_handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_null_saga_id() -> None:
    """Events with no saga_id should deserialise with saga_id=None."""
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("order.created", handler)

    event = _make_event(saga_id=None)
    await bus._dispatch(_serialise_event(event))

    dispatched: Event = handler.call_args.args[0]
    assert dispatched.saga_id is None


@pytest.mark.asyncio
async def test_dispatch_malformed_fields_skipped() -> None:
    """A message with missing required fields should be silently skipped."""
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("*", handler)

    bad_fields: dict[bytes, bytes] = {b"junk": b"value"}
    await bus._dispatch(bad_fields)

    handler.assert_not_awaited()


# ---------------------------------------------------------------------------
# Start / stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_consumer_group_and_reader_task() -> None:
    bus = _make_bus()
    mock_client = AsyncMock()

    with patch(
        "sagaz.choreography.buses.redis_streams.aioredis.from_url",
        return_value=mock_client,
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
async def test_start_handles_busygroup_error() -> None:
    """BUSYGROUP should be silently ignored on second start."""
    bus = _make_bus()
    mock_client = AsyncMock()
    mock_client.xgroup_create.side_effect = Exception("BUSYGROUP Consumer group already exists")

    with patch(
        "sagaz.choreography.buses.redis_streams.aioredis.from_url",
        return_value=mock_client,
    ):
        await bus.start()  # Should not raise

    bus._reader_task.cancel()
    try:
        await bus._reader_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_stop_cancels_reader_and_closes_client() -> None:
    bus = _make_bus()
    mock_client = AsyncMock()

    with patch(
        "sagaz.choreography.buses.redis_streams.aioredis.from_url",
        return_value=mock_client,
    ):
        await bus.start()

    await bus.stop()

    mock_client.aclose.assert_awaited_once()
    assert bus._client is None


@pytest.mark.asyncio
async def test_stop_when_not_started_is_safe() -> None:
    bus = _make_bus()
    await bus.stop()  # Should not raise


# ---------------------------------------------------------------------------
# Import-error fallback (module-level except ImportError branch)
# ---------------------------------------------------------------------------


def test_redis_import_error_sets_unavailable_flag() -> None:
    """When redis cannot be imported the module falls back gracefully."""
    import importlib
    import sys

    import sagaz.choreography.buses.redis_streams as rmod

    saved = sys.modules.pop("redis", None)
    saved_asyncio = sys.modules.pop("redis.asyncio", None)
    sys.modules["redis"] = None  # type: ignore[assignment]
    try:
        importlib.reload(rmod)
        assert not rmod._REDIS_AVAILABLE
        assert rmod.aioredis is None
    finally:
        if saved is not None:
            sys.modules["redis"] = saved
        else:
            sys.modules.pop("redis", None)
        if saved_asyncio is not None:
            sys.modules["redis.asyncio"] = saved_asyncio
        else:
            sys.modules.pop("redis.asyncio", None)
        importlib.reload(rmod)  # Restore module to working state


# ---------------------------------------------------------------------------
# start() idempotency and non-BUSYGROUP error propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    """A second start() while the reader is running must be a no-op."""
    bus = _make_bus()
    mock_client = AsyncMock()

    with patch(
        "sagaz.choreography.buses.redis_streams.aioredis.from_url",
        return_value=mock_client,
    ):
        await bus.start()
        first_task = bus._reader_task
        await bus.start()  # second call must not replace the task

    assert bus._reader_task is first_task
    first_task.cancel()
    try:
        await first_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_start_raises_non_busygroup_xgroup_error() -> None:
    """xgroup_create errors not containing 'BUSYGROUP' must propagate."""
    bus = _make_bus()
    mock_client = AsyncMock()
    mock_client.xgroup_create.side_effect = RuntimeError("unexpected redis error")

    with patch(
        "sagaz.choreography.buses.redis_streams.aioredis.from_url",
        return_value=mock_client,
    ):
        with pytest.raises(RuntimeError, match="unexpected redis error"):
            await bus.start()


# ---------------------------------------------------------------------------
# _reader_loop coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reader_loop_cancelled_error_exits_cleanly() -> None:
    """CancelledError from xreadgroup causes reader loop to exit via break."""
    bus = _make_bus()
    bus._client = AsyncMock()
    bus._client.xreadgroup = AsyncMock(side_effect=asyncio.CancelledError())

    await asyncio.wait_for(bus._reader_loop(), timeout=2.0)


@pytest.mark.asyncio
async def test_reader_loop_empty_results_continues() -> None:
    """Empty xreadgroup results cause the loop to continue without processing."""
    bus = _make_bus()
    bus._client = AsyncMock()

    call_count = 0

    async def fake_xreadgroup(*args: object, **kwargs: object) -> list:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return []  # empty — triggers `if not results: continue`
        raise asyncio.CancelledError

    bus._client.xreadgroup = fake_xreadgroup

    await asyncio.wait_for(bus._reader_loop(), timeout=2.0)
    assert call_count == 2


@pytest.mark.asyncio
async def test_reader_loop_dispatches_messages() -> None:
    """Reader loop acknowledges each message after successful dispatch."""
    bus = _make_bus()
    handler = AsyncMock()
    bus.subscribe("order.created", handler)

    event = _make_event("order.created")
    fields = _serialise_event(event)
    msg_id = b"1-0"

    call_count = 0

    async def fake_xreadgroup(*args: object, **kwargs: object) -> list:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            stream = b"test.stream"
            return [(stream, [(msg_id, fields)])]
        raise asyncio.CancelledError

    bus._client = AsyncMock()
    bus._client.xreadgroup = fake_xreadgroup

    await asyncio.wait_for(bus._reader_loop(), timeout=2.0)

    handler.assert_awaited()
    bus._client.xack.assert_awaited()


@pytest.mark.asyncio
async def test_reader_loop_exception_is_logged_and_loop_retries() -> None:
    """Non-CancelledError exceptions in xreadgroup are caught and retried."""
    bus = _make_bus()
    bus._client = AsyncMock()

    call_count = 0

    async def fake_xreadgroup(*args: object, **kwargs: object) -> list:
        nonlocal call_count
        call_count += 1
        msg = "redis gone"
        if call_count == 1:
            raise RuntimeError(msg)
        raise asyncio.CancelledError

    bus._client.xreadgroup = fake_xreadgroup

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await asyncio.wait_for(bus._reader_loop(), timeout=2.0)

    assert call_count == 2
