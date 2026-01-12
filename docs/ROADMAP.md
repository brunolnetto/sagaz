# Sagaz Roadmap & Strategy 2026

Active development roadmap for the Sagaz saga pattern library.

> **Updated**: 2026-01-05 | **Version**: 1.0.x → 2.x

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

## Current Version: 1.0.x

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
      │ v1.1 DLQ     │   │ v2.0 CDC     │   │ v2.1 Fluss   │  → v2.2 Enrich
      │ Alerts       │   │ Debezium     │   │ Iceberg      │
      └──────────────┘   └──────────────┘   └──────────────┘

ECO   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
      │ Quickstart   │   │ FastAPI      │   │ Templates    │
      │ Docs/Videos  │   │ Django       │   │ Marketplace  │
      └──────────────┘   └──────────────┘   └──────────────┘

═══════════════════════════════════════════════════════════════════════════════
```

---

## Q1 2026 (Jan-Mar)

### CLI v1.0 - Local Development

**Target**: Q1 2026 | **Effort**: 20-30 hours

| Feature | Priority | Status |
|---------|----------|--------|
| `sagaz init --local` | High | 📋 Planned |
| `sagaz dev` (start containers) | High | 📋 Planned |
| `sagaz status` (health check) | High | 📋 Planned |
| `sagaz logs` (log tailing) | Medium | 📋 Planned |
| `sagaz visualize` (Mermaid) | Medium | 📋 Planned |

### v1.1.0 - Reliability & Observability

**Target**: Q1 2026 | **Effort**: 16-24 hours

| Feature | Priority | Status | Docs |
|---------|----------|--------|------|
| **Dead Letter Queue Pattern** | High | 📋 Planned | [Docs](patterns/dead-letter-queue.md) |
| **AlertManager Rules Template** | High | 📋 Planned | [Template](monitoring/alertmanager-rules.yml) |
| Batch saga status updates | Low | 📋 Planned | - |

### v1.2.0 - Unified Storage Layer

**Target**: Q1 2026 | **Effort**: 5-6 weeks

| Feature | Priority | Status | Docs |
|---------|----------|--------|------|
| **Core Infrastructure** | High | 📋 Planned | [Plan](architecture/unified-storage-implementation-plan.md) |
| **Redis Outbox Storage** | High | 📋 Planned | [Plan](architecture/unified-storage-implementation-plan.md) |
| **Data Transfer Layer** | High | 📋 Planned | [Plan](architecture/unified-storage-implementation-plan.md) |
| SQLite Backend | Low | 📋 Planned | - |

---

## Q2 2026 (Apr-Jun)

### CLI v2.0 - Multi-Cloud Deploy

**Target**: Q2 2026 | **Effort**: 30-40 hours

| Feature | Priority | Status |
|---------|----------|--------|
| `sagaz deploy --provider aws` | High | 📋 Planned |
| `sagaz deploy --provider gcp` | Medium | 📋 Planned |
| `sagaz deploy --provider k8s` | High | 📋 Planned |
| `sagaz deploy --cost-estimate` | Medium | 📋 Planned |

### v2.0.0 - CDC (Change Data Capture)

**Target**: Q2 2026 | **Effort**: 26-40 hours | [ADR-011](architecture/adr/adr-011-cdc-support.md)

| Feature | Priority | Status |
|---------|----------|--------|
| **CDC Support (Debezium)** | High | 📋 Planned |
| CDC Worker implementation | High | 📋 Planned |
| Native pg_logical support | Medium | 📋 Planned |
| CDC Prometheus metrics | High | 📋 Planned |
| CDC Grafana dashboards | High | 📋 Planned |

**Target throughput**: 50,000+ events/sec

### ✅ Dry-Run Mode (COMPLETED v1.3.0)

**Status**: ✅ Implemented | [ADR-019](architecture/adr/adr-019-dry-run-mode.md)

Validate and preview saga execution without side effects.

**Features**:
- `sagaz validate` - Validate saga configuration
- `sagaz simulate` - Analyze execution DAG and step order
- 100% test coverage (29 tests)
- Interactive saga selection
- Rich output formatting

---

## Q3 2026 (Jul-Sep)

### v2.1.0 - Analytics (Fluss + Iceberg)

**Target**: Q3 2026 | **Effort**: 32-48 hours | [ADR-013](architecture/adr/adr-013-fluss-iceberg-analytics.md)

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

### Saga Replay & Time-Travel

**Target**: Q3 2026 | [ADR-016](architecture/adr/adr-016-saga-replay.md)

Replay failed sagas and query historical state for debugging and compliance.

### Pivot/Irreversible Steps

**Target**: Q3 2026 | [ADR-023](architecture/adr/adr-023-pivot-irreversible-steps.md)

Support for irreversible steps and forward recovery patterns.

---

## Q4 2026 (Oct-Dec)

### Multi-Tenancy Support

**Target**: Q4 2026 | [ADR-020](architecture/adr/adr-020-multi-tenancy.md)

| Feature | Priority | Status |
|---------|----------|--------|
| Tenant context propagation | High | 📋 Planned |
| Row-level security (RLS) | High | 📋 Planned |
| Resource quotas per tenant | Medium | 📋 Planned |
| Per-tenant encryption | Medium | 📋 Planned |

### Cloud Managed Tier (Beta)

Sagaz Cloud platform with managed infrastructure.

---

## 2027+ Considerations

### Lightweight Context Streaming

[ADR-021](architecture/adr/adr-021-lightweight-context-streaming.md) - Reference-based context passing and streaming between steps.

### Future Ideas (Community Interest)

| Feature | Notes | Status |
|---------|-------|--------|
| Event sourcing integration | Store saga state as events | 💡 Ideas |
| Saga choreography mode | Event-driven sagas (vs orchestration) | 💡 Ideas |
| Multi-region support | Cross-region saga coordination | 💡 Ideas |
| Saga visualization UI | Dashboard for saga monitoring | 💡 Ideas |

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
| 1.0.3 | 2024-12 | Unified SagaConfig, env var config, test perf |
| 1.0.2 | 2024-12 | CI improvements, Codecov, code quality fixes |
| 1.0.1 | 2024-12 | Redis broker, documentation reorg |
| 1.0.0 | 2024-11 | Initial release |
