# Sagaz Roadmap & Strategy 2026

Active development roadmap for the Sagaz saga pattern library.

> **Updated**: 2026-04-08 | **Version**: 1.1.2 → 2.x

---

## Vision

**"The open-source distributed transaction platform that just works."**

Sagaz competes with AWS Step Functions, Temporal, and Azure Durable Functions by offering:
- ✅ **Exactly-once guarantees** (they don't have this)
- ✅ **Transactional outbox pattern** (they don't have this)
- ✅ **True code-first Python** (not JSON/YAML)
- ✅ **No vendor lock-in**
- ✅ **10x cost advantage**
- ✅ **Sub-10ms latency**

---

## Current Version: 1.1.2

### ✅ Completed Features

| Feature | Version | Status |
|---------|---------|--------|
| Core Saga Pattern | 1.0.0 | ✅ Done |
| Transactional Outbox | 1.0.0 | ✅ Done |
| PostgreSQL Storage | 1.0.0 | ✅ Done |
| RabbitMQ Broker | 1.0.0 | ✅ Done |
| Kafka Broker | 1.0.0 | ✅ Done |
| Redis Broker | 1.0.1 | ✅ Done |
| Kubernetes Deployment | 1.0.0 | ✅ Done |
| Consumer Inbox (Idempotency) | 1.0.0 | ✅ Done |
| Compensation Graph | 1.0.0 | ✅ Done |
| Prometheus Metrics | 1.0.0 | ✅ Done |
| **Unified SagaConfig** | 1.0.3 | ✅ Done |
| **Environment Variable Config** | 1.0.3 | ✅ Done |
| **Mermaid Diagram Generation** | 1.0.3 | ✅ Done |
| **Connected Graph Validation** | 1.0.3 | ✅ Done |
| **Grafana Dashboard Templates** | 1.0.3 | ✅ Done |
| **Unified Storage Layer** | 1.2.0 | ✅ Done — [ADR-016](architecture/adr/adr-016-unified-storage-layer.md) |
| **Compensation Result Passing** | 1.2.0 | ✅ Done — [ADR-022](architecture/adr/adr-022-compensation-result-passing.md) |
| **Pivot / Irreversible Steps** | 1.3.0 | ✅ Done — [ADR-023](architecture/adr/adr-023-pivot-irreversible-steps.md) |
| **Event-Driven Triggers** | 1.3.0 | ✅ Done — [ADR-025](architecture/adr/adr-025-event-driven-triggers.md) |
| **Dry-Run Mode** (`validate` / `simulate`) | 1.3.0 | ✅ Done — [ADR-019](architecture/adr/adr-019-dry-run-mode.md) |
| **Project CLI** (`project init/check/list`) | 1.3.0 | ✅ Done — [ADR-027](architecture/adr/adr-027-project-cli.md) |
| **Framework Integration** (FastAPI/Django/Flask) | 1.3.0 | ✅ Done — [ADR-028](architecture/adr/adr-028-framework-integration.md) |
| **Lightweight Context Streaming** | 1.4.0 | ✅ Done — [ADR-021](architecture/adr/adr-021-lightweight-context-streaming.md) |
| **Industry Examples** (24 examples, 12 verticals) | 1.4.0 | ✅ Done — [ADR-026](architecture/adr/adr-026-industry-examples-expansion.md) |
| **Saga Replay & Time-Travel** | 2.1.0 | ✅ Done — [ADR-024](architecture/adr/adr-024-saga-replay.md) |

---

## 2026 Strategic Timeline

```
2026 Strategic Timeline
═══════════════════════════════════════════════════════════════════════════════
      Q1 (Jan-Mar)          Q2 (Apr-Jun)         Q3 (Jul-Sep)      Q4 (Oct-Dec)
═══════════════════════════════════════════════════════════════════════════════

DX    ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
      │ CLI v1.0     │   │ CLI v2.0     │   │ Cloud Tier   │
      │ init/deploy  │   │ Multi-cloud  │   │ Managed Dev  │
      └──────────────┘   └──────────────┘   └──────────────┘

TECH  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
      │ v1.5 DLQ     │   │ v1.8 CDC     │   │ v1.9 Fluss   │  → v1.10 Enrich
      │ Alerts       │   │ Debezium     │   │ Iceberg      │
      └──────────────┘   └──────────────┘   └──────────────┘

ECO   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
      │ Quickstart   │   │ FastAPI      │   │ Templates    │
      │ Docs/Videos  │   │ Django       │   │ Marketplace  │
      └──────────────┘   └──────────────┘   └──────────────┘

═══════════════════════════════════════════════════════════════════════════════
```

---

## Q1 2026 (Jan-Mar) — ✅ Completed

> All major Q1 deliverables were shipped ahead of schedule.

| Release | Feature | Status |
|---------|---------|--------|
| v1.2.0 | Unified Storage Layer | ✅ Done |
| v1.2.0 | Compensation Result Passing | ✅ Done |
| v1.3.0 | Pivot/Irreversible Steps | ✅ Done |
| v1.3.0 | Event-Driven Triggers | ✅ Done |
| v1.3.0 | Dry-Run Mode | ✅ Done |
| v1.3.0 | Project CLI | ✅ Done |
| v1.3.0 | Framework Integration | ✅ Done |
| v1.4.0 | Lightweight Context Streaming | ✅ Done |
| v1.4.0 | Industry Examples (24) | ✅ Done |
| v1.4.0 | Saga Replay & Time-Travel | ✅ Done |

Items originally tagged Q1 but deferred to Q2 (not yet started):

| Feature | Issue |
|---------|-------|
| CLI v1.0 local dev commands | [#48](https://github.com/brunolnetto/sagaz/issues/48) |
| Dead Letter Queue | [#44](https://github.com/brunolnetto/sagaz/issues/44) |
| AlertManager Rules | [#45](https://github.com/brunolnetto/sagaz/issues/45) |
| SQLite Backend | [#46](https://github.com/brunolnetto/sagaz/issues/46) |
| Storage Data Transfer layer | [#47](https://github.com/brunolnetto/sagaz/issues/47) |

---

## 📅 Implementation Schedule — Apr 7 → Jun 30, 2026

> **Deadline**: Jun 30, 2026 (61 business days) — dependency-ordered, no weekends.
> Deferred items (Q3+) are listed at the bottom.

### Dependency Graph

```
PR #42 (fix/coverage-and-container-timeouts)
  └─► DLQ #44 ──────────────────────────────────────────────────────────► M1
        └─► AlertManager #45 ─────────────────────────────────────────────► M1
        └─► SQLite #46 ───────────────────────────────────────────────────► M2
              └─► sqldim analytics #73 ──────────────────────────────────► M2
              └─► Storage migration #47 ────────────────────────────────► M2
                    └─► CLI v1.0 #48 ────────────────────────────────────► M3
                    └─► Visualization UI #58 ◄── enabled by #73 ─────────► M3
```

### Day-by-Day Schedule (D1–D61)

| Days | Dates | Feature | PR | Milestone |
|------|-------|---------|-----|-----------|
| D1–D2 | Apr 7–8 | Merge PR #42; read DLQ + storage design docs | [#42](https://github.com/brunolnetto/sagaz/pull/42) | M1 |
| D3–D8 | Apr 9–16 | DLQ implementation Phases 1+2 (queue model, consumer, metrics) | [#60](https://github.com/brunolnetto/sagaz/pull/60) / [#44](https://github.com/brunolnetto/sagaz/issues/44) | M1 |
| D9–D10 | Apr 17–18 | AlertManager rules template + docs | [#61](https://github.com/brunolnetto/sagaz/pull/61) / [#45](https://github.com/brunolnetto/sagaz/issues/45) | M1 |
| D11–D17 | Apr 21–29 | SQLite backend Phases 1+2 (schema, CRUD, migrations) | [#62](https://github.com/brunolnetto/sagaz/pull/62) / [#46](https://github.com/brunolnetto/sagaz/issues/46) | M2 |
| D18–D22 | Apr 30–May 6 | Storage migration layer + transfer API | [#63](https://github.com/brunolnetto/sagaz/pull/63) / [#47](https://github.com/brunolnetto/sagaz/issues/47) | M2 |
| D23–D30 | May 7–16 | sqldim analytics — Bronze reads + Silver star schema | [#74](https://github.com/brunolnetto/sagaz/pull/74) / [#73](https://github.com/brunolnetto/sagaz/issues/73) | M2 |
| D31–D38 | May 19–28 | CLI v1.0 (`init`, `dev`, `status`, `logs`, `visualize`) | [#64](https://github.com/brunolnetto/sagaz/pull/64) / [#48](https://github.com/brunolnetto/sagaz/issues/48) | M3 |
| D31–D35 | May 10–18 | **Gradio Asset Monitor** (ADR-039) | [#267](https://github.com/brunolnetto/sagaz/issues/267) | M3 |
| D39–D52 | May 29–Jun 17 | Visualization UI — REST/SSE API + dashboard (Phases 1–3) | [#71](https://github.com/brunolnetto/sagaz/pull/71) / [#58](https://github.com/brunolnetto/sagaz/issues/58) | M3 |
| D53–D57 | Jun 18–24 | sqldim Gold aggregations + UI analytics tab integration | [#74](https://github.com/brunolnetto/sagaz/pull/74) | M3 |
| D58–D61 | Jun 25–30 | Integration testing, bugfix buffer, cut v1.5.0 / v1.6.0-beta | — | M3 |

### What Ships by June 30

| Release | Features | PRs |
|---------|----------|-----|
| v1.5.0 | DLQ pattern, AlertManager rules | #60, #61 |
| v1.6.0 | SQLite backend, storage migration | #62, #63 |
| v1.7.0-beta | sqldim analytics pipeline (`sagaz[analytics]`) | #74 |
| v1.7.0-beta | Gradio Asset Monitor UI (`sagaz[monitor]`) | #267 |
| v1.7.0-beta | Visualization UI + live analytics tab | #71 |

### Deferred to Q3+ (Jul–Dec 2026)

| Feature | Issue | Earliest start |
|---------|-------|----------------|
| CLI v2.0 multi-cloud deploy | [#49](https://github.com/brunolnetto/sagaz/issues/49) | Jul 1 |
| CDC / Debezium | [#50](https://github.com/brunolnetto/sagaz/issues/50) | Jul 1 |
| Fluss + Iceberg analytics | [#51](https://github.com/brunolnetto/sagaz/issues/51) | Aug 1 |
| Choreography engine | [#56](https://github.com/brunolnetto/sagaz/issues/56) | Aug 1 |
| Event sourcing integration | [#57](https://github.com/brunolnetto/sagaz/issues/57) | Oct 1 |
| Multi-tenancy | [#54](https://github.com/brunolnetto/sagaz/issues/54) | Oct 1 |
| Multi-region coordination | [#59](https://github.com/brunolnetto/sagaz/issues/59) | Nov 1 |

---

## 📅 Semester Sprint Calendar — Apr–Sep 2026 (reference)

> Sprint reference view — see "Implementation Schedule" above for the day-by-day plan.
> Sprints are 2 weeks each.

| Sprint | Dates | Deliverable | Issues |
|--------|-------|-------------|--------|
| S1 | Apr 7 – Apr 18 | Merge PR #42; start DLQ | [#41](https://github.com/brunolnetto/sagaz/issues/41), [#44](https://github.com/brunolnetto/sagaz/issues/44) |
| S2 | Apr 21 – May 2 | DLQ + AlertManager + SQLite start | [#44](https://github.com/brunolnetto/sagaz/issues/44), [#45](https://github.com/brunolnetto/sagaz/issues/45), [#46](https://github.com/brunolnetto/sagaz/issues/46) |
| S3 | May 5 – May 16 | SQLite backend + storage migration | [#46](https://github.com/brunolnetto/sagaz/issues/46), [#47](https://github.com/brunolnetto/sagaz/issues/47) |
| S4 | May 19 – May 30 | sqldim analytics pipeline + CLI v1.0 | [#73](https://github.com/brunolnetto/sagaz/issues/73), [#48](https://github.com/brunolnetto/sagaz/issues/48) |
| S5 | Jun 2 – Jun 13 | Visualization UI Phases 1–2 | [#58](https://github.com/brunolnetto/sagaz/issues/58) |
| S6 | Jun 16 – Jun 30 | Viz UI Phase 3 + Gold integr. + v2.2.0-beta + v1.5.0 | [#58](https://github.com/brunolnetto/sagaz/issues/58), [#73](https://github.com/brunolnetto/sagaz/issues/73) |
| S7 | Jul 1 – Jul 11 | CDC/Debezium worker + pg_logical | [#50](https://github.com/brunolnetto/sagaz/issues/50) |
| S8 | Jul 14 – Jul 25 | CDC metrics, dashboards; CLI v2.0 start | [#50](https://github.com/brunolnetto/sagaz/issues/50), [#49](https://github.com/brunolnetto/sagaz/issues/49) |
| S9 | Jul 28 – Aug 8 | CLI v2.0 (`deploy --provider`) + Fluss listener | [#49](https://github.com/brunolnetto/sagaz/issues/49), [#51](https://github.com/brunolnetto/sagaz/issues/51) |
| S10 | Aug 11 – Aug 22 | Choreography engine Phase 1–2 | [#56](https://github.com/brunolnetto/sagaz/issues/56) |
| S11 | Aug 25 – Sep 5 | Choreography Phase 3–4 | [#56](https://github.com/brunolnetto/sagaz/issues/56) |
| S12 | Sep 8 – Sep 19 | Choreography Phase 5 + release v1.9.0 | [#56](https://github.com/brunolnetto/sagaz/issues/56) |
| S13 | Sep 22 – Sep 30 | Multi-tenancy Phase 1 start | [#54](https://github.com/brunolnetto/sagaz/issues/54) |

---

## Q2 2026 (Apr-Jun) — 🔄 In Progress

### CLI v2.0 - Multi-Cloud Deploy

**Target**: S8–S9 (Jul–Aug 2026) | **Effort**: 30-40 hours | [#49](https://github.com/brunolnetto/sagaz/issues/49)

| Feature | Priority | Status |
|---------|----------|--------|
| `sagaz deploy --provider aws` | High | 📋 Planned |
| `sagaz deploy --provider gcp` | Medium | 📋 Planned |
| `sagaz deploy --provider k8s` | High | 📋 Planned |
| `sagaz deploy --cost-estimate` | Medium | 📋 Planned |

### v2.0.0 - CDC (Change Data Capture)

**Target**: S7–S8 (Jun–Jul 2026) | **Effort**: 26-40 hours | [ADR-011](architecture/adr/adr-011-cdc-support.md) | [#50](https://github.com/brunolnetto/sagaz/issues/50)

| Feature | Priority | Status |
|---------|----------|--------|
| **CDC Support (Debezium)** | High | 📋 Planned |
| CDC Worker implementation | High | 📋 Planned |
| Native pg_logical support | Medium | 📋 Planned |
| CDC Prometheus metrics | High | 📋 Planned |
| CDC Grafana dashboards | High | 📋 Planned |

**Target throughput**: 50,000+ events/sec

### ✅ Already Shipped (not Q2 work)

| Feature | Version | ADR |
|---------|---------|-----|
| Dry-Run Mode | 1.3.0 | [ADR-019](architecture/adr/adr-019-dry-run-mode.md) |
| Lightweight Context Streaming | 1.4.0 | [ADR-021](architecture/adr/adr-021-lightweight-context-streaming.md) |
| Saga Replay & Time-Travel | 2.1.0 | [ADR-024](architecture/adr/adr-024-saga-replay.md) |

### v1.5.0 - DLQ + Storage + CLI v1.0 (Deferred from Q1)

**Target**: S1–S6 (Apr–Jun 2026)

| Feature | Sprint | Issue |
|---------|--------|-------|
| Dead Letter Queue pattern | S1–S2 | [#44](https://github.com/brunolnetto/sagaz/issues/44) |
| AlertManager rules template | S2 | [#45](https://github.com/brunolnetto/sagaz/issues/45) |
| SQLite backend | S3 | [#46](https://github.com/brunolnetto/sagaz/issues/46) |
| Storage data-transfer layer | S4 | [#47](https://github.com/brunolnetto/sagaz/issues/47) |
| CLI v1.0 (`init`, `dev`, `status`, `logs`, `visualize`) | S5–S6 | [#48](https://github.com/brunolnetto/sagaz/issues/48) |

---

## Q3 2026 (Jul-Sep) — Planned

### v2.0.0 - CDC (Change Data Capture) continued

**Target**: S7–S8 (Jul 2026) | [ADR-011](architecture/adr/adr-011-cdc-support.md) | [#50](https://github.com/brunolnetto/sagaz/issues/50)

(Continues from Q2 S7–S8 sprint.)

### v2.1.0 - Analytics (Fluss + Iceberg)

**Target**: S9 (Aug 2026) | **Effort**: 32-48 hours | [ADR-013](architecture/adr/adr-013-fluss-iceberg-analytics.md) | [#51](https://github.com/brunolnetto/sagaz/issues/51)

| Feature | Priority | Status |
|---------|----------|--------|
| **Fluss Analytics Listener** | High | 📋 Planned |
| Iceberg tiering integration | High | 📋 Planned |
| Real-time saga dashboards | Medium | 📋 Planned |
| Historical saga analytics | Medium | 📋 Planned |

**Architecture:**
```
Saga → FlussListener → Fluss (real-time) → Iceberg (historical)
                           ↓                      ↓
                     Dashboard              Long-term
                     (sub-second)           analytics
```

### v2.2.0 - Saga Visualization UI

**Target**: S10 (Aug 2026) | **Effort**: 16-24 hours | [ADR-035](architecture/adr/adr-035-saga-visualization-ui.md) | [#58](https://github.com/brunolnetto/sagaz/issues/58)

| Feature | Priority | Status |
|---------|----------|--------|
| REST + SSE backend API | High | 📋 Planned |
| `sagaz monitor` command | High | 📋 Planned |
| Interactive web dashboard | High | 📋 Planned |
| Live step progress (SSE) | Medium | 📋 Planned |
| Step Explorer & run comparison | Medium | 📋 Planned |

### v2.2.0 - Saga Choreography Mode (Phases 1–4)

**Target**: S11–S12 (Aug–Sep 2026) | [ADR-029](architecture/adr/adr-029-saga-choreography.md) | [#56](https://github.com/brunolnetto/sagaz/issues/56)

| Feature | Priority | Status |
|---------|----------|--------|
| Event Bus Infrastructure | High | 📋 Planned |
| Choreography Engine | High | 📋 Planned |
| Distributed tracing for choreography | Medium | 📋 Planned |

---

## Q4 2026 (Oct-Dec) — Planned

### Multi-Tenancy Support

**Target**: Oct–Nov 2026 | [ADR-020](architecture/adr/adr-020-multi-tenancy.md) | [#54](https://github.com/brunolnetto/sagaz/issues/54)

| Feature | Priority | Status |
|---------|----------|--------|
| Tenant context propagation | High | 📋 Planned |
| Row-level security (RLS) | High | 📋 Planned |
| Resource quotas per tenant | Medium | 📋 Planned |
| Per-tenant encryption | Medium | 📋 Planned |

### v2.2.0 - Saga Choreography Mode (Phase 5 wrap-up)

**Target**: Oct 2026 | [ADR-029](architecture/adr/adr-029-saga-choreography.md) | [#56](https://github.com/brunolnetto/sagaz/issues/56)

| Feature | Priority | Status |
|---------|----------|--------|
| Event sourcing integration (with ADR-033) | Medium | 📋 Planned |
| Testing & observability | Medium | 📋 Planned |

### v2.3.0 - Event Sourcing Integration

**Target**: Nov 2026 | **Effort**: 20-30 hours | [ADR-033](architecture/adr/adr-033-event-sourcing-integration.md) | [#57](https://github.com/brunolnetto/sagaz/issues/57)

| Feature | Priority | Status |
|---------|----------|--------|
| `SagaEvent` hierarchy & event store interface | High | 📋 Planned |
| PostgreSQL + SQLite event store backends | High | 📋 Planned |
| Opt-in `Meta.storage_strategy = "event_sourced"` | High | 📋 Planned |
| Projection / read-model builder | Medium | 📋 Planned |
| Snapshot threshold strategy | Medium | 📋 Planned |
| `sagaz event-log <saga-id>` CLI command | Medium | 📋 Planned |

### v2.4.0 - Multi-Region Saga Coordination

**Target**: Dec 2026 | **Effort**: 40-56 hours | [ADR-034](architecture/adr/adr-034-multi-region-coordination.md) | [#59](https://github.com/brunolnetto/sagaz/issues/59)

| Feature | Priority | Status |
|---------|----------|--------|
| Region registry & routing | High | 📋 Planned |
| Cross-region coordinator | High | 📋 Planned |
| Conflict resolution (OCC + vector clocks) | High | 📋 Planned |
| Automatic region failover (< 5 s) | High | 📋 Planned |
| `sagaz region list/failover` CLI commands | Medium | 📋 Planned |

### Cloud Managed Tier (Beta)

Sagaz Cloud platform with managed infrastructure.

---

## 2027+ Considerations

All previously listed ideas have been promoted to the 2026 roadmap and have dedicated ADRs:

| Feature | ADR | Scheduled | Issue |
|---------|-----|-----------|-------|
| Lightweight Context Streaming | [ADR-021](architecture/adr/adr-021-lightweight-context-streaming.md) | v1.4.0 ✅ Done | — |
| Saga Replay & Time-Travel | [ADR-024](architecture/adr/adr-024-saga-replay.md) | v2.1.0 ✅ Done | — |
| Saga Choreography Mode | [ADR-029](architecture/adr/adr-029-saga-choreography.md) | v2.2.0 (Aug–Oct 2026) | [#56](https://github.com/brunolnetto/sagaz/issues/56) |
| Saga Visualization UI | [ADR-035](architecture/adr/adr-035-saga-visualization-ui.md) | v2.2.0 (Aug 2026) | [#58](https://github.com/brunolnetto/sagaz/issues/58) |
| Event Sourcing Integration | [ADR-033](architecture/adr/adr-033-event-sourcing-integration.md) | v2.3.0 (Nov 2026) | [#57](https://github.com/brunolnetto/sagaz/issues/57) |
| Multi-Region Coordination | [ADR-034](architecture/adr/adr-034-multi-region-coordination.md) | v2.4.0 (Dec 2026) | [#59](https://github.com/brunolnetto/sagaz/issues/59) |

---

## Strategic Focus Areas

### Cost Advantage

| Platform | Setup | Monthly Cost (10K exec) |
|----------|-------|------------------------|
| AWS Step Functions | None | ~$250 |
| Temporal Cloud | None | ~$200 |
| Azure Durable Functions | None | ~$150 |
| **Sagaz (Fully Managed)** | 15 min | ~$180 |
| **Sagaz (Hybrid)** | 15 min | ~$75 |
| **Sagaz (Self-Hosted)** | 30 min | ~$0* |

*Self-hosted: Only compute costs (your existing infra)

### Deployment Flexibility

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DEPLOYMENT MODES                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SELF-HOSTED                HYBRID                    FULLY MANAGED          │
│  ────────────               ──────                    ─────────────          │
│  • Docker Compose           • App on K8s              • Cloud Only           │
│  • All local               • Managed data services   • RDS, MSK, etc        │
│                                                                              │
│  Cost: $0                  Cost: $50-200/mo          Cost: $100-500/mo      │
│  Ops: High                 Ops: Medium               Ops: Low               │
│  Scale: Limited            Scale: High               Scale: High            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Competitive Positioning

| Feature | Sagaz | Temporal | Step Functions | Durable Functions |
|---------|-------|----------|----------------|-------------------|
| Setup time | 5 min | 30-60 min | 2 min | 10 min |
| Monthly cost (10k exec) | ~$50 | ~$100 | ~$250 | ~$150 |
| Exactly-once | ✅ | ✅ | ❌ | ❌ |
| Code-first Python | ✅ | ✅ | ❌ | ❌ |
| Multi-cloud | ✅ | ✅ | ❌ | ❌ |
| Transactional outbox | ✅ | ❌ | ❌ | ❌ |
| Sub-10ms publishing | ✅ | ❌ | ❌ | ❌ |
| Open source | ✅ | ✅ | ❌ | ❌ |
| Self-hosted option | ✅ | ✅ | ❌ | ❌ |

---

## Developer Experience

### CLI Architecture

```
sagaz-cli/
├── commands/
│   ├── init.py        # Setup wizard
│   ├── deploy.py      # Deployment automation
│   ├── monitor.py     # Observability
│   ├── logs.py        # Log tailing
│   └── status.py      # Health checks
├── providers/
│   ├── local.py       # Docker Compose (default)
│   ├── aws.py         # AWS (Terraform/CDK)
│   ├── gcp.py         # GCP
│   └── k8s.py         # Kubernetes (any cloud)
└── templates/
    ├── terraform/     # IaC templates per provider
    ├── k8s/           # Kubernetes manifests
    └── docker/        # Docker Compose files
```

### CLI Commands

```bash
# Getting started (5 minutes to production)
sagaz init                     # Interactive wizard
sagaz init --local             # Docker Compose (default)
sagaz init --provider aws      # AWS with Terraform
sagaz init --provider k8s      # Kubernetes

# Deployment
sagaz deploy                   # Deploy infrastructure
sagaz deploy --dry-run         # Preview changes
sagaz deploy --cost-estimate   # Show monthly cost

# Operations
sagaz status                   # Health of all components
sagaz monitor                  # Open Grafana dashboard
sagaz logs                     # Tail all logs
sagaz logs saga-id-123         # Specific saga logs

# Saga management
sagaz saga list                # List running sagas
sagaz saga inspect <id>        # Saga details + Mermaid
sagaz saga retry <id>          # Retry failed saga
sagaz saga cancel <id>         # Cancel running saga

# DLQ management
sagaz dlq list                 # Show DLQ messages
sagaz dlq replay --all         # Replay all
sagaz dlq purge --older 7d     # Purge old messages
```

---

## Success Metrics

### Developer Experience
- **Time-to-first-saga**: < 5 minutes (target)
- **CLI adoption**: % of users using `sagaz init`
- **Setup failure rate**: < 5%

### Adoption
- **GitHub stars**: 1k → 5k → 10k
- **PyPI downloads**: 1k/month → 10k/month
- **Active users**: DAU/MAU ratio

### Business
- **Free tier signups**: Conversion funnel
- **Paid tier revenue**: MRR growth
- **Enterprise leads**: Pipeline value

---

## Related Documents

- [ADR Index](architecture/adr/README.md) - All Architecture Decision Records
- [Architecture Overview](architecture/overview.md) - System design
- [Patterns](patterns/) - Implementation patterns
- [Documentation Structure](STRUCTURE.md) - Where to add new content

---

## Contributing

To propose a new feature:
1. Open a GitHub issue with the feature request
2. If significant, create an ADR in `docs/architecture/adr/`
3. Submit a PR referencing the issue/ADR

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 2.1.0 | 2026-01 | Saga Replay & Time-Travel (all 6 phases, ADR-024) |
| 1.4.0 | 2026-01 | Context Streaming (ADR-021), 24 industry examples (ADR-026) |
| 1.3.0 | 2026-01 | Pivot Steps (ADR-023), Event Triggers (ADR-025), Dry-Run (ADR-019), CLI scaffold (ADR-027), Framework integration (ADR-028) |
| 1.2.0 | 2026-01 | Unified Storage Layer (ADR-016), Compensation Result Passing (ADR-022) |
| 1.0.3 | 2024-12 | Unified SagaConfig, env var config, test perf |
| 1.0.2 | 2024-12 | CI improvements, Codecov, code quality fixes |
| 1.0.1 | 2024-12 | Redis broker, documentation reorg |
| 1.0.0 | 2024-11 | Initial release |
