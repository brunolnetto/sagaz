# Architecture Decision Records

**Last Updated**: 2026-01-10

This directory contains Architecture Decision Records (ADRs) documenting significant technical decisions for Sagaz.

---

## ✅ Accepted (Implemented)

| ADR | Title | Version | Date |
|-----|-------|---------|------|
| [ADR-012](adr-012-synchronous-orchestration-model.md) | Synchronous Orchestration Model | v1.0.0 | 2024-12 |
| [ADR-015](adr-015-unified-saga-api.md) | Unified Saga API | v1.0.3 | 2024-12 |
| [ADR-016](adr-016-unified-storage-layer.md) | Unified Storage Layer | v1.2.0 | 2026-01 |
| [ADR-021](adr-021-lightweight-context-streaming.md) | Context Streaming | v1.4.0 | 2026-01 |
| [ADR-022](adr-022-compensation-result-passing.md) | Compensation Result Passing | v1.2.0 | 2026-01 |
| [ADR-023](adr-023-pivot-irreversible-steps.md) | Pivot/Irreversible Steps | v1.3.0 | 2026-01 |
| [ADR-024](adr-024-saga-replay.md) | Saga Replay & Time-Travel | v2.1.0 | 2026-01 |
| [ADR-025](adr-025-event-driven-triggers.md) | Event-Driven Triggers | v1.3.0 | 2026-01 |
| [ADR-026](adr-026-industry-examples-expansion.md) | Industry Examples Expansion | v1.4-1.6 | 2026-01 |
| [ADR-027](adr-027-project-cli.md) | Project CLI | v1.3.0 | 2026-01 |
| [ADR-028](adr-028-framework-integration.md) | Framework Integration | v1.3.0 | 2026-01 |

---

## 📋 Proposed (Future Releases)

### High Priority

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|
| [ADR-029](adr-029-saga-choreography.md) | Saga Choreography Pattern | v2.2.0 | Event-driven distributed coordination (10-15 weeks) |
| [ADR-020](adr-020-multi-tenancy.md) | Multi-Tenancy | v2.0.0 | Tenant isolation, quotas, and compliance |

### Medium Priority

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|
| [ADR-018](adr-018-saga-versioning.md) | Saga Versioning | v2.0.0 | Version management for saga definitions |
| [ADR-019](adr-019-dry-run-mode.md) | Dry-Run Mode | v1.3.0 | Validate and preview saga execution |

### Low Priority / Future

| ADR | Title | Target | Description |
|-----|-------|--------|-------------|
| [ADR-011](adr-011-cdc-support.md) | CDC Support | Future | Change Data Capture with Debezium for 50K+ events/sec |
| [ADR-013](adr-013-fluss-iceberg-analytics.md) | Fluss Analytics | Future | Real-time + historical analytics with Iceberg |
| [ADR-017](adr-017-chaos-engineering.md) | Chaos Engineering | TBD | Fault injection and resilience testing |

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
