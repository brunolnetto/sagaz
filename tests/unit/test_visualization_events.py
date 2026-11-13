from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from sagaz.visualization.events import (
    HTTPEventPublisher,
    VisualizationSagaListener,
)


class RecordingPublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_step_failure_emits_only_safe_metadata():
    publisher = RecordingPublisher()
    listener = VisualizationSagaListener(publisher=publisher)

    await listener.on_step_failure(
        "PaymentSaga",
        "charge",
        {
            "saga_id": "saga-123",
            "access_token": "must-not-leak",
            "customer_email": "private@example.com",
        },
        RuntimeError("sensitive payment response"),
    )

    assert len(publisher.events) == 1
    event = publisher.events[0]

    assert event["event_type"] == "step.failed"
    assert event["saga_id"] == "saga-123"
    assert event["saga_name"] == "PaymentSaga"
    assert event["step_name"] == "charge"
    assert event["error_type"] == "RuntimeError"
    assert "access_token" not in event
    assert "customer_email" not in event
    assert "sensitive payment response" not in str(event)
    assert event["event_id"]
    assert event["occurred_at"]


@pytest.mark.asyncio
async def test_listener_emits_all_lifecycle_event_types():
    publisher = RecordingPublisher()
    listener = VisualizationSagaListener(publisher=publisher)
    ctx = {"saga_id": "saga-456"}

    await listener.on_saga_start("OrderSaga", "saga-456", ctx)
    await listener.on_step_enter("OrderSaga", "reserve", ctx)
    await listener.on_step_success("OrderSaga", "reserve", ctx, {"secret": "hidden"})
    await listener.on_compensation_start("OrderSaga", "reserve", ctx)
    await listener.on_compensation_complete("OrderSaga", "reserve", ctx)
    await listener.on_saga_complete("OrderSaga", "saga-456", ctx)
    await listener.on_saga_failed("OrderSaga", "saga-456", ctx, ValueError("private message"))

    assert [event["event_type"] for event in publisher.events] == [
        "saga.started",
        "step.started",
        "step.succeeded",
        "step.compensation_started",
        "step.compensated",
        "saga.completed",
        "saga.failed",
    ]


@pytest.mark.asyncio
async def test_http_publisher_sends_json_and_bearer_token():
    captured = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data)
        return FakeResponse()

    publisher = HTTPEventPublisher(
        "http://127.0.0.1:7070",
        token="test-token",
        timeout_seconds=0.25,
    )

    event = {"event_type": "saga.started", "saga_id": "saga-789"}

    with patch("sagaz.visualization.events.urlopen", fake_urlopen):
        await publisher.publish(event)

    assert captured["url"] == "http://127.0.0.1:7070/api/v1/events"
    assert captured["authorization"] == "Bearer test-token"
    assert captured["timeout"] == 0.25
    assert captured["body"] == event


def test_http_publisher_rejects_invalid_url():
    with pytest.raises(ValueError, match="HTTP"):
        HTTPEventPublisher("file:///tmp/events")


def test_listener_requires_publisher_or_server_url():
    with pytest.raises(ValueError, match="server_url or publisher"):
        VisualizationSagaListener()


def test_from_env_creates_listener_with_url_and_token(monkeypatch):
    monkeypatch.setenv("SAGAZ_VISUALIZATION_URL", "http://127.0.0.1:7070")
    monkeypatch.setenv("SAGAZ_VISUALIZATION_TOKEN", "test-token-abc")

    listener = VisualizationSagaListener.from_env()

    assert isinstance(listener, VisualizationSagaListener)
    assert isinstance(listener.publisher, HTTPEventPublisher)
    assert listener.publisher.token == "test-token-abc"
    assert listener.publisher.endpoint == "http://127.0.0.1:7070/api/v1/events"


def test_from_env_uses_none_token_when_not_configured(monkeypatch):
    monkeypatch.setenv("SAGAZ_VISUALIZATION_URL", "http://127.0.0.1:7070")
    monkeypatch.delenv("SAGAZ_VISUALIZATION_TOKEN", raising=False)

    listener = VisualizationSagaListener.from_env()

    assert listener.publisher.token is None


def test_from_env_raises_when_url_missing(monkeypatch):
    monkeypatch.delenv("SAGAZ_VISUALIZATION_URL", raising=False)

    with pytest.raises(ValueError, match="SAGAZ_VISUALIZATION_URL"):
        VisualizationSagaListener.from_env()


def test_from_env_passes_timeout_seconds(monkeypatch):
    monkeypatch.setenv("SAGAZ_VISUALIZATION_URL", "http://127.0.0.1:7070")
    monkeypatch.delenv("SAGAZ_VISUALIZATION_TOKEN", raising=False)

    listener = VisualizationSagaListener.from_env(timeout_seconds=2.5)

    assert listener.publisher.timeout_seconds == 2.5


@pytest.mark.parametrize(
    ("url", "kwargs", "match"),
    [
        ("http://127.0.0.1:7070/?x=1", {}, "query or fragment"),
        ("http://127.0.0.1:7070/#frag", {}, "query or fragment"),
        ("http://127.0.0.1:7070", {"timeout_seconds": 0}, "timeout_seconds"),
    ],
)
def test_http_publisher_rejects_invalid_configuration(url, kwargs, match):
    with pytest.raises(ValueError, match=match):
        HTTPEventPublisher(url, **kwargs)


def test_http_publisher_raises_on_non_2xx_and_omits_auth_without_token():
    captured = {}

    class FakeResponse:
        status = 500

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        return FakeResponse()

    publisher = HTTPEventPublisher("http://127.0.0.1:7070")
    with (
        patch("sagaz.visualization.events.urlopen", fake_urlopen),
        pytest.raises(RuntimeError, match="HTTP 500"),
    ):
        publisher._post({"event_type": "saga.started"})

    assert captured["authorization"] is None
