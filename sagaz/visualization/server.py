"""
Sagaz Visualization Server.

A lightweight FastAPI application that provides:
- HTML dashboard with Mermaid diagram support
- REST API for saga discovery and diagram generation
- SSE event bus for real-time saga status updates
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

# ---------------------------------------------------------------------------
# SSE event queues — populated by publish_event(), consumed by SSE endpoint
# ---------------------------------------------------------------------------
_EVENT_QUEUES: list[asyncio.Queue] = []

# ---------------------------------------------------------------------------
# Dashboard HTML template
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Sagaz — Visualization Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
  <style>
    body { font-family: sans-serif; margin: 2rem; background: #0d1117; color: #e6edf3; }
    h1 { color: #58a6ff; }
    #diagram { background: #161b22; padding: 1rem; border-radius: 8px; }
  </style>
</head>
<body>
  <h1>Sagaz — Saga Visualization Dashboard</h1>
  <p>Select a saga from the API to view its execution graph.</p>
  <div id="diagram" class="mermaid">
    flowchart TB
      A[No saga selected] --> B[Use /api/v1/diagram?saga=module:Class]
  </div>
  <script>mermaid.initialize({ startOnLoad: true, theme: "dark" });</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _discover_saga_cls(class_path: str) -> type:
    """Resolve ``'module.path:ClassName'`` to the actual class.

    Raises
    ------
    ValueError
        If *class_path* does not contain a colon, or the class cannot be
        found in the resolved module.
    ModuleNotFoundError
        If the module portion cannot be imported.
    """
    if ":" not in class_path:
        msg = f"Invalid class path {class_path!r}: expected 'module:ClassName'."
        raise ValueError(msg)

    module_path, class_name = class_path.rsplit(":", 1)
    module = importlib.import_module(module_path)  # raises ModuleNotFoundError if absent

    cls = getattr(module, class_name, None)
    if cls is None:
        msg = f"Class {class_name!r} not found in module {module_path!r}."
        raise ValueError(msg)
    return cls


# ---------------------------------------------------------------------------
# Event broadcasting
# ---------------------------------------------------------------------------


def publish_event(event: dict[str, Any]) -> None:
    """Broadcast *event* to all active SSE subscriber queues.

    Full queues are silently skipped to avoid blocking callers.
    """
    dead: list[asyncio.Queue] = []
    for q in list(_EVENT_QUEUES):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # consumer is too slow — skip
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            _EVENT_QUEUES.remove(q)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(registered_sagas: list[str] | None = None) -> FastAPI:
    """Create and return the Sagaz visualization FastAPI application.

    Parameters
    ----------
    registered_sagas:
        Optional list of ``'module:ClassName'`` strings that will be
        returned by ``GET /api/v1/sagas``.
    """
    _sagas: list[str] = list(registered_sagas or [])

    app = FastAPI(title="Sagaz Visualization", version="1.0.0")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        """Serve the HTML visualization dashboard."""
        return HTMLResponse(content=_DASHBOARD_HTML)

    @app.get("/api/v1/sagas")
    async def list_sagas() -> dict[str, list[str]]:
        """Return the list of registered saga class paths."""
        return {"sagas": _sagas}

    @app.get("/api/v1/diagram")
    async def get_diagram(saga: str, direction: str = "TB") -> dict[str, str]:
        """Return the Mermaid diagram string for the given saga class.

        Parameters
        ----------
        saga:
            ``'module:ClassName'`` of the saga to visualize.
        direction:
            Mermaid flowchart direction (TB, LR, BT, RL).
        """
        try:
            cls = _discover_saga_cls(saga)
        except (ModuleNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail=f"Saga {saga!r} not found.")

        if not hasattr(cls, "to_mermaid"):
            raise HTTPException(
                status_code=422,
                detail=f"{saga!r} does not implement to_mermaid().",
            )

        try:
            instance = cls()
        except TypeError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot instantiate {saga!r}: {exc}",
            )

        try:
            await instance.build()
        except Exception:
            pass  # produce diagram even if build() fails

        diagram: str = instance.to_mermaid(direction=direction)
        return {"saga": saga, "diagram": diagram}

    return app
