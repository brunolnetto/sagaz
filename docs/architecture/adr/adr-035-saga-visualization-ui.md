# ADR-035: Saga Visualization UI

## Status

**Proposed** | Date: 2026-04-07 | Priority: Medium | Target: v2.2.0

**Implementation Status:**
- ⚪ Phase 1: Backend API for Visualization Data (Not Started)
- ⚪ Phase 2: Mermaid & Static Export Enhancements (Not Started)
- ⚪ Phase 3: Interactive Web Dashboard (Not Started)
- ⚪ Phase 4: Live Execution Monitoring (Not Started)
- ⚪ Phase 5: Integration with Observability Stack (Not Started)

## Dependencies

**Prerequisites**:
- ADR-027: Project CLI (CLI backend serves visualization data)
- ADR-024: Saga Replay & Time-Travel (visualization shows historical runs)

**Synergies** (Optional):
- ADR-013: Fluss Analytics (feed real-time events into visualization layer)
- ADR-033: Event Sourcing (event log drives timeline view in UI)
- ADR-021: Lightweight Context Streaming (stream step results to UI in real-time)
- ADR-034: Multi-Region Coordination (map view showing per-region step execution)

**Roadmap**: **Phase 6 (v2.2.0)** — Developer Experience

## Context

Saga definitions are expressed as Python code. The existing `sagaz visualize` command generates static Mermaid diagrams from class definitions, but there is no runtime visualization of:

- Which step a live saga is currently executing
- How long each step took in a completed run
- Which step triggered compensation and why
- Aggregate statistics across thousands of saga runs
- Comparisons across saga versions

### Current Capabilities

| Capability | Status |
|-----------|--------|
| Static Mermaid diagram from class | ✅ `sagaz visualize` (ADR-027/032) |
| Mermaid diagram embedded in logs | ✅ `sagaz saga inspect <id>` |
| Step execution state in terminal | ✅ Rich table via `sagaz status` |
| Run-time browser-based UI | ❌ Not available |
| Live step progress | ❌ Not available |
| Historical run comparison | ❌ Not available |
| Aggregate success/failure heatmap | ❌ Not available |

### Target Users

| Persona | Need |
|---------|------|
| **Developer** | Debug a failing saga; see exactly where and why it failed |
| **Operator** | Monitor saga health; get alerted on compensation spikes |
| **Product Manager** | Understand business process throughput and SLA compliance |
| **Compliance Officer** | Audit trail with timeline view per saga run |

---

## Decision

Implement a **Saga Visualization UI** as a lightweight web dashboard served by the `sagaz` CLI. It provides both static (class-level) and dynamic (runtime) saga visualization using the existing Mermaid backend for diagrams and a minimal JavaScript frontend for interactivity.

### Design Principles

1. **Zero dependencies for basic use**: Dashboard is served by `sagaz monitor` using a self-contained HTML file with embedded JS (Mermaid + vanilla JS). No Node.js build step required.
2. **API-first**: All data exposed via a REST/SSE API so third-party dashboards (Grafana, custom) can consume it.
3. **Progressive enhancement**: Static Mermaid always works; live updates via Server-Sent Events (SSE) are additive.
4. **Read-only UI**: The dashboard displays and explores state; mutations go through the CLI or application code.

---

## Proposed Architecture

### Backend API

```python
# sagaz/visualization/server.py  (served by: sagaz monitor)
from fastapi import FastAPI
from sse_starlette.sse import EventSourceResponse

app = FastAPI(title="Sagaz Visualization API")

@app.get("/api/sagas")
async def list_sagas(status: str | None = None, limit: int = 50):
    """Return paginated list of saga runs."""

@app.get("/api/sagas/{saga_id}")
async def get_saga(saga_id: str):
    """Return full saga run details including step history."""

@app.get("/api/sagas/{saga_id}/diagram")
async def get_diagram(saga_id: str, format: str = "mermaid"):
    """Return Mermaid diagram for a saga (class definition or runtime state)."""

@app.get("/api/sagas/{saga_id}/events")
async def stream_saga_events(saga_id: str):
    """SSE stream of step state changes for live monitoring."""
    return EventSourceResponse(saga_event_generator(saga_id))

@app.get("/api/metrics/summary")
async def metrics_summary():
    """Aggregate statistics: success rate, avg duration, compensation rate."""
```

### CLI Integration

```bash
sagaz monitor               # Open browser to http://localhost:7070
sagaz monitor --port 8080   # Custom port
sagaz monitor --no-browser  # Start server only
```

### Frontend Structure

The dashboard is a single `index.html` delivered from `sagaz/visualization/static/` with:

```
sagaz/visualization/static/
├── index.html          # Self-contained SPA (mermaid.min.js inlined)
├── dashboard.js        # Vanilla JS: fetch API, SSE subscription, render
└── style.css           # Minimal CSS; dark/light mode via CSS variables
```

