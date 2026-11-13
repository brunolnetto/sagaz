"""SSE smoke test for the visualization monitor (issue #113).

Connects an ``httpx.AsyncClient`` to the live stream of a real Uvicorn server,
emits one saga event and asserts the stream delivers it.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from sagaz.visualization.server import create_app
from tests.unit.test_visualization_run_api import live_server

TOKEN = "sse-smoke-token-0123456789abcdef"


def _event(event_type: str, saga_id: str) -> dict[str, object]:
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "saga_id": saga_id,
        "saga_name": "SmokeSaga",
        "occurred_at": datetime.now(UTC).isoformat(),
    }


async def _next_data(lines) -> dict[str, object]:
    while True:
        line = await asyncio.wait_for(anext(lines), timeout=5.0)
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))


@pytest.mark.parametrize("stream_path", ["/api/v1/live", "/api/sagas/smoke-1/events"])
async def test_stream_receives_an_emitted_saga_event(stream_path):
    app = create_app(event_token=TOKEN)
    async with live_server(app) as base_url, httpx.AsyncClient(timeout=10.0) as client:
        async with client.stream("GET", f"{base_url}{stream_path}") as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            lines = stream.aiter_lines()

            emitted = _event("saga.started", "smoke-1")
            response = await client.post(
                f"{base_url}/api/v1/events",
                json=emitted,
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            assert response.status_code == 202

            received = await _next_data(lines)

    assert received["event_id"] == emitted["event_id"]
    assert received["event_type"] == "saga.started"
    assert received["saga_id"] == "smoke-1"
