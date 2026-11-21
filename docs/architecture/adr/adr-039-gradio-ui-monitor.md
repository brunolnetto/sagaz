# ADR-039: Gradio-Based Saga Asset Monitor

## Status

Accepted (2026-11-20). Revised for the unified saga log and implemented for v2.3.0
([#501](https://github.com/brunolnetto/sagaz/issues/501)). The first version (2026-04-24)
predated the unified saga log (ADR-041) and the `sagaz monitor` web dashboard (ADR-035).

## Context

Developers need a zero-config, visual way to inspect saga **assets** during development:
what a transaction did, which steps ran and how they ended, which events a choreography
exchanged, and what the context held.

Two tools exist, and neither shows persisted state:

- **ADR-035, `sagaz monitor --ui web`:** a browser dashboard fed live by a listener over
  HTTP. Its run records live in the server process and are lost when it stops. It does
  not read storage.
- **Grafana / Prometheus and the Fluss/Iceberg analytics (ADR-013):** aggregates for
  production, not single transactions.

Since v2.1.0, the unified saga log (ADR-041) holds everything worth inspecting for both
coordination styles:

- **Transactions:** coordination, flow, status, initiator and context;
- **Activities:** steps and handled events, with status, attempts, results, errors and
  durations;
- **Events:** the append-only log, with causation links.

Older deployments keep sagas in a `SagaStorage`.

## Decision

Implement a **Gradio** app that reads persisted saga state and runs locally, with no
infrastructure beyond the store.

### Entry points

- **CLI:** `sagaz monitor --ui gradio --saga-log URL`, or `--storage-url URL` for a
  classic-layout saga storage.
- **Python:** `sagaz.visualization.gradio.launch(saga_log=..., storage=...)`, and
  `build_app(...)` for embedding.
- **Package:** an extra of its own, `pip install 'sagaz[gradio]'`. `sagaz[monitor]`
  stays the ADR-035 web dashboard.

### Views

- **Transactions:** a table with filters for coordination, flow, status and tenant.
- **Detail of a selected transaction:**
  - a **Mermaid diagram**, rendered by Gradio's Markdown component, which bundles
    mermaid.js and works offline:
    - **orchestrated:** the steps in start order, colored by status;
    - **choreographed:** the events as a causation graph, labelled by participant;
  - the **steps** (activities) with status, attempt, duration and error;
  - the **events** with kind, source and causation;
  - the **context** as JSON.
- **Classic storage:** a saga storage shows its sagas, their steps and context the same
  way.

### Architecture

- **Data layer** (`sagaz.visualization.gradio._data`): async functions over
  `SagaLogStore` and `SagaStorage` that return plain rows and Mermaid text. It has no
  Gradio import and is tested without a browser.
- **UI layer** (`_app`): builds `gr.Blocks` from the data layer. Its async handlers run
  on Gradio's event loop, where the store is opened lazily.
- **Read-only:** the monitor never writes.

## Consequences

- **Positive:** persisted transactions of both coordination styles can be inspected
  without Grafana or a database client, and with no frontend code to maintain.
- **Positive:** the data layer can back other views later, such as the web dashboard.
- **Negative:** the `gradio` extra is a large dependency, and only for those who want
  the UI.
- **Neutral:**
  - the monitor is for development and introspection, and is unauthenticated, like
    ADR-035;
  - `--host` binds to loopback by default, and a non-loopback address needs
    `--unsafe-expose`.
