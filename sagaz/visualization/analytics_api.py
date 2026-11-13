"""Gold-layer analytics endpoints for the visualization monitor.

``/api/v1/analytics/<report>`` rebuilds the ``sagaz[analytics]`` pipeline from
the configured saga storage (read-only) and returns one Gold query. The
analytics extra is optional: without it the endpoints answer 501 with the
install hint, and without a configured storage they answer 503.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder

#: Public report name → ``SagaQueries`` attribute.
ANALYTICS_REPORTS: dict[str, str] = {
    "summary": "SAGA_SUMMARY",
    "step-latency": "STEP_LATENCY",
    "compensations": "COMPENSATION_EVENTS",
    "lifecycle": "SAGA_LIFECYCLE_MILESTONES",
}

NOT_CONFIGURED = (
    "Analytics storage is not configured. Start the monitor with "
    "--storage-url (or set SAGAZ_STORAGE_URL) pointing at the saga database."
)
NOT_INSTALLED = "Analytics requires the optional extra: pip install 'sagaz[analytics]'"


@asynccontextmanager
async def analytics_storage_lifespan(app: FastAPI, url: str | None) -> AsyncIterator[None]:
    """Open a StorageManager for ``url`` for the app's lifetime (no-op without a URL)."""
    if url is None:
        yield
        return
    from sagaz.core.storage import create_storage_manager

    manager = create_storage_manager(url)
    await manager.initialize()
    app.state.analytics_storage = manager
    try:
        yield
    finally:
        await manager.close()


async def build_report(storage: Any, report: str) -> dict[str, Any]:
    """Run the pipeline over ``storage`` and return one Gold report."""
    try:
        from sagaz.analytics import SagaAnalyticsPipeline, SagaQueries
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=NOT_INSTALLED) from exc

    with SagaAnalyticsPipeline(storage) as pipeline:
        stats = await pipeline.run()
        rows = pipeline.query(getattr(SagaQueries, ANALYTICS_REPORTS[report]))
    return {
        "report": report,
        "rows": jsonable_encoder(rows),
        "sagas_loaded": stats.sagas_loaded,
        "quality_errors": len(stats.quality_errors),
    }


def register_analytics_routes(app: FastAPI) -> None:
    @app.get("/api/v1/analytics")
    async def analytics_index() -> dict[str, Any]:
        return {
            "reports": sorted(ANALYTICS_REPORTS),
            "configured": app.state.analytics_storage is not None,
        }

    @app.get("/api/v1/analytics/{report}")
    async def analytics_report(report: str) -> dict[str, Any]:
        if report not in ANALYTICS_REPORTS:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown report {report!r}; available: {sorted(ANALYTICS_REPORTS)}",
            )
        if app.state.analytics_storage is None:
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
        return await build_report(app.state.analytics_storage, report)