### UI Pages

| View | Description |
|------|-------------|
| **Dashboard** | Summary cards: total runs, success/failure rates, avg duration, compensation rate |
| **Saga List** | Filterable table of all saga runs with status badges and duration |
| **Saga Detail** | Mermaid diagram with step colours (green=done, red=failed, yellow=compensating), timeline, step durations |
| **Live Monitor** | Real-time step progress for a running saga via SSE |
| **Step Explorer** | Click a step to see input context, output, duration, and error (if any) |
| **Compare Runs** | Side-by-side step durations for two saga runs of the same class |

### Diagram State Annotation

The existing Mermaid generator is extended to colour-code nodes based on runtime state:

```python
# sagaz/visualization/diagram.py
def saga_runtime_diagram(run: SagaRun) -> str:
    lines = [generate_base_diagram(run.saga_class)]
    for step in run.steps:
        colour = {
            "completed": "fill:#22c55e",
            "failed": "fill:#ef4444",
            "compensating": "fill:#f59e0b",
            "compensated": "fill:#6366f1",
            "pending": "fill:#94a3b8",
        }[step.status]
        lines.append(f"  style {step.name} {colour}")
    return "\n".join(lines)
```

---

## Implementation Phases

### Phase 1: Backend API (1.5 weeks)
- `sagaz/visualization/server.py` — FastAPI app with `/api/sagas`, `/api/sagas/{id}`, `/api/sagas/{id}/diagram` endpoints
- Unit tests for all API endpoints (mock storage)
- Integration test: start server, query list, verify response schema

### Phase 2: Mermaid & Static Export Enhancements (0.5 weeks)
- `saga_runtime_diagram()` in `sagaz/visualization/diagram.py` — colour-coded state
- `sagaz saga inspect <id> --export mermaid/svg/png` CLI flag (PNG via headless Mermaid renderer)
- Tests for colour annotation logic

### Phase 3: Interactive Web Dashboard (2 weeks)
- `index.html` + `dashboard.js` + `style.css` in `sagaz/visualization/static/`
- Dashboard, Saga List, and Saga Detail views
- Mermaid diagram rendered client-side
- `sagaz monitor` command serves the static files + API

### Phase 4: Live Execution Monitoring (1 week)
- SSE endpoint `/api/sagas/{id}/events`
- Dashboard subscribes to SSE; updates step colours in real-time without page reload
- Live Monitor view for active saga runs
- Integration test: saga runs while SSE client is connected; verify all events received

### Phase 5: Integration with Observability Stack (0.5 weeks)
- Grafana data source plugin configuration for the Sagaz API (optional JSON data source)
- Link from Grafana alert → Sagaz UI saga detail view via `external_url`
- `docs/monitoring/visualization-ui.md` setup guide

---

## Consequences

### Positive
- Zero additional infrastructure: dashboard runs in the `sagaz` process
- Static diagrams still work when browser is unavailable (CI/terminal usage)
- Compliance officers get a timeline view without DB access
- Developers diagnose failures without reading raw logs

### Negative
- FastAPI + sse-starlette added as optional dependency (`sagaz[monitor]` extra)
- Frontend has no build step but adds static file management
- SSE connections are persistent; busy deployments need connection pooling

### Mitigation
- `sagaz[monitor]` extra keeps core install lean
- Self-contained HTML keeps the frontend maintenance burden minimal
- Connection limit configurable via `--max-sse-connections`

---

## Acceptance Criteria

- [ ] `sagaz/visualization/server.py` with REST API and SSE endpoint
- [ ] `sagaz monitor` CLI command: starts server and opens browser
- [ ] `saga_runtime_diagram()` colour-codes steps by status
- [ ] Self-contained `index.html` dashboard with Dashboard, List, and Detail views
- [ ] Live Monitor view updates via SSE (no polling)
- [ ] Step Explorer shows input/output/error per step
- [ ] `sagaz[monitor]` extra installs `fastapi` and `sse-starlette`
- [ ] Unit tests for API endpoints (mock storage)
- [ ] Integration test: SSE stream delivers all events for a running saga
- [ ] 90%+ coverage for `sagaz/visualization/`
- [ ] `docs/monitoring/visualization-ui.md` user guide

## Rejected Alternatives

### Grafana-Only Dashboard
Grafana requires a separately deployed server and is not zero-setup. The CLI-served dashboard is the zero-friction option; Grafana integration is additive.

### Streamlit / Dash App
These frameworks add heavy dependencies and a non-standard deployment model. Vanilla JS with Mermaid keeps the footprint minimal.

### Real-Time Push via WebSockets
SSE is simpler (unidirectional, HTTP/1.1 compatible), sufficient for read-only visualization, and more firewall-friendly than WebSockets.
