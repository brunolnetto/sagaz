"""
Unit tests for sagaz.visualization.server — FastAPI visualization server.
Uses TestClient (synchronous) for endpoint testing; no real Uvicorn needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sagaz.visualization.server import (
    _EVENT_QUEUES,
    _discover_saga_cls,
    create_app,
    publish_event,
)

# ---------------------------------------------------------------------------
# Helper saga class
# ---------------------------------------------------------------------------


class _SimpleSaga:
    async def build(self) -> None:
        pass

    def to_mermaid(self, direction: str = "TB", **kwargs) -> str:
        return f"flowchart {direction}\n  A --> B"


@pytest.fixture
def client():
    app = create_app(registered_sagas=["mymod:SimpleSaga"])
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests — static endpoints
# ---------------------------------------------------------------------------


class TestDashboardEndpoint:
    def test_root_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_contains_mermaid_script(self, client):
        resp = client.get("/")
        assert "mermaid" in resp.text.lower()

    def test_dashboard_contains_saga_label(self, client):
        resp = client.get("/")
        assert "sagaz" in resp.text.lower()


class TestSagasEndpoint:
    def test_returns_registered_sagas(self, client):
        resp = client.get("/api/v1/sagas")
        assert resp.status_code == 200
        data = resp.json()
        assert "sagas" in data
        assert "mymod:SimpleSaga" in data["sagas"]

    def test_empty_app_returns_empty_list(self):
        app = create_app()
        c = TestClient(app)
        resp = c.get("/api/v1/sagas")
        assert resp.json()["sagas"] == []


# ---------------------------------------------------------------------------
# Tests — /api/v1/diagram
# ---------------------------------------------------------------------------


class TestDiagramEndpoint:
    def _patched_client(self, saga_cls=_SimpleSaga) -> TestClient:
        """Return a TestClient whose app points _discover_saga_cls to saga_cls."""
        app = create_app()
        # Inject the class into a temporary module attribute so the real import works
        import sys

        mod = type(sys)("_test_saga_mod")
        mod.MySaga = saga_cls  # type: ignore[attr-defined]
        sys.modules["_test_saga_mod"] = mod

        return TestClient(app, raise_server_exceptions=False)

    def _url(self, cls: type, direction: str = "TB") -> str:
        return f"/api/v1/diagram?saga=_test_saga_mod:MySaga&direction={direction}"

    def test_diagram_returns_mermaid_string(self):
        client = self._patched_client()
        resp = client.get(self._url(_SimpleSaga))
        assert resp.status_code == 200
        data = resp.json()
        assert "diagram" in data
        assert "flowchart" in data["diagram"]

    def test_diagram_respects_direction_param(self):
        client = self._patched_client()
        resp = client.get(self._url(_SimpleSaga, direction="LR"))
        assert resp.status_code == 200
        assert "LR" in resp.json()["diagram"]

    def test_unknown_module_returns_404(self):
        app = create_app()
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/api/v1/diagram?saga=nonexistent.module:MissingClass")
        assert resp.status_code == 404

    def test_missing_to_mermaid_returns_422(self):
        class NoMermaidSaga:
            async def build(self) -> None:
                pass

        import sys

        mod = type(sys)("_test_no_mermaid_mod")
        mod.MySaga = NoMermaidSaga  # type: ignore[attr-defined]
        sys.modules["_test_no_mermaid_mod"] = mod

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/diagram?saga=_test_no_mermaid_mod:MySaga")
        assert resp.status_code == 422

    def test_saga_key_present_in_response(self):
        client = self._patched_client()
        resp = client.get(self._url(_SimpleSaga))
        assert resp.json()["saga"] == "_test_saga_mod:MySaga"


# ---------------------------------------------------------------------------
# Tests — _discover_saga_cls
# ---------------------------------------------------------------------------


class TestDiscoverSagaCls:
    def test_raises_on_missing_colon(self):
        with pytest.raises(ValueError, match="module:ClassName"):
            _discover_saga_cls("myapp.OrderSaga")

    def test_raises_on_module_not_found(self):
        with pytest.raises(ModuleNotFoundError):
            _discover_saga_cls("nonexistent.module:AClass")

    def test_raises_when_class_absent(self):
        with patch("importlib.import_module") as mock_import:
            mock_import.return_value = MagicMock(spec=[])
            with pytest.raises(ValueError, match="not found"):
                _discover_saga_cls("mymod:MissingClass")

    def test_returns_class_on_success(self):
        with patch("importlib.import_module") as mock_import:
            module = MagicMock()
            module.MySaga = _SimpleSaga
            mock_import.return_value = module
            cls = _discover_saga_cls("mymod:MySaga")
        assert cls is _SimpleSaga


# ---------------------------------------------------------------------------
# Tests — publish_event (SSE broadcast)
# ---------------------------------------------------------------------------


class TestPublishEvent:
    def test_publish_puts_to_all_queues(self):
        import asyncio

        loop = asyncio.new_event_loop()
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        _EVENT_QUEUES.extend([q1, q2])
        try:
            publish_event({"type": "step_completed", "step": "charge"})
            assert q1.qsize() == 1
            assert q2.qsize() == 1
        finally:
            _EVENT_QUEUES.remove(q1)
            _EVENT_QUEUES.remove(q2)
            loop.close()

    def test_publish_to_full_queue_does_not_raise(self):
        import asyncio

        q = asyncio.Queue(maxsize=1)
        q.put_nowait("existing")
        _EVENT_QUEUES.append(q)
        try:
            publish_event({"event": "overflow"})  # should not raise
        finally:
            _EVENT_QUEUES.remove(q)
