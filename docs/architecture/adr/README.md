# Architecture Decision Records

**Last Updated**: 2026-01-05

This directory contains Architecture Decision Records (ADRs) documenting significant technical decisions for Sagaz.

---

## ✅ Accepted (Implemented)

| ADR | Title | Version | Date |
|-----|-------|---------|------|
| [ADR-012](adr-012-synchronous-orchestration-model.md) | Synchronous Orchestration Model | v1.0.0 | 2024-12 |
| [ADR-015](adr-015-unified-saga-api.md) | Unified Saga API | v1.0.3 | 2024-12 |

---

## 📋 Proposed (2026 Roadmap)

### High Priority

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|
| [ADR-011](adr-011-cdc-support.md) | CDC Support | Q2 2026 | Change Data Capture with Debezium for 50K+ events/sec |
| [ADR-020](adr-020-multi-tenancy.md) | Multi-Tenancy | Q4 2026 | Tenant isolation, quotas, and compliance |

### Medium Priority

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|
| [ADR-013](adr-013-fluss-iceberg-analytics.md) | Fluss Analytics | Q3 2026 | Real-time + historical analytics with Iceberg |
| [ADR-016](adr-016-saga-replay.md) | Saga Replay | Q3 2026 | Replay failed sagas and time-travel queries |
| [ADR-019](adr-019-dry-run-mode.md) | Dry-Run Mode | Q2 2026 | Validate and preview saga execution |
| [ADR-023](adr-023-pivot-irreversible-steps.md) | Pivot Steps | Q3 2026 | Irreversible steps and forward recovery |

### Low Priority / Future

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|
| [ADR-021](adr-021-lightweight-context-streaming.md) | Context Streaming | 2027+ | Reference-based context and streaming between steps |
| [ADR-017](adr-017-chaos-engineering.md) | Chaos Engineering | TBD | Fault injection and resilience testing |
| [ADR-018](adr-018-saga-versioning.md) | Saga Versioning | TBD | Version management for saga definitions |
| [ADR-022](adr-022-compensation-result-passing.md) | Compensation Results | TBD | Pass results between compensation steps |

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
