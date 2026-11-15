"""The Debezium connector config and its Kafka Connect registration (ADR-011, #50)."""

from __future__ import annotations

import json

import httpx
import pytest

from sagaz.integrations.cdc import CDCError
from sagaz.integrations.cdc.debezium import DEFAULT_TOPIC_PREFIX
from sagaz.integrations.cdc.debezium_connect import (
    CONNECTOR_NAME,
    connector_status,
    is_running,
    outbox_connector_config,
    register_connector,
)

CONNECT = "http://connect:8083/"


class TestOutboxConnectorConfig:
    def test_shipped_config(self):
        config = outbox_connector_config()
        assert config["connector.class"] == "io.debezium.connector.postgresql.PostgresConnector"
        assert config["plugin.name"] == "pgoutput"
        assert config["table.include.list"] == "public.saga_outbox"
        assert config["publication.autocreate.mode"] == "filtered"
        assert config["topic.prefix"] == DEFAULT_TOPIC_PREFIX
        assert config["value.converter.schemas.enable"] == "false"
        assert config["key.converter.schemas.enable"] == "false"
        assert int(config["heartbeat.interval.ms"]) > 0
        assert config["slot.name"]
        assert all(isinstance(value, str) for value in config.values())

    def test_overrides(self):
        config = outbox_connector_config(
            {
                "database.hostname": "db",
                "database.port": 6543,
                "slot.drop.on.stop": True,
                "provide.transaction.metadata": False,
                "heartbeat.interval.ms": None,
            }
        )
        assert config["database.hostname"] == "db"
        assert config["database.port"] == "6543"
        assert config["slot.drop.on.stop"] == "true"
        assert config["provide.transaction.metadata"] == "false"
        assert "heartbeat.interval.ms" not in config

    def test_returns_a_fresh_copy(self):
        outbox_connector_config()["topic.prefix"] = "changed"
        assert outbox_connector_config()["topic.prefix"] == DEFAULT_TOPIC_PREFIX


def transport(handler):
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.MockTransport(record), requests


@pytest.mark.asyncio
class TestRegisterConnector:
    async def test_puts_the_shipped_config(self):
        mock, requests = transport(
            lambda request: httpx.Response(
                201, json={"name": CONNECTOR_NAME, "config": json.loads(request.content)}
            )
        )
        result = await register_connector(CONNECT, transport=mock)
        (request,) = requests
        assert request.method == "PUT"
        assert str(request.url) == "http://connect:8083/connectors/sagaz-outbox/config"
        assert json.loads(request.content) == outbox_connector_config()
        assert result["name"] == CONNECTOR_NAME

    async def test_custom_name_and_config(self):
        mock, requests = transport(lambda request: httpx.Response(200, json={"name": "x"}))
        await register_connector(CONNECT, {"topic.prefix": "p"}, name="x", transport=mock)
        assert requests[0].url.path == "/connectors/x/config"
        assert json.loads(requests[0].content) == {"topic.prefix": "p"}

    async def test_rejected_config(self):
        mock, _ = transport(
            lambda request: httpx.Response(
                400, json={"message": "Connector configuration is invalid"}
            )
        )
        with pytest.raises(CDCError, match=r"400.*invalid"):
            await register_connector(CONNECT, transport=mock)

    async def test_unreachable(self):
        def refuse(request):
            msg = "connection refused"
            raise httpx.ConnectError(msg, request=request)

        mock, _ = transport(refuse)
        with pytest.raises(CDCError, match="cannot reach"):
            await register_connector(CONNECT, transport=mock)


@pytest.mark.asyncio
class TestConnectorStatus:
    async def test_status(self):
        body = {
            "name": CONNECTOR_NAME,
            "connector": {"state": "RUNNING"},
            "tasks": [{"id": 0, "state": "RUNNING"}],
        }
        mock, requests = transport(lambda request: httpx.Response(200, json=body))
        status = await connector_status(CONNECT, transport=mock)
        assert requests[0].method == "GET"
        assert requests[0].url.path == "/connectors/sagaz-outbox/status"
        assert is_running(status)

    async def test_empty_body(self):
        mock, _ = transport(lambda request: httpx.Response(204))
        assert await connector_status(CONNECT, transport=mock) == {}

    async def test_unknown_connector(self):
        mock, _ = transport(lambda request: httpx.Response(404, text="not found"))
        with pytest.raises(CDCError, match="404"):
            await connector_status(CONNECT, transport=mock)

    async def test_unreachable(self):
        def refuse(request):
            msg = "timed out"
            raise httpx.ReadTimeout(msg, request=request)

        mock, _ = transport(refuse)
        with pytest.raises(CDCError, match="cannot reach"):
            await connector_status(CONNECT, transport=mock)


@pytest.mark.parametrize(
    "status",
    [
        {},
        {"connector": {"state": "RUNNING"}, "tasks": []},
        {"connector": {"state": "RUNNING"}, "tasks": [{"state": "FAILED"}]},
        {"connector": {"state": "PAUSED"}, "tasks": [{"state": "RUNNING"}]},
    ],
)
def test_not_running(status):
    assert not is_running(status)
