# Sagaz Architecture Documentation

Welcome to the Sagaz architecture documentation. This directory contains all architectural decisions, design documents, and technical deep-dives for the saga pattern implementation.

---

## 📚 Documentation Index

### Core Architecture

| Document | Description |
|----------|-------------|
| [**overview.md**](overview.md) | High-level architecture overview, component interactions, and system design |
| [**components.md**](components.md) | Detailed component descriptions and responsibilities |
| [**dataflow.md**](dataflow.md) | Event and data flow patterns through the system |
| [**decisions.md**](decisions.md) | Architecture decision summary with links to full ADRs |
| [**adr-roadmap-dependencies.md**](adr-roadmap-dependencies.md) | ⭐ **ADR implementation roadmap and dependency matrix** |

---

### 📋 Architecture Decision Records (ADRs)

Full decision records with context, rationale, and consequences.

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-011](adr/adr-011-cdc-support.md) | CDC (Change Data Capture) Support | Proposed |
| [ADR-012](adr/adr-012-synchronous-orchestration-model.md) | Synchronous Orchestration Model | Accepted |
| [ADR-013](adr/adr-013-fluss-iceberg-analytics.md) | Fluss + Iceberg Analytics | Proposed |
| [ADR-014](adr/adr-014-schema-registry.md) | Schema Registry Integration | Proposed |
| [ADR-015](adr/adr-015-unified-saga-api.md) | Unified Saga API | Accepted |
| [ADR-016](adr/adr-016-unified-storage-layer.md) | Unified Storage Layer | Accepted |
| [ADR-017](adr/adr-017-chaos-engineering.md) | Chaos Engineering Support | Proposed |
| [ADR-018](adr/adr-018-saga-versioning.md) | Saga Versioning | Proposed |
| [ADR-019](adr/adr-019-dry-run-mode.md) | Dry Run Mode | Proposed |
| [ADR-020](adr/adr-020-multi-tenancy.md) | Multi-Tenancy Support | Proposed |
| [ADR-021](adr/adr-021-lightweight-context-streaming.md) | Lightweight Context Streaming | Proposed |
| [ADR-022](adr/adr-022-compensation-result-passing.md) | Compensation Result Passing | Accepted |
| [ADR-023](adr/adr-023-pivot-irreversible-steps.md) | Pivot/Irreversible Steps | Proposed |
| [ADR-024](adr/adr-024-saga-replay.md) | Saga Replay & Time-Travel | Proposed |
| [ADR-025](adr/adr-025-event-driven-triggers.md) | Event-Driven Triggers | Proposed |
| [ADR-026](adr/adr-026-industry-examples-expansion.md) | Industry Examples Expansion | Proposed |

➡️ See [adr/README.md](adr/README.md) for ADR format and guidelines.

---

### 🛠️ Implementation Plans

Detailed implementation plans for approved architectural decisions.

| Plan | Related ADR | Status |
|------|-------------|--------|
| [Unified Storage](implementation-plans/unified-storage-implementation-plan.md) | ADR-016 | Planned |
| [Scalable Deployment](implementation-plans/scalable-deployment-plan.md) | - | Reference |
| [HA PostgreSQL](implementation-plans/ha-postgres-implementation.md) | - | Implemented |
| [Industry Examples](industry-examples-implementation-plan.md) | ADR-026 | Proposed |

➡️ See [implementation-plans/README.md](implementation-plans/README.md) for plan format.

---

### 🔬 Technical Deep-Dives

In-depth technical explorations of complex topics.

| Document | Description |
|----------|-------------|
| [Compensation Graph](deep-dives/compensation-graph-deep-dive.md) | Deep-dive into DAG-based compensation ordering |

---

### 🔮 Future Designs

Proposed designs for future versions and features.

| Document | Target Version | Description |
|----------|----------------|-------------|
| [Distributed Saga Support](future/design-distributed-saga-support.md) | v2.0 | Multi-service saga orchestration via message broker |
| [Fluss Analytics](future/fluss-analytics.md) | v2.0 | Real-time analytics with Apache Fluss + Iceberg |

---

### 📊 Diagrams

Visual architecture diagrams.

| Diagram | Description |
|---------|-------------|
| [diagrams/](diagrams/) | Mermaid and other architecture diagrams |

---

### 📦 Archive

Historical documents for reference.

| Document | Description |
|----------|-------------|
| [Resources Reorganization](archive/resources-reorganization-summary.md) | v1.1.0 resource folder migration notes |

---

## 🗺️ Quick Navigation

**New to Sagaz?** Start with:
1. [overview.md](overview.md) - Understand the architecture
2. [components.md](components.md) - Learn the components
3. [decisions.md](decisions.md) - See why decisions were made

**Implementing a feature?** Check:
1. Relevant ADR in [adr/](adr/)
2. Implementation plan in [implementation-plans/](implementation-plans/)

**Deep technical questions?** See:
1. [deep-dives/](deep-dives/) for detailed explorations

---

## 📝 Contributing

When adding architecture documentation:

1. **New decision?** → Create an ADR in `adr/adr-NNN-title.md`
2. **Implementation details?** → Add to `implementation-plans/`
3. **Technical deep-dive?** → Add to `deep-dives/`
4. **Future feature design?** → Add to `future/`
5. **Completed/historical?** → Consider `archive/`

Always update this README and [decisions.md](decisions.md) when adding new ADRs.

---

## 📚 Related Documentation

- [Main README](../../README.md) - Project overview and quick start
- [Examples](../../examples/README.md) - Usage examples by domain
- [API Reference](../api/) - API documentation
- [Guides](../guides/) - How-to guides and tutorials

---

**Questions?** Open an issue: https://github.com/brunolnetto/sagaz/issues
