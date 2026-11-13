"""FastAPI server for the Sagaz visualization dashboard and live events."""

from __future__ import annotations

import asyncio
import importlib
from importlib import resources
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from sagaz.visualization._server_hub import (
    EventHub,
    EventType,
    VisualizationEvent,
)
from sagaz.visualization._server_hub import _sse_stream as _sse_stream
from sagaz.visualization._server_routes import register_run_routes
from sagaz.visualization.analytics_api import (
    analytics_storage_lifespan,
    register_analytics_routes,
)
from sagaz.visualization.assets import MERMAID, AssetCache, AssetUnavailableError
from sagaz.visualization.runs import RunStore

__all__ = [
    "EventHub",
    "EventType",
    "VisualizationEvent",
    "create_app",
    "run_server",
]


def _load_dashboard_html() -> str:
    return (
        resources.files("sagaz.visualization")
        .joinpath("static/index.html")
        .read_text(encoding="utf-8")
    )


def _discover_saga_cls(import_path: str) -> type:
    """Resolve a Saga class from ``module.path:ClassName``."""
    if ":" not in import_path:
        msg = f"Expected 'module:ClassName', got {import_path!r}"
        raise ValueError(msg)

    module_path, class_name = import_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)

    if cls is None or not isinstance(cls, type):
        msg = f"Class {class_name!r} not found in module {module_path!r}"
        raise ValueError(msg)

    return cls


async def _build_saga_instance(cls: type) -> Any:
    instance = cls()
    build = getattr(instance, "build", None)

    if build is not None:
        result = build()
        if asyncio.iscoroutine(result):
            await result

    return instance


def create_app(
    registered_sagas: list[str] | None = None,
    *,
    event_token: str | None = None,
    event_queue_size: int = 100,
    max_sse_subscribers: int = 100,
    max_runs: int = 1000,
    asset_cache: AssetCache | None = None,
    analytics_storage: Any | None = None,
    analytics_storage_url: str | None = None,
) -> FastAPI:
    """Create the visualization API.

    Event ingestion is disabled unless an explicit bearer token is configured.
    The event hub and run store are process-local: Saga workers send events to
    this server over HTTP; the run store folds them into bounded run records and
    SSE subscribers consume them from this application's hub.
    """
    app = FastAPI(
        title="Sagaz Visualization",
        version="1.0.0",
        lifespan=lambda app: analytics_storage_lifespan(app, analytics_storage_url),
    )
    # Saga storage the /api/v1/analytics/* reports are built from (read-only):
    # an object passed in directly, or one opened from a URL at startup.
    app.state.analytics_storage = analytics_storage
    app.state.event_hub = EventHub(
        queue_size=event_queue_size,
        max_subscribers=max_sse_subscribers,
    )
    app.state.run_store = RunStore(max_runs=max_runs)
    app.state.asset_cache = asset_cache or AssetCache()
    sagas = list(registered_sagas or [])
    dashboard_html = _load_dashboard_html()
    register_analytics_routes(app)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> str:
        return dashboard_html

    @app.get("/static/mermaid.min.js", include_in_schema=False)
    async def mermaid_js() -> Response:
        try:
            body = await app.state.asset_cache.get(MERMAID)
        except AssetUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            body,
            media_type="text/javascript",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.get("/api/v1/sagas")
    async def list_sagas() -> dict[str, list[str]]:
        return {"sagas": sagas}

    @app.get("/api/v1/diagram")
    async def get_diagram(
        saga: str,
        direction: Literal["TB", "LR", "BT", "RL"] = "TB",
    ) -> JSONResponse:
        try:
            cls = _discover_saga_cls(saga)
        except (ValueError, ImportError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            instance = await _build_saga_instance(cls)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Build failed: {type(exc).__name__}",
            ) from exc

        if not callable(getattr(instance, "to_mermaid", None)):
            raise HTTPException(
                status_code=422,
                detail=f"{cls.__name__} has no to_mermaid() method",
            )

        try:
            diagram = instance.to_mermaid(direction=direction)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Diagram generation failed: {type(exc).__name__}",
            ) from exc

        return JSONResponse(
            {
                "saga": saga,
                "direction": direction,
                "diagram": diagram,
            }
        )

    register_run_routes(app, event_token=event_token)

    return app


def run_server(
    app: FastAPI | None = None,
    host: str = "127.0.0.1",
    port: int = 7070,
    registered_sagas: list[str] | None = None,
    *,
    event_token: str | None = None,
    analytics_storage_url: str | None = None,
) -> None:
    """Run the visualization server with Uvicorn."""
    try:
        import uvicorn
    except ImportError as exc:
        msg = "uvicorn is required; install sagaz[visualization]"
        raise ImportError(msg) from exc

    if app is None:
        app = create_app(
            registered_sagas,
            event_token=event_token,
            analytics_storage_url=analytics_storage_url,
        )

    uvicorn.run(app, host=host, port=port)
