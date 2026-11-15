"""Register the outbox's Debezium connector with Kafka Connect (ADR-011, #50).

The connector configuration ships with sagaz under
``sagaz/deployment/resources/local/postgres/debezium/saga-outbox-connector.json``
(pgoutput, ``public.saga_outbox`` only, ``topic.prefix`` ``sagaz``, schemaless
JSON). :func:`outbox_connector_config` loads it with overrides and
:func:`register_connector` creates or updates it through Kafka Connect's REST
API (``PUT /connectors/<name>/config``, idempotent)::

    config = outbox_connector_config({"database.hostname": "db", "database.password": pw})
    await register_connector("http://connect:8083", config)
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from typing import Any

import httpx

from sagaz.integrations.cdc._types import CDCError

#: Default name of the outbox connector in Kafka Connect.
CONNECTOR_NAME = "sagaz-outbox"

#: The shipped connector configuration, relative to the ``sagaz`` package.
CONNECTOR_CONFIG_RESOURCE = (
    "deployment/resources/local/postgres/debezium/saga-outbox-connector.json"
)


def outbox_connector_config(overrides: Mapping[str, Any] | None = None) -> dict[str, str]:
    """The shipped outbox connector config with ``overrides`` applied.

    Kafka Connect expects string values, so overrides are converted with
    ``str`` (booleans become ``"true"``/``"false"``); a ``None`` override
    removes the key.
    """
    text = resources.files("sagaz").joinpath(CONNECTOR_CONFIG_RESOURCE).read_text("utf-8")
    config: dict[str, str] = json.loads(text)
    for key, value in (overrides or {}).items():
        if value is None:
            config.pop(key, None)
        elif isinstance(value, bool):
            config[key] = "true" if value else "false"
        else:
            config[key] = str(value)
    return config


def _client(
    connect_url: str, timeout: float, transport: httpx.AsyncBaseTransport | None
) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=connect_url.rstrip("/"), timeout=timeout, transport=transport)


def _json_or_raise(response: httpx.Response, action: str) -> dict[str, Any]:
    if response.is_success:
        body: dict[str, Any] = response.json() if response.content else {}
        return body
    msg = f"Kafka Connect refused to {action} ({response.status_code}): {response.text}"
    raise CDCError(msg)


async def register_connector(
    connect_url: str,
    config: Mapping[str, str] | None = None,
    *,
    name: str = CONNECTOR_NAME,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Create or update connector ``name`` with ``config`` (the shipped one by default).

    Returns Kafka Connect's description of the connector; raises
    :class:`CDCError` if Connect is unreachable or rejects the configuration.
    """
    body = dict(config) if config is not None else outbox_connector_config()
    try:
        async with _client(connect_url, timeout, transport) as client:
            response = await client.put(f"/connectors/{name}/config", json=body)
    except httpx.HTTPError as exc:
        msg = f"cannot reach Kafka Connect at {connect_url}: {exc}"
        raise CDCError(msg) from exc
    return _json_or_raise(response, f"configure connector {name!r}")


async def connector_status(
    connect_url: str,
    *,
    name: str = CONNECTOR_NAME,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """The connector's state and its tasks' (``GET /connectors/<name>/status``)."""
    try:
        async with _client(connect_url, timeout, transport) as client:
            response = await client.get(f"/connectors/{name}/status")
    except httpx.HTTPError as exc:
        msg = f"cannot reach Kafka Connect at {connect_url}: {exc}"
        raise CDCError(msg) from exc
    return _json_or_raise(response, f"report connector {name!r}")


def is_running(status: Mapping[str, Any]) -> bool:
    """True if a :func:`connector_status` result shows the connector and all tasks running."""
    tasks = status.get("tasks") or []
    return (
        (status.get("connector") or {}).get("state") == "RUNNING"
        and bool(tasks)
        and all(task.get("state") == "RUNNING" for task in tasks)
    )
