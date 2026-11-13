# Saga Visualization UI

`sagaz monitor` starts a small, self-contained web dashboard that shows Saga runs
as they happen. You don't need to deploy Grafana, Prometheus or a database for it.
It implements [ADR-035](../architecture/adr/adr-035-saga-visualization-ui.md).

## Install

```bash
pip install "sagaz[visualization]"   # or the alias: sagaz[monitor]
```

The extra installs `fastapi`, `uvicorn` and `sse-starlette`. The core `sagaz`
package does not depend on them.

## Quick start

1. Start the monitor:

    ```bash
    sagaz monitor            # http://127.0.0.1:7070, opens a browser tab
    sagaz monitor --port 8080 --no-browser
    ```

    On startup it prints the two environment variables that workers need:

    ```text
    export SAGAZ_VISUALIZATION_URL=http://127.0.0.1:7070
    export SAGAZ_VISUALIZATION_TOKEN=<generated token>
    ```

2. Register the listener on the Sagas you want to see (in the worker process
   where those variables are set):

    ```python
    from sagaz import Saga, action
    from sagaz.visualization import VisualizationSagaListener

    class OrderSaga(Saga):
        saga_name = "OrderSaga"
        listeners = [VisualizationSagaListener.from_env()]

        @action("charge")
        async def charge(self, ctx):
            ...
    ```

Event delivery is best-effort. Each event is one HTTP POST with a 0.5 s
timeout. If the monitor is down, the Saga listener dispatcher logs the failure
and the Saga carries on running.

## Dashboard views

| View | URL hash | Shows |
|------|----------|-------|
| Dashboard | `#/dashboard` | Run totals, success rate, p95 duration, counts per Saga |
| Runs | `#/runs` | Paginated run list with status and Saga-name filters |
| Run detail | `#/runs/<saga_id>` | Runtime diagram plus step timeline (durations, compensation, error type) |
| Live | `#/live` | Raw event feed from the SSE stream |
| Steps | `#/steps` | Executions, failures, compensations and average duration per step |

The runtime diagram colours each step by state:

- green: completed
- red: failed
- amber: compensating
- indigo: compensated
- blue: running

The page is one HTML file with vanilla JS and no build step. Mermaid loads from
`cdn.jsdelivr.net` (version pinned). If that CDN can't be reached, the page shows
the diagram source as text and everything else keeps working.

## HTTP API

All routes are under `/api/v1`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/runs?status=&saga_name=&limit=50&offset=0` | Runs, newest first. `status` ∈ `running`, `compensating`, `completed`, `failed`; `limit` ≤ 500. Returns `{items, total, limit, offset}` |
| `GET` | `/runs/{saga_id}` | Full run: steps, timings, error type, last 200 events |
| `GET` | `/runs/{saga_id}/diagram?direction=LR` | Runtime-state Mermaid diagram |
| `GET` | `/runs/{saga_id}/events` | SSE stream for one run. Sends a `snapshot` event first if the run is already known, then only that run's events |
| `GET` | `/live` | SSE stream of every event |
| `GET` | `/metrics/summary` | Status counts, success rate, duration avg/p50/p95/max, per-Saga and per-step aggregates |
| `GET` | `/sagas` | Saga classes registered with `create_app(registered_sagas=...)` |
| `GET` | `/diagram?saga=module:Class` | Static definition diagram from the class's `to_mermaid()` |
| `POST` | `/events` | Event ingestion. Requires a bearer token |

SSE streams send a keep-alive ping every 15 s. Each subscriber has a bounded
queue of 100 events, and at most 100 subscribers can connect at once. If a slow
client falls behind, the oldest queued events are dropped and the client gets an
`event: gap` message with `{"dropped": N}`.

### Event schema

`POST /api/v1/events` accepts only these fields; any other field is rejected
with `422`:

```json
{
  "event_id": "uuid",
  "event_type": "saga.started | saga.completed | saga.failed | step.started | step.succeeded | step.failed | step.compensation_started | step.compensated",
  "saga_id": "≤256 chars",
  "saga_name": "≤256 chars",
  "step_name": "≤256 chars or null",
  "error_type": "exception class name or null",
  "occurred_at": "ISO-8601 timestamp"
}
```

Saga context, step results and exception messages are never sent, so the
dashboard cannot leak business data. Events with a duplicate `event_id` are
acknowledged with `"duplicate": true` and are not re-broadcast.

## Data retention

Run state is held **in memory by the monitor process**:

- The monitor keeps the last 1,000 runs. When it is full, finished runs are evicted before running ones.
- It remembers the last 10,000 event IDs for de-duplication.
- Restarting the monitor clears the history.
- Each monitor process keeps its own state; replicas do not share it.

Use the [Prometheus/Grafana stack](OBSERVABILITY_REFERENCE.md) (`sagaz monitor --ui grafana`)
when you need long-term history or several replicas.

## Security: authentication and CORS

| Surface | Policy |
|---------|--------|
| Event ingestion (`POST /events`) | Requires `Authorization: Bearer <token>`, compared in constant time. Ingestion is **disabled** (`503`) unless a token is configured. `sagaz monitor` reads `SAGAZ_VISUALIZATION_TOKEN`, or generates a random 256-bit token per process |
| Read endpoints (dashboard, REST, SSE) | **Unauthenticated.** Intended for local use only |
| Bind address | Defaults to `127.0.0.1`. Any other address requires `--unsafe-expose`, and the CLI prints a warning |
| CORS | **No CORS middleware is installed**, so browsers allow same-origin access only. Pages on other origins cannot read the API, and their cross-origin `POST /events` (which sends a custom `Authorization` header) fails the preflight. There is no `SAGAZ_VIZ_ALLOWED_ORIGINS` setting |

Recommended deployment patterns:

- **Local development**: use the defaults (loopback bind, generated token).
- **Shared or remote access**: keep the bind on loopback and use an SSH tunnel
  (`ssh -L 7070:127.0.0.1:7070 host`). Alternatively, put the monitor behind a
  reverse proxy that handles authentication (OAuth2 proxy, mTLS, basic auth) and
  bind with `--unsafe-expose`. Use `--advertise-host` to set the URL printed for
  workers.
- **Workers on other hosts**: set the same `SAGAZ_VISUALIZATION_TOKEN` on the
  monitor and on every worker, and use HTTPS when traffic crosses untrusted
  networks.

## Embedding the API

```python
from sagaz.visualization.server import create_app, run_server

app = create_app(
    registered_sagas=["myapp.sagas:OrderSaga"],
    event_token="...",
    max_runs=5_000,
    event_queue_size=100,
    max_sse_subscribers=100,
)
run_server(app, host="127.0.0.1", port=7070)
```
