# ADR-039: Gradio-Based Saga Asset Monitor

## Status
Proposed (2026-04-24) | Priority: High | Target: v1.7.0

## Context
As the Sagaz ecosystem grows, developers need a zero-config, visual way to monitor saga assets (states, contexts, and dependency graphs) during development. ADR-035 previously proposed a custom FastAPI + Vanilla JS dashboard, but we want a more rapid, Python-native solution that fits better into the developer's workflow without building a custom frontend from scratch.

While Grafana/Prometheus provide production-grade monitoring, they require a full infrastructure stack. We need a lightweight, Python-native monitoring interface that can replicate the feature set proposed in ADR-035 but with the ease of Gradio.

## Decision
We will implement a monitoring UI using **Gradio**. This replaces the custom JS frontend from ADR-035 with a Python-defined interface while maintaining all proposed features.

The monitor will be accessible via:
1. A new CLI command: `sagaz monitor --ui gradio`.
2. A programmatic API: `sagaz.visualization.gradio.launch()`.

### Feature Set (Parity with ADR-035)
- **Dashboard Summary**: Cards showing total runs, success/failure rates, avg duration, and compensation rate.
- **Saga Explorer**: A filterable table of all saga runs with status badges and timestamps.
- **Instance Detail**:
    - **Mermaid Graph**: Interactive diagram with status-based colour coding (green=done, red=failed, yellow=compensating).
    - **Timeline View**: Step-by-step execution timeline with durations.
    - **Context Inspector**: Collapsible JSON views for step inputs, outputs, and errors.
- **Live Monitoring**: Automatic refresh of the UI as sagas execute (using Gradio's `every` or state-triggered updates).
- **Comparison View**: Side-by-side comparison of two saga runs (e.g., comparing a successful run vs a failed run).

### Technical Details
- **Backend**: Uses existing `SagaStorage` interfaces (Redis, Postgres, Memory).
- **Visualization**: Integrates with the existing Mermaid-based visualization engine.
- **Portability**: Packaged as an optional extra `pip install sagaz[monitor]`.
- **Gradio Components**:
    - `gr.Dataframe` for saga lists.
    - `gr.HTML` for Mermaid diagram rendering.
    - `gr.JSON` for context inspection.
    - `gr.Plot` or `gr.BarPlot` for basic metrics.

## Consequences
- **Positive**: 100% Python codebase for the UI, facilitating maintenance by the core team.
- **Positive**: Faster implementation of complex interactive features (e.g., filtering, JSON tree exploration).
- **Positive**: Direct integration with the Python debugger and logs.
- **Negative**: Adds a dependency on `gradio` for the monitoring extra.
- **Neutral**: Replaces the custom JS dashboard from ADR-035 as the primary developer tool, though the REST API from ADR-035 may still be implemented for third-party integrations (e.g., Grafana).

## Cascaded Impact & Future Releases
- **v1.7.0**: Initial Gradio UI with Dashboard, List, and Detail views (Phase 1).
- **v1.8.0**: Advanced Live Monitoring and Historical Comparison (Phase 2).
- **v2.0.0+**: Full integration with the production observability stack (ADR-035 Phase 5).

This Gradio implementation will serve as the reference UI, while the REST/SSE API proposed in ADR-035 remains the target for production-grade, headless monitoring integrations.
