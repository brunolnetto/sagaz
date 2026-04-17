"""
sagaz.visualization.server — FastAPI-powered visualization UI server.

Exposes:
  GET  /                    → HTML dashboard
  GET  /api/v1/sagas        → All saga class info (auto-discovered)
  GET  /api/v1/diagram      → Mermaid diagram for a saga class
  GET  /api/v1/live         → SSE stream of saga execution events

Install with:  pip install sagaz[visualization]

Usage::

    from sagaz.observability.visualization.server import create_app, run_server

    app = create_app()
    run_server(app, host="127.0.0.1", port=8765)

Or via CLI::

    sagaz serve --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import AsyncGenerator
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError as exc:  # pragma: no cover
    msg = (
        "FastAPI is required for the visualization server. "
        "Install with: pip install sagaz[visualization]"
    )
    raise ImportError(msg) from exc

try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:  # pragma: no cover — library present in test venv
    EventSourceResponse = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process event bus for SSE
# ---------------------------------------------------------------------------

_EVENT_QUEUES: list[asyncio.Queue] = []


def publish_event(event: dict[str, Any]) -> None:
    """Push a saga event to all connected SSE clients (thread-safe)."""
    for q in list(_EVENT_QUEUES):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


# ---------------------------------------------------------------------------
# Saga class discovery helpers
# ---------------------------------------------------------------------------


def _discover_saga_cls(import_path: str) -> type:
    """
    Import a saga class from a dotted import path with colon separator.

    Parameters
    ----------
    import_path:
        E.g. ``"myapp.sagas:OrderSaga"``
    """
    if ":" not in import_path:
        msg = f"import_path must be 'module:ClassName', got {import_path!r}"
        raise ValueError(msg)
    module_path, class_name = import_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        msg = f"Class {class_name!r} not found in module {module_path!r}"
        raise ValueError(msg)
    return cls


async def _build_saga_instance(cls: type) -> Any:
    """Instantiate a Saga class and call build() to populate steps."""
    instance = cls()
    if hasattr(instance, "build"):
        await instance.build()
    return instance


# ---------------------------------------------------------------------------
# HTML dashboard template
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>sagaz Visualization</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; margin: 0; background: #0d1117; color: #e6edf3; }
    header { background: #161b22; padding: 1rem 2rem; border-bottom: 1px solid #30363d; }
    header h1 { margin: 0; font-size: 1.4rem; }
    .layout { display: flex; height: calc(100vh - 60px); }
    .sidebar { width: 280px; background: #161b22; border-right: 1px solid #30363d;
               padding: 1rem; overflow-y: auto; flex-shrink: 0; }
    .sidebar h2 { margin: 0 0 1rem; font-size: 1rem; color: #8b949e; text-transform: uppercase; }
    .saga-item { padding: .5rem .75rem; border-radius: 6px; cursor: pointer;
                 margin-bottom: .25rem; border: 1px solid transparent; font-size: .9rem; }
    .saga-item:hover { background: #1f2937; border-color: #388bfd; }
    .saga-item.active { background: #1f2937; border-color: #388bfd; color: #79c0ff; }
    .main { flex: 1; overflow: auto; padding: 2rem; }
    #diagram { background: #fff; border-radius: 8px; padding: 1.5rem; min-height: 200px; }
    .events { margin-top: 1.5rem; background: #161b22; border: 1px solid #30363d;
              border-radius: 8px; padding: 1rem; max-height: 300px; overflow-y: auto; }
    .event-line { font-size: .8rem; font-family: monospace; padding: .2rem 0;
                  border-bottom: 1px solid #21262d; color: #8b949e; }
    .no-sagas { color: #8b949e; font-style: italic; font-size: .9rem; }
    .controls { margin-bottom: 1rem; display: flex; gap: .75rem; align-items: center; }
    select, button { padding: .4rem .75rem; border-radius: 6px; border: 1px solid #30363d;
                     background: #1f2937; color: #e6edf3; font-size: .85rem; cursor: pointer; }
    button:hover { border-color: #388bfd; }
  </style>
</head>
<body>
  <header><h1>⚡ sagaz Visualization</h1></header>
  <div class="layout">
    <div class="sidebar">
      <h2>Sagas</h2>
      <div id="saga-list">
        <div class="no-sagas">No sagas registered.<br>
          Pass saga import paths as query args: <code>?saga=module:Class</code></div>
      </div>
    </div>
    <div class="main">
      <div class="controls">
        <label for="dir-select">Direction:</label>
        <select id="dir-select">
          <option value="TB">Top→Bottom</option>
          <option value="LR">Left→Right</option>
          <option value="BT">Bottom→Top</option>
          <option value="RL">Right→Left</option>
        </select>
        <button id="refresh-btn">↻ Refresh</button>
      </div>
      <div id="diagram"><em style="color:#8b949e">Select a saga to view its diagram.</em></div>
      <div class="events">
        <strong style="font-size:.85rem;color:#8b949e">Live Events</strong>
        <div id="event-log"></div>
      </div>
    </div>
  </div>
  <script>
    mermaid.initialize({ startOnLoad: false, theme: 'default' });
    let currentSaga = null;

    async function loadSagas() {
      const params = new URLSearchParams(window.location.search);
      const sagaParams = params.getAll('saga');
      const list = document.getElementById('saga-list');
      const res = await fetch('/api/v1/sagas');
      const data = await res.json();
      const sagas = [...(data.sagas || []), ...sagaParams];
      if (sagas.length === 0) return;
      list.innerHTML = '';
      sagas.forEach(s => {
        const item = document.createElement('div');
        item.className = 'saga-item';
        item.textContent = s.split(':').pop();
        item.dataset.path = s;
        item.onclick = () => selectSaga(s, item);
        list.appendChild(item);
      });
    }

    async function selectSaga(path, el) {
      document.querySelectorAll('.saga-item').forEach(i => i.classList.remove('active'));
      el.classList.add('active');
      currentSaga = path;
      await renderDiagram(path);
    }

    async function renderDiagram(path) {
      const dir = document.getElementById('dir-select').value;
      const box = document.getElementById('diagram');
      box.innerHTML = '<em style="color:#8b949e">Loading…</em>';
      try {
        const res = await fetch(`/api/v1/diagram?saga=${encodeURIComponent(path)}&direction=${dir}`);
        if (!res.ok) { box.innerHTML = `<span style="color:red">Error: ${res.statusText}</span>`; return; }
        const { diagram } = await res.json();
        const id = 'mg-' + Date.now();
        box.innerHTML = `<div class="mermaid" id="${id}">${diagram}</div>`;
        await mermaid.run({ querySelector: `#${id}` });
      } catch(e) { box.innerHTML = `<span style="color:red">${e.message}</span>`; }
    }

    document.getElementById('dir-select').onchange = () => { if (currentSaga) renderDiagram(currentSaga); };
    document.getElementById('refresh-btn').onclick = () => { if (currentSaga) renderDiagram(currentSaga); };

    // SSE
    const evtSource = new EventSource('/api/v1/live');
    evtSource.onmessage = e => {
      const log = document.getElementById('event-log');
      const line = document.createElement('div');
      line.className = 'event-line';
      line.textContent = new Date().toISOString().slice(11,23) + '  ' + e.data;
      log.prepend(line);
      while (log.childElementCount > 100) log.removeChild(log.lastChild);
    };
    evtSource.onerror = () => {};

    loadSagas();
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# FastAPI app factory
# ---------------------------------------------------------------------------


def create_app(registered_sagas: list[str] | None = None) -> FastAPI:
    """
    Create and return the FastAPI visualization app.

    Parameters
    ----------
    registered_sagas:
        Optional list of ``"module:ClassName"`` strings to pre-register. When
        empty or omitted, the ``/api/v1/sagas`` endpoint lists nothing — clients
        can still pass ``?saga=module:Class`` to the diagram endpoint.
    """
    app = FastAPI(title="sagaz Visualization", version="1.0.0")
    _registered = list(registered_sagas or [])

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> str:
        return _DASHBOARD_HTML

    @app.get("/api/v1/sagas")
    async def list_sagas() -> JSONResponse:
        return JSONResponse({"sagas": _registered})

    @app.get("/api/v1/diagram")
    async def get_diagram(saga: str, direction: str = "TB") -> JSONResponse:
        """Return a Mermaid diagram string for the given saga import path."""
        try:
            cls = _discover_saga_cls(saga)
        except (ValueError, ModuleNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            instance = await _build_saga_instance(cls)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Build failed: {exc}") from exc

        if not hasattr(instance, "to_mermaid"):
            raise HTTPException(
                status_code=422, detail=f"{cls.__name__} has no to_mermaid() method"
            )

        try:
            diagram = instance.to_mermaid(direction=direction)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Diagram generation failed: {exc}"
            ) from exc

        return JSONResponse({"saga": saga, "direction": direction, "diagram": diagram})

    @app.get("/api/v1/live")
    async def sse_live() -> EventSourceResponse:
        """Server-Sent Events stream of saga execution events."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        _EVENT_QUEUES.append(q)

        async def _generator() -> AsyncGenerator[dict, None]:
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield {"data": str(event)}
                    except TimeoutError:
                        yield {"data": "ping"}
            finally:
                _EVENT_QUEUES.remove(q)

        return EventSourceResponse(_generator())

    return app


def run_server(
    app: FastAPI | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    registered_sagas: list[str] | None = None,
) -> None:
    """
    Start the uvicorn server (blocking).

    Parameters
    ----------
    app:
        FastAPI app instance.  Created via ``create_app()`` if *None*.
    host:
        Bind address.
    port:
        Port number.
    registered_sagas:
        Passed to ``create_app()`` when *app* is *None*.
    """
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        msg = "uvicorn is required to run the visualization server."
        raise ImportError(msg) from exc

    if app is None:
        app = create_app(registered_sagas)

    uvicorn.run(app, host=host, port=port)
