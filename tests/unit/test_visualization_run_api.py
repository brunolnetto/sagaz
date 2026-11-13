"""Tests for the run, metrics and per-saga SSE endpoints of the visualization server."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from sagaz.visualization.server import create_app

TOKEN = "test-visualization-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
T0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)


def ev(event_type, saga_id="s1", saga_name="OrderSaga", step=None, error=None, at_ms=0):
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "saga_id": saga_id,
        "saga_name": saga_name,
        "step_name": step,
        "error_type": error,
        "occurred_at": (T0 + timedelta(milliseconds=at_ms)).isoformat(),
    }


@pytest.fixture
def client():
    with TestClient(create_app(event_token=TOKEN)) as test_client:
        yield test_client


def post(client, event):
    response = client.post("/api/v1/events", json=event, headers=AUTH)
    assert response.status_code == 202, response.text
    return response.json()


def seed(client):
    post(client, ev("saga.started", "ok-1"))
    post(client, ev("step.started", "ok-1", step="charge", at_ms=1))
    post(client, ev("step.succeeded", "ok-1", step="charge", at_ms=6))
    post(client, ev("saga.completed", "ok-1", at_ms=8))

    post(client, ev("saga.started", "bad-1"))
    post(client, ev("step.started", "bad-1", step="reserve", at_ms=1))
    post(client, ev("step.succeeded", "bad-1", step="reserve", at_ms=2))
    post(client, ev("step.started", "bad-1", step="charge", at_ms=3))
    post(client, ev("step.failed", "bad-1", step="charge", error="Declined", at_ms=4))
    post(client, ev("step.compensation_started", "bad-1", step="reserve", at_ms=5))
    post(client, ev("step.compensated", "bad-1", step="reserve", at_ms=6))
    post(client, ev("saga.failed", "bad-1", error="Declined", at_ms=7))

    post(client, ev("saga.started", "refund-1", saga_name="RefundSaga"))


class TestDashboardPage:
    def test_dashboard_has_all_views(self, client):
        html = client.get("/").text
        for view in ("dashboard", "runs", "detail", "live", "steps"):
            assert f'id="view-{view}"' in html
        assert "/api/v1/metrics/summary" in html
        assert "securityLevel" in html


class TestRunsEndpoint:
    def test_lists_runs_newest_first(self, client):
        seed(client)
        data = client.get("/api/v1/runs").json()
        assert data["total"] == 3
        assert [r["saga_id"] for r in data["items"]] == ["refund-1", "bad-1", "ok-1"]
        assert data["limit"] == 50
        assert data["offset"] == 0

    def test_status_and_saga_filters(self, client):
        seed(client)
        failed = client.get("/api/v1/runs", params={"status": "failed"}).json()
        assert [r["saga_id"] for r in failed["items"]] == ["bad-1"]

        refunds = client.get("/api/v1/runs", params={"saga_name": "RefundSaga"}).json()
        assert [r["saga_id"] for r in refunds["items"]] == ["refund-1"]

    def test_pagination(self, client):
        seed(client)
        page = client.get("/api/v1/runs", params={"limit": 1, "offset": 1}).json()
        assert page["total"] == 3
        assert [r["saga_id"] for r in page["items"]] == ["bad-1"]

    @pytest.mark.parametrize(
        "params",
        [{"status": "bogus"}, {"limit": 0}, {"limit": 501}, {"offset": -1}],
    )
    def test_invalid_query_is_rejected(self, client, params):
        assert client.get("/api/v1/runs", params=params).status_code == 422

    def test_run_detail_includes_steps_and_events(self, client):
        seed(client)
        run = client.get("/api/v1/runs/bad-1").json()
        assert run["status"] == "failed"
        assert run["error_type"] == "Declined"
        assert [(s["name"], s["status"]) for s in run["steps"]] == [
            ("reserve", "compensated"),
            ("charge", "failed"),
        ]
        assert len(run["events"]) == 8

    def test_unknown_run_is_404(self, client):
        assert client.get("/api/v1/runs/missing").status_code == 404
        assert client.get("/api/v1/runs/missing/diagram").status_code == 404

    def test_run_diagram(self, client):
        seed(client)
        data = client.get("/api/v1/runs/bad-1/diagram", params={"direction": "TB"}).json()
        assert data["saga_id"] == "bad-1"
        assert data["status"] == "failed"
        assert data["diagram"].startswith("flowchart TB")
        assert ":::compensated" in data["diagram"]


class TestMetricsSummary:
    def test_summary(self, client):
        seed(client)
        summary = client.get("/api/v1/metrics/summary").json()
        assert summary["total_runs"] == 3
        assert summary["by_status"]["failed"] == 1
        assert summary["success_rate"] == 0.5
        assert set(summary["by_saga"]) == {"OrderSaga", "RefundSaga"}


class TestIngestionProjection:
    def test_duplicate_event_is_not_republished(self, client):
        hub = client.app.state.event_hub
        subscription = hub.subscribe()
        try:
            event = ev("saga.started")
            assert post(client, event)["duplicate"] is False
            second = post(client, event)
            assert second["duplicate"] is True
            assert second["active_subscribers"] == 0
            assert subscription.queue.qsize() == 1
        finally:
            hub.unsubscribe(subscription)

    @pytest.mark.parametrize(
        "overrides",
        [{"saga_id": ""}, {"saga_name": "x" * 257}, {"step_name": ""}, {"error_type": "e" * 257}],
    )
    def test_oversized_or_empty_fields_are_rejected(self, client, overrides):
        event = ev("saga.started")
        event.update(overrides)
        response = client.post("/api/v1/events", json=event, headers=AUTH)
        assert response.status_code == 422


def test_sse_subscriber_limit_applies_to_per_run_stream():
    app = create_app(event_token=TOKEN, max_sse_subscribers=1)
    hub = app.state.event_hub
    held = hub.subscribe()
    try:
        with TestClient(app) as test_client:
            assert test_client.get("/api/v1/runs/s1/events").status_code == 503
            assert test_client.get("/api/v1/live").status_code == 503
    finally:
        hub.unsubscribe(held)


@contextlib.asynccontextmanager
async def live_server(app):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", lifespan="off")
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(500):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        assert server.started, "Uvicorn server did not start"
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except TimeoutError:
            server.force_exit = True
            await task
        finally:
            if sock.fileno() != -1:
                sock.close()


async def read_sse(lines, count):
    """Collect ``count`` SSE messages as (event_name, data) tuples."""
    messages, name = [], "message"
    while len(messages) < count:
        line = await asyncio.wait_for(anext(lines), timeout=5.0)
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            messages.append((name, json.loads(line.removeprefix("data: "))))
            name = "message"
    return messages


@pytest.mark.asyncio
async def test_per_run_sse_sends_snapshot_then_only_that_runs_events():
    app = create_app(event_token=TOKEN)
    timeout = httpx.Timeout(connect=3.0, read=None, write=3.0, pool=3.0)

    async with live_server(app) as base_url, httpx.AsyncClient(timeout=timeout) as http:
        started = ev("saga.started", "target")
        assert (await http.post(f"{base_url}/api/v1/events", json=started, headers=AUTH)).is_success

        async with http.stream("GET", f"{base_url}/api/v1/runs/target/events") as stream:
            assert stream.status_code == 200
            lines = stream.aiter_lines()

            (snapshot,) = await read_sse(lines, 1)
            assert snapshot[0] == "snapshot"
            assert snapshot[1]["saga_id"] == "target"
            assert snapshot[1]["status"] == "running"

            other = ev("saga.started", "other")
            step = ev("step.started", "target", step="charge")
            done = ev("saga.completed", "target")
            for event in (other, step, done):
                response = await http.post(f"{base_url}/api/v1/events", json=event, headers=AUTH)
                assert response.is_success

            received = await read_sse(lines, 2)

    assert [data["event_id"] for _, data in received] == [step["event_id"], done["event_id"]]


@pytest.mark.asyncio
async def test_per_run_sse_for_unknown_run_has_no_snapshot():
    app = create_app(event_token=TOKEN)
    timeout = httpx.Timeout(connect=3.0, read=None, write=3.0, pool=3.0)

    async with live_server(app) as base_url, httpx.AsyncClient(timeout=timeout) as http:
        async with http.stream("GET", f"{base_url}/api/v1/runs/later/events") as stream:
            assert stream.status_code == 200
            lines = stream.aiter_lines()

            event = ev("saga.started", "later")
            response = await http.post(f"{base_url}/api/v1/events", json=event, headers=AUTH)
            assert response.is_success

            ((name, data),) = await read_sse(lines, 1)

    assert name == "message"
    assert data["event_id"] == event["event_id"]
