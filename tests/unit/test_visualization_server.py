"""Tests for the canonical visualization FastAPI server."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from datetime import UTC, datetime
from types import ModuleType
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from sagaz.visualization.server import EventHub, create_app

TOKEN = "test-visualization-token-0123456789"


class _SimpleSaga:
    async def build(self) -> None:
        pass

    def to_mermaid(self, direction: str = "TB") -> str:
        return f"flowchart {direction}\n  A --> B"


@pytest.fixture
def client():
    app = create_app(
        registered_sagas=["test_visualization_module:SimpleSaga"],
        event_token=TOKEN,
    )
    module = ModuleType("test_visualization_module")
    module.SimpleSaga = _SimpleSaga
    sys.modules[module.__name__] = module

    with TestClient(app) as test_client:
        yield test_client

    sys.modules.pop("test_visualization_module", None)


def make_event(**overrides):
    event = {
        "event_id": str(uuid4()),
        "event_type": "saga.started",
        "saga_id": "saga-123",
        "saga_name": "OrderSaga",
        "step_name": None,
        "error_type": None,
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    event.update(overrides)
    return event


class TestDashboardEndpoint:
    def test_root_returns_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "EventSource" in response.text

    def test_dashboard_contains_sagaz_label(self, client):
        assert "Sagaz" in client.get("/").text


class TestSagasEndpoint:
    def test_returns_registered_sagas(self, client):
        response = client.get("/api/v1/sagas")
        assert response.status_code == 200
        assert response.json() == {"sagas": ["test_visualization_module:SimpleSaga"]}

    def test_empty_app_returns_empty_list(self):
        with TestClient(create_app()) as test_client:
            response = test_client.get("/api/v1/sagas")
        assert response.json() == {"sagas": []}


class TestDiagramEndpoint:
    def test_diagram_returns_mermaid_string(self, client):
        response = client.get(
            "/api/v1/diagram",
            params={"saga": "test_visualization_module:SimpleSaga"},
        )
        assert response.status_code == 200
        assert response.json()["diagram"].startswith("flowchart TB")

    def test_diagram_respects_direction(self, client):
        response = client.get(
            "/api/v1/diagram",
            params={
                "saga": "test_visualization_module:SimpleSaga",
                "direction": "LR",
            },
        )
        assert response.status_code == 200
        assert response.json()["direction"] == "LR"
        assert response.json()["diagram"].startswith("flowchart LR")

    def test_invalid_direction_is_rejected(self, client):
        response = client.get(
            "/api/v1/diagram",
            params={
                "saga": "test_visualization_module:SimpleSaga",
                "direction": "INVALID",
            },
        )
        assert response.status_code == 422

    def test_unknown_module_returns_404(self, client):
        response = client.get(
            "/api/v1/diagram",
            params={"saga": "does_not_exist:MissingSaga"},
        )
        assert response.status_code == 404

    def test_missing_to_mermaid_returns_422(self, client):
        module = ModuleType("test_no_mermaid_module")

        class NoMermaidSaga:
            async def build(self):
                pass

        module.NoMermaidSaga = NoMermaidSaga
        sys.modules[module.__name__] = module

        try:
            response = client.get(
                "/api/v1/diagram",
                params={"saga": "test_no_mermaid_module:NoMermaidSaga"},
            )
        finally:
            sys.modules.pop(module.__name__, None)

        assert response.status_code == 422


class TestEventIngestion:
    def test_event_ingestion_requires_bearer_token(self, client):
        response = client.post("/api/v1/events", json=make_event())
        assert response.status_code == 401

    def test_event_ingestion_rejects_wrong_token(self, client):
        response = client.post(
            "/api/v1/events",
            json=make_event(),
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401

    def test_event_ingestion_is_disabled_without_server_token(self):
        with TestClient(create_app()) as test_client:
            response = test_client.post(
                "/api/v1/events",
                json=make_event(),
                headers={"Authorization": "Bearer anything"},
            )
        assert response.status_code == 503

    def test_event_ingestion_rejects_unapproved_fields(self, client):
        event = make_event()
        event["context"] = {"secret": "must-not-be-accepted"}

        response = client.post(
            "/api/v1/events",
            json=event,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == 422

    def test_posted_event_reaches_application_event_hub(self, client):
        hub: EventHub = client.app.state.event_hub
        subscription = hub.subscribe()
        assert subscription is not None

        try:
            event = make_event()
            response = client.post(
                "/api/v1/events",
                json=event,
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

            assert response.status_code == 202
            assert response.json()["accepted"] is True
            assert subscription.queue.get_nowait()["event_id"] == event["event_id"]
        finally:
            hub.unsubscribe(subscription)

    @pytest.mark.asyncio
    async def test_sse_stream_receives_posted_event(self):
        app = create_app(event_token=TOKEN)

        listening_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listening_socket.bind(("127.0.0.1", 0))
        listening_socket.listen(128)
        listening_socket.setblocking(False)

        port = listening_socket.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="critical",
                lifespan="off",
            )
        )
        server_task = asyncio.create_task(server.serve(sockets=[listening_socket]))

        try:
            for _ in range(500):
                if server.started:
                    break
                if server_task.done():
                    await server_task
                await asyncio.sleep(0.01)

            assert server.started, "Uvicorn server did not start"

            event = make_event(
                event_type="step.succeeded",
                step_name="charge",
            )
            base_url = f"http://127.0.0.1:{port}"

            timeout = httpx.Timeout(
                connect=3.0,
                read=None,
                write=3.0,
                pool=3.0,
            )

            async with httpx.AsyncClient(timeout=timeout) as http_client:
                async with http_client.stream(
                    "GET",
                    f"{base_url}/api/v1/live",
                ) as stream:
                    assert stream.status_code == 200
                    assert stream.headers["content-type"].startswith("text/event-stream")

                    # The SSE connection is open before the independent POST.
                    response = await http_client.post(
                        f"{base_url}/api/v1/events",
                        json=event,
                        headers={"Authorization": f"Bearer {TOKEN}"},
                    )
                    assert response.status_code == 202

                    data_line = None
                    lines = stream.aiter_lines()

                    for _ in range(10):
                        line = await asyncio.wait_for(
                            anext(lines),
                            timeout=3.0,
                        )
                        if line.startswith("data: "):
                            data_line = line
                            break

                    assert data_line is not None, "SSE event was not delivered"

                    received = json.loads(data_line.removeprefix("data: "))
                    assert received["event_id"] == event["event_id"]
                    assert received["event_type"] == "step.succeeded"
                    assert received["step_name"] == "charge"

        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(server_task, timeout=5.0)
            except TimeoutError:
                server.force_exit = True
                await server_task
            finally:
                if listening_socket.fileno() != -1:
                    listening_socket.close()


class TestEventHub:
    def test_publish_fans_out_to_all_subscribers(self):
        hub = EventHub(queue_size=2)
        first = hub.subscribe()
        second = hub.subscribe()

        assert first is not None
        assert second is not None

        try:
            event = {"event_id": "1", "event_type": "saga.started"}
            assert hub.publish(event) == 2
            assert first.queue.get_nowait() == event
            assert second.queue.get_nowait() == event
        finally:
            hub.unsubscribe(first)
            hub.unsubscribe(second)

    def test_overflow_drops_oldest_and_counts_gap(self):
        hub = EventHub(queue_size=1)
        subscription = hub.subscribe()
        assert subscription is not None

        try:
            hub.publish({"event_id": "old"})
            hub.publish({"event_id": "new"})

            assert subscription.dropped == 1
            assert subscription.queue.get_nowait() == {"event_id": "new"}
        finally:
            hub.unsubscribe(subscription)

    def test_maximum_subscribers_is_enforced(self):
        hub = EventHub(max_subscribers=1)
        first = hub.subscribe()

        try:
            assert first is not None
            assert hub.subscribe() is None
        finally:
            hub.unsubscribe(first)

    def test_invalid_queue_configuration_is_rejected(self):
        with pytest.raises(ValueError, match="queue_size"):
            EventHub(queue_size=0)


@pytest.mark.asyncio
async def test_real_saga_lifecycle_reaches_sse_through_http():
    """A real Saga run must reach an SSE subscriber through HTTP ingestion."""
    from sagaz import Saga, action
    from sagaz.visualization.events import VisualizationSagaListener

    app = create_app(event_token=TOKEN)

    listening_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listening_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listening_socket.bind(("127.0.0.1", 0))
    listening_socket.listen(128)
    listening_socket.setblocking(False)

    port = listening_socket.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
            lifespan="off",
        )
    )
    server_task = asyncio.create_task(server.serve(sockets=[listening_socket]))

    try:
        for _ in range(500):
            if server.started:
                break
            if server_task.done():
                await server_task
            await asyncio.sleep(0.01)

        assert server.started, "Uvicorn server did not start"

        listener = VisualizationSagaListener(
            server_url=base_url,
            token=TOKEN,
            timeout_seconds=2.0,
        )

        class OrderSaga(Saga):
            saga_name = "OrderSaga"
            listeners = [listener]

            @action("charge")
            async def charge(self, ctx):
                return {"charged": True}

        timeout = httpx.Timeout(
            connect=3.0,
            read=None,
            write=3.0,
            pool=3.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as http_client:
            async with http_client.stream(
                "GET",
                f"{base_url}/api/v1/live",
            ) as stream:
                assert stream.status_code == 200

                saga = OrderSaga()
                result = await saga.run(
                    {"order_id": "order-123"},
                    saga_id="saga-e2e-123",
                )

                assert result["charged"] is True

                events = []
                lines = stream.aiter_lines()

                while len(events) < 4:
                    line = await asyncio.wait_for(
                        anext(lines),
                        timeout=5.0,
                    )
                    if line.startswith("data: "):
                        events.append(json.loads(line.removeprefix("data: ")))

        assert [event["event_type"] for event in events] == [
            "saga.started",
            "step.started",
            "step.succeeded",
            "saga.completed",
        ]

        assert all(event["saga_id"] == "saga-e2e-123" for event in events)
        assert all(event["event_id"] for event in events)

    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except TimeoutError:
            server.force_exit = True
            await server_task
        finally:
            if listening_socket.fileno() != -1:
                listening_socket.close()


class TestDiagramFailures:
    @pytest.fixture
    def module(self):
        module = ModuleType("test_diagram_failure_module")

        class SyncBuildSaga:
            def build(self):
                return None

            def to_mermaid(self, direction="TB"):
                return f"flowchart {direction}"

        class BrokenBuildSaga:
            async def build(self):
                message = "secret detail"
                raise RuntimeError(message)

        class BrokenMermaidSaga:
            def to_mermaid(self, direction="TB"):
                message = "secret detail"
                raise RuntimeError(message)

        module.SyncBuildSaga = SyncBuildSaga
        module.BrokenBuildSaga = BrokenBuildSaga
        module.BrokenMermaidSaga = BrokenMermaidSaga
        module.not_a_class = 42
        sys.modules[module.__name__] = module
        yield module.__name__
        sys.modules.pop(module.__name__, None)

    @pytest.mark.parametrize(
        ("target", "status", "detail"),
        [
            ("SyncBuildSaga", 200, None),
            ("BrokenBuildSaga", 500, "Build failed: RuntimeError"),
            ("BrokenMermaidSaga", 500, "Diagram generation failed: RuntimeError"),
            ("not_a_class", 404, "not found"),
            ("Missing", 404, "not found"),
        ],
    )
    def test_diagram_failure_modes(self, client, module, target, status, detail):
        response = client.get("/api/v1/diagram", params={"saga": f"{module}:{target}"})
        assert response.status_code == status
        if detail is not None:
            assert detail in response.json()["detail"]
            assert "secret" not in response.text

    def test_import_path_without_colon_is_404(self, client):
        response = client.get("/api/v1/diagram", params={"saga": "no_colon_here"})
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_sse_stream_emits_gap_then_filters_events():
    from sagaz.visualization.server import _sse_stream

    hub = EventHub(queue_size=1)
    subscription = hub.subscribe()
    stream = _sse_stream(hub, subscription, accept=lambda e: e["saga_id"] == "keep")

    hub.publish({"event_id": "1", "saga_id": "keep"})
    hub.publish({"event_id": "2", "saga_id": "drop"})  # evicts "1", records a gap
    hub.publish({"event_id": "3", "saga_id": "keep"})  # evicts "2", records a gap

    gap = await anext(stream)
    assert gap.event == "gap"
    assert json.loads(gap.data) == {"dropped": 2}

    message = await anext(stream)
    assert message.id == "3"

    await stream.aclose()
    assert hub.subscriber_count == 0


def test_invalid_max_subscribers_is_rejected():
    with pytest.raises(ValueError, match="max_subscribers"):
        EventHub(max_subscribers=0)


class TestRunServer:
    def test_runs_uvicorn_with_created_app(self, monkeypatch):
        from sagaz.visualization import server as server_module

        calls = {}

        def fake_run(app, host, port):
            calls.update(app=app, host=host, port=port)

        monkeypatch.setattr(uvicorn, "run", fake_run)
        server_module.run_server(host="127.0.0.1", port=7171, event_token=TOKEN)

        assert calls["host"] == "127.0.0.1"
        assert calls["port"] == 7171
        assert calls["app"].title == "Sagaz Visualization"

    def test_uses_supplied_app(self, monkeypatch):
        from sagaz.visualization import server as server_module

        app = create_app()
        seen = []
        monkeypatch.setattr(uvicorn, "run", lambda a, host, port: seen.append(a))
        server_module.run_server(app)
        assert seen == [app]

    def test_missing_uvicorn_raises_helpful_error(self, monkeypatch):
        from sagaz.visualization import server as server_module

        monkeypatch.setitem(sys.modules, "uvicorn", None)
        with pytest.raises(ImportError, match=r"sagaz\[visualization\]"):
            server_module.run_server()
