"""Run, metrics and live-event routes of the visualization server."""

from __future__ import annotations

import hmac
import json
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from sagaz.visualization._server_hub import (
    EventHub,
    VisualizationEvent,
    _sse_stream,
    _Subscription,
)
from sagaz.visualization.runs import RunRecord, RunStatus, RunStore, saga_runtime_diagram


def register_run_routes(app: FastAPI, *, event_token: str | None) -> None:
    """Register run, metrics, event-ingestion and live SSE routes on *app*.

    Uses the event hub and run store already attached to ``app.state``.
    """
    hub: EventHub = app.state.event_hub
    store: RunStore = app.state.run_store

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
