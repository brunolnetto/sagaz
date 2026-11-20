# Architecture Decision Records

**Last Updated**: 2026-11-20

This directory contains Architecture Decision Records (ADRs) documenting significant technical decisions for Sagaz.

---

## ✅ Accepted (Implemented)

| ADR | Title | Version | Date |
|-----|-------|---------|------|
| [ADR-011](adr-011-cdc-support.md) | CDC Support (PostgreSQL logical replication, Debezium) | v1.9.0 | 2026-11 |
| [ADR-012](adr-012-synchronous-orchestration-model.md) | Synchronous Orchestration Model | v1.0.0 | 2024-12 |
| [ADR-013](adr-013-fluss-iceberg-analytics.md) | Fluss + Iceberg Analytics on the Unified Saga Log | v2.2.0 | 2026-11 |
| [ADR-015](adr-015-unified-saga-api.md) | Unified Saga API | v1.0.3 | 2024-12 |
| [ADR-016](adr-016-unified-storage-layer.md) | Unified Storage Layer | v1.2.0 | 2026-01 |
| [ADR-017](adr-017-chaos-engineering.md) | Chaos Engineering | v1.4.0 | 2026-04 |
| [ADR-018](adr-018-saga-versioning.md) | Saga Versioning | v2.0.0 | 2026-04 |
| [ADR-019](adr-019-dry-run-mode.md) | Dry-Run Mode | v1.3.0 | 2026-01 |
| [ADR-020](adr-020-multi-tenancy.md) | Multi-Tenancy | v1.4.0 | 2026-04 |
| [ADR-021](adr-021-lightweight-context-streaming.md) | Context Streaming | v1.4.0 | 2026-01 |
| [ADR-022](adr-022-compensation-result-passing.md) | Compensation Result Passing | v1.2.0 | 2026-01 |
| [ADR-023](adr-023-pivot-irreversible-steps.md) | Pivot/Irreversible Steps | v1.3.0 | 2026-01 |
| [ADR-024](adr-024-saga-replay.md) | Saga Replay & Time-Travel | v2.1.0 | 2026-01 |
| [ADR-025](adr-025-event-driven-triggers.md) | Event-Driven Triggers | v1.3.0 | 2026-01 |
| [ADR-026](adr-026-industry-examples-expansion.md) | Industry Examples Expansion | v1.4-1.6 | 2026-01 |
| [ADR-027](adr-027-project-cli.md) | Project CLI | v1.3.0 | 2026-01 |
| [ADR-028](adr-028-framework-integration.md) | Framework Integration (FastAPI/Django/Flask) | v1.3.0 | 2026-01 |
| [ADR-029](adr-029-saga-choreography.md) | Saga Choreography Pattern | v1.10.0 | 2026-11 |
| [ADR-030](adr-030-dry-run-parallel-analysis.md) | Dry-Run Parallel Analysis | v1.3.0 | 2026-01 |
| [ADR-031](adr-031-dry-run-simplification.md) | Dry-Run Simplification | v1.3.0 | 2026-01 |
| [ADR-032](adr-032-cli-command-organization.md) | CLI Command Organization | v1.3.0 | 2026-01 |
| [ADR-033](adr-033-event-sourcing-integration.md) | Event Sourcing Integration | v2.0.0 | 2026-11 |
| [ADR-034](adr-034-multi-region-coordination.md) | Multi-Region Coordination | v2.0.0 | 2026-11 |
| [ADR-035](adr-035-saga-visualization-ui.md) | Saga Visualization UI (`sagaz monitor`) | v1.8.0 | 2026-11 |
| [ADR-036](adr-036-lifecycle-hooks-observers.md) | Lifecycle Hooks & Observers | v1.3.0 | 2026-04 |
| [ADR-037](adr-037-compliance-data-governance.md) | Compliance & Data Governance | v2.1.0 | 2026-04 |
| [ADR-038](adr-038-dlq-observability.md) | DLQ Observability (error classification, replay validation) | v1.3.0 | 2026-04 |
| [ADR-039](adr-039-gradio-ui-monitor.md) | Gradio Saga Asset Monitor | v2.3.0 | 2026-11 |
| [ADR-040](adr-040-statechart-saga-lifecycle.md) | StateChart Saga Lifecycle (Phase 1) | v1.7.0 | 2026-11 |
| [ADR-041](adr-041-unified-saga-log.md) | Unified Saga Log | v2.1.0 | 2026-11 |
| [ADR-042](adr-042-environment-variable-management.md) | Environment Variable Management (`.env`) | v1.1.1 | 2026-01 |
| [ADR-043](adr-043-sqldim-analytics-pipeline.md) | sqldim Analytics Pipeline | v1.8.0 | 2026-11 |

ADR-040 covers phase 1 of the StateChart migration. Phase 2 (compound and parallel step
regions, [#190](https://github.com/brunolnetto/sagaz/issues/190)) is in the backlog until
its recovery, compensation and migration semantics are reviewed.

---

## 📋 Proposed (Future Releases)

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|
| [ADR-014](adr-014-schema-registry.md) | Schema Registry | v2.3.0 | Schema registry for saga events: Avro/JSON Schema, Confluent-compatible registries ([#502](https://github.com/brunolnetto/sagaz/issues/502)); to be revised for the unified saga log |

---

## ADR Status Definitions

| Status | Description |
|--------|-------------|
| **Proposed** | Under discussion, not yet approved |
| **Accepted** | Approved and implemented |
| **Deferred** | Postponed for future consideration |
| **Superseded** | Replaced by a newer ADR |
| **Rejected** | Considered and rejected |

---

## Creating New ADRs

### Naming Convention

```
adr-NNN-descriptive-name.md
```

Examples:
- `adr-024-rate-limiting.md`
- `adr-025-event-sourcing.md`

### Template Structure

```markdown
# ADR-NNN: Title

## Status

**Proposed** | Date: YYYY-MM-DD | Priority: High/Medium/Low | Target: QN YYYY

## Context

[Why is this decision needed?]

## Decision

[What was decided?]

## Consequences

### Positive
[Benefits]

### Negative
[Drawbacks]

## Alternatives Considered

[Other options evaluated]

## References

[Related documents, external links]
```

---

## See Also

- [Roadmap](../../ROADMAP.md) - Development timeline
- [Architecture Overview](../overview.md) - System design
- [Architecture Decisions Summary](../decisions.md) - High-level decision log
