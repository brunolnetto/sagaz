"""FastAPI server for the Sagaz visualization dashboard and live events."""

from __future__ import annotations

import asyncio
import hmac
import importlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from sagaz.visualization.analytics_api import (
    analytics_storage_lifespan,
    register_analytics_routes,
)
from sagaz.visualization.assets import MERMAID, AssetCache, AssetUnavailableError
from sagaz.visualization.runs import RunRecord, RunStatus, RunStore, saga_runtime_diagram

EventType = Literal[
    "saga.started",
    "saga.completed",
    "saga.failed",
    "step.started",
    "step.succeeded",
    "step.failed",
    "step.compensation_started",
    "step.compensated",
]


class VisualizationEvent(BaseModel):
    """Allowlisted event schema. Arbitrary Saga context is deliberately rejected."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: EventType
    saga_id: str = Field(min_length=1, max_length=256)
    saga_name: str = Field(min_length=1, max_length=256)
    step_name: str | None = Field(default=None, min_length=1, max_length=256)
    error_type: str | None = Field(default=None, max_length=256)
    occurred_at: datetime


@dataclass(eq=False, slots=True)
class _Subscription:
    queue: asyncio.Queue[dict[str, Any]]
    dropped: int = 0


class EventHub:
    """Bounded, process-local fan-out hub owned by one FastAPI application."""

    def __init__(
        self,
        queue_size: int = 100,
        max_subscribers: int = 100,
    ) -> None:
        if queue_size < 1:
            message = "queue_size must be positive"
            raise ValueError(message)
        if max_subscribers < 1:
            message = "max_subscribers must be positive"
            raise ValueError(message)

        self.queue_size = queue_size
        self.max_subscribers = max_subscribers
        self._subscribers: set[_Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> _Subscription | None:
        if len(self._subscribers) >= self.max_subscribers:
            return None

        subscription = _Subscription(asyncio.Queue(maxsize=self.queue_size))
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: _Subscription) -> None:
        self._subscribers.discard(subscription)

    def publish(self, event: dict[str, Any]) -> int:
        """Fan out an event, dropping oldest queued messages on overflow."""
        delivered = 0

        for subscription in tuple(self._subscribers):
            queue = subscription.queue

            if queue.full():
                try:
                    queue.get_nowait()
                    subscription.dropped += 1
                except asyncio.QueueEmpty:
                    pass

            try:
                queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                # Defensive: queue operations are synchronous on this event loop.
                subscription.dropped += 1

        return delivered


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


def _sse_stream(
    hub: EventHub,
    subscription: _Subscription,
    *,
    accept: Callable[[dict[str, Any]], bool] | None = None,
    initial: list[ServerSentEvent] | None = None,
) -> AsyncIterator[ServerSentEvent]:
    async def stream() -> AsyncIterator[ServerSentEvent]:
        try:
            for message in initial or ():
                yield message
            while True:
                event = await subscription.queue.get()

                if subscription.dropped:
                    dropped = subscription.dropped
                    subscription.dropped = 0
                    yield ServerSentEvent(
                        event="gap",
                        data=json.dumps({"dropped": dropped}),
                    )

                if accept is not None and not accept(event):
                    continue

                yield ServerSentEvent(
                    id=event["event_id"],
                    data=json.dumps(event, separators=(",", ":")),
                )
        finally:
            hub.unsubscribe(subscription)

    return stream()


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
    hub: EventHub = app.state.event_hub
    store: RunStore = app.state.run_store
    dashboard_html = _load_dashboard_html()
    register_analytics_routes(app)

    def _subscribe() -> _Subscription:
        subscription = hub.subscribe()
        if subscription is None:
            raise HTTPException(
                status_code=503,
                detail="Maximum number of SSE subscribers reached",
            )
        return subscription

    def _require_run(saga_id: str) -> RunRecord:
        run = store.get(saga_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

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

    # Unversioned /api/sagas/... and /api/metrics/... are the paths specified in #58;
    # they serve the same handlers as the /api/v1 routes.
    @app.get("/api/v1/runs")
    @app.get("/api/sagas")
    async def list_runs(
        status: RunStatus | None = None,
        saga_name: str | None = Query(default=None, max_length=256),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        runs, total = store.list(status=status, saga_name=saga_name, limit=limit, offset=offset)
        return {
            "items": [run.summary() for run in runs],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/v1/runs/{saga_id}")
    @app.get("/api/sagas/{saga_id}")
    async def get_run(saga_id: str) -> dict[str, Any]:
        return _require_run(saga_id).to_dict()

    @app.get("/api/v1/runs/{saga_id}/diagram")
    @app.get("/api/sagas/{saga_id}/diagram")
    async def get_run_diagram(
        saga_id: str,
        direction: Literal["TB", "LR", "BT", "RL"] = "LR",
    ) -> dict[str, Any]:
        run = _require_run(saga_id)
        return {
            "saga_id": run.saga_id,
            "status": run.status,
            "direction": direction,
            "diagram": saga_runtime_diagram(run, direction=direction),
        }

    @app.get("/api/v1/runs/{saga_id}/events")
    @app.get("/api/sagas/{saga_id}/events")
    async def run_events(saga_id: str) -> EventSourceResponse:
        subscription = _subscribe()
        run = store.get(saga_id)
        initial = []
        if run is not None:
            initial.append(
                ServerSentEvent(
                    event="snapshot",
                    data=json.dumps(run.to_dict(), separators=(",", ":")),
                )
            )
        return EventSourceResponse(
            _sse_stream(
                hub,
                subscription,
                accept=lambda event: event["saga_id"] == saga_id,
                initial=initial,
            ),
            ping=15,
        )

    @app.get("/api/v1/metrics/summary")
    @app.get("/api/metrics/summary")
    async def metrics_summary() -> dict[str, Any]:
        return store.summary()

    @app.post("/api/v1/events", status_code=202)
    async def ingest_event(
        event: VisualizationEvent,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if event_token is None:
            raise HTTPException(
                status_code=503,
                detail="Event ingestion is disabled; configure an event token",
            )

        scheme, separator, supplied_token = (authorization or "").partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not hmac.compare_digest(supplied_token, event_token)
        ):
            raise HTTPException(status_code=401, detail="Invalid bearer token")

        event_data = event.model_dump(mode="json")
        if not store.apply(event_data):
            return {
                "accepted": True,
                "duplicate": True,
                "event_id": str(event.event_id),
                "active_subscribers": 0,
            }

        delivered = hub.publish(event_data)

        return {
            "accepted": True,
            "duplicate": False,
            "event_id": str(event.event_id),
            "active_subscribers": delivered,
        }

    @app.get("/api/v1/live")
    async def live_events() -> EventSourceResponse:
        return EventSourceResponse(_sse_stream(hub, _subscribe()), ping=15)

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
