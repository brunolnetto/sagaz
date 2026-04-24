# Architecture Decision Records

**Last Updated**: 2026-04-11

This directory contains Architecture Decision Records (ADRs) documenting significant technical decisions for Sagaz.

---

## ✅ Accepted (Implemented)

| ADR | Title | Version | Date |
|-----|-------|---------|------|
| [ADR-012](adr-012-synchronous-orchestration-model.md) | Synchronous Orchestration Model | v1.0.0 | 2024-12 |
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
| [ADR-030](adr-030-dry-run-parallel-analysis.md) | Dry-Run Parallel Analysis | v1.3.0 | 2026-01 |
| [ADR-031](adr-031-dry-run-simplification.md) | Dry-Run Simplification | v1.3.0 | 2026-01 |
| [ADR-032](adr-032-cli-command-organization.md) | CLI Command Organization | v1.3.0 | 2026-01 |
| [ADR-036](adr-036-lifecycle-hooks-observers.md) | Lifecycle Hooks & Observers | v1.3.0 | 2026-04 |
| [ADR-037](adr-037-compliance-data-governance.md) | Compliance & Data Governance | v2.1.0 | 2026-04 |

---

## 📋 Proposed (Future Releases)

### High Priority

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|
| [ADR-029](adr-029-saga-choreography.md) | Saga Choreography Pattern | v2.2.0 | Event-driven distributed coordination |
| [ADR-039](adr-039-gradio-ui-monitor.md) | Gradio-Based Saga Asset Monitor | v1.7.0 | Python-native monitoring UI for development |

### Medium / Low Priority

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|

### Low Priority / Future

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|
| [ADR-011](adr-011-cdc-support.md) | CDC Support | v2.1.0 | Change Data Capture with Debezium for 50K+ events/sec |
| [ADR-013](adr-013-fluss-iceberg-analytics.md) | Fluss Analytics | v2.0.0 | Real-time + historical analytics with Iceberg |
| [ADR-033](adr-033-event-sourcing-integration.md) | Event Sourcing Integration | v2.3.0 | Opt-in event-sourced storage strategy for full audit trail |
| [ADR-034](adr-034-multi-region-coordination.md) | Multi-Region Coordination | v2.3.0 | Cross-region step routing, data residency, and failover |
| [ADR-035](adr-035-saga-visualization-ui.md) | Saga Visualization UI | v2.0.0 | Browser-based live saga monitoring dashboard |

---

## ⏸️ Deferred

| ADR | Title | Reason |
|-----|-------|--------|
| [ADR-014](adr-014-schema-registry.md) | Schema Registry | Optional for single-language setups, needed for polyglot/multi-team |

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
