# ADR-039: Gradio-Based Saga Asset Monitor

## Status
Proposed (2026-04-24)

## Context
As the Sagaz ecosystem grows, developers need a zero-config, visual way to monitor saga assets (states, contexts, and dependency graphs) during development. While Grafana/Prometheus provide production-grade monitoring, they require a full infrastructure stack (database, metrics exporter, Grafana server).

We need a lightweight, Python-native monitoring interface that can:
1. Visualize the current state of any saga instance.
2. Display the dependency graph (DAG) of a saga.
3. Inspect the `SagaContext` in real-time.
4. Run as a standalone tool or integrated into a dev server.

## Decision
We will implement a monitoring UI using **Gradio**. Gradio provides a rapid way to build interactive UIs in Python with minimal boilerplate, making it ideal for developer-centric tooling.

The monitor will be accessible via:
1. A new CLI command: `sagaz monitor --ui gradio`.
2. A programmatic API: `sagaz.visualization.gradio.launch()`.

### Technical Details
- **Backend**: Uses existing `SagaStorage` interfaces to fetch data.
- **Visualization**: Integrates with the existing Mermaid-based visualization engine.
- **Portability**: Will be packaged as an optional extra `pip install sagaz[monitor]`.
- **Interface**:
    - Sidebar for saga instance selection.
    - Central panel for Mermaid graph rendering.
    - Data tables for context inspection.
    - Real-time refresh using Gradio's state management.

## Consequences
- **Positive**: Simplifies local development and debugging of complex DAG sagas.
- **Positive**: Low maintenance overhead compared to building a custom React/Vue frontend.
- **Negative**: Adds a dependency on Gradio for those who want the UI.
- **Neutral**: This tool is strictly for development/introspection and does not replace the production Grafana dashboard.
