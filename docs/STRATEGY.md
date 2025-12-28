# Sagaz Strategic Roadmap 2025

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

## Strategic Pillars

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SAGAZ STRATEGY                                │
├─────────────────┬─────────────────┬─────────────────┬───────────────┤
│   DEVELOPER     │   TECHNICAL     │    ECOSYSTEM    │   BUSINESS    │
│   EXPERIENCE    │   EXCELLENCE    │   EXPANSION     │    MODEL      │
├─────────────────┼─────────────────┼─────────────────┼───────────────┤
│ • CLI tooling   │ • CDC support   │ • Integrations  │ • Open source │
│ • 5-min setup   │ • Analytics     │ • Templates     │ • Cloud tiers │
│ • Multi-cloud   │ • DLQ/Alerts    │ • Community     │ • Enterprise  │
│ • Documentation │ • Performance   │ • Marketplace   │ • Support     │
└─────────────────┴─────────────────┴─────────────────┴───────────────┘
```

---

## Unified Timeline

```
2025 Strategic Timeline
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

## Phase 1: Developer Experience CLI (Q1 2025)

### Goal
**Time-to-first-saga: < 5 minutes**

### CLI Architecture

```
sagaz-cli/
├── commands/
│   ├── init.py        # Setup wizard
│   ├── deploy.py      # Deployment automation
│   ├── monitor.py     # Observability
│   ├── logs.py        # Log tailing
│   ├── status.py      # Health checks
│   └── migrate.py     # Cloud provider migration
├── providers/
│   ├── local.py       # Docker Compose (default)
│   ├── aws.py         # AWS-specific (Terraform/CDK)
│   ├── gcp.py         # GCP-specific
│   ├── azure.py       # Azure-specific
│   └── k8s.py         # Kubernetes (any cloud)
├── templates/
│   ├── terraform/     # IaC templates per provider
│   ├── pulumi/        # Pulumi alternatives
│   ├── k8s/           # Kubernetes manifests
│   └── docker/        # Docker Compose files
└── ui/
    └── tui.py         # Rich terminal UI
```

### CLI Commands

```bash
# Getting started (5 minutes to production)
sagaz init                     # Interactive wizard
sagaz init --local             # Docker Compose (default)
sagaz init --provider aws      # AWS with Terraform
sagaz init --provider gcp      # Google Cloud
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

# Development
sagaz dev                      # Start local dev environment
sagaz test                     # Run saga tests
sagaz visualize                # Open Mermaid diagram

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

### Implementation Checklist

**Week 1-2: Core CLI**
- [ ] Set up CLI project with Click/Typer
- [ ] Implement `sagaz init --local` (Docker Compose)
- [ ] Create interactive setup wizard (Rich library)
- [ ] Generate sagaz.yaml config file
- [ ] Implement `sagaz status`

**Week 3-4: Local Development**
- [ ] Implement `sagaz dev` (start Docker Compose)
- [ ] Implement `sagaz logs` with live tailing
- [ ] Implement `sagaz monitor` (open Grafana)
- [ ] Implement `sagaz visualize` (Mermaid)
- [ ] Create quickstart tutorial

**Week 5-6: Cloud Providers**
- [ ] Create Terraform templates for AWS
- [ ] Implement `sagaz deploy` + `--dry-run`
- [ ] Add cost estimation feature
- [ ] GCP templates
- [ ] Azure templates

**Effort Estimate**: 40-60 hours (4-6 weeks)

---

## Deployment Flexibility

### Service Dependency Matrix

Each component can be self-hosted, cloud-managed, or bring-your-own:

| Component | Self-Hosted | AWS Managed | GCP Managed | Azure Managed |
|-----------|-------------|-------------|-------------|---------------|
| **Database** | PostgreSQL (Docker) | RDS PostgreSQL | Cloud SQL | Azure PostgreSQL |
| **Broker** | Kafka/RabbitMQ/Redis | MSK / Amazon MQ | Pub/Sub | Event Hubs |
| **Cache** | Redis (Docker) | ElastiCache | Memorystore | Azure Cache |
| **Observability** | Prometheus+Grafana | CloudWatch | Cloud Monitoring | Azure Monitor |
| **Analytics** | Fluss+Iceberg | Athena+Iceberg | BigQuery | Synapse |

### Deployment Modes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DEPLOYMENT MODES                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SELF-HOSTED                HYBRID                    FULLY MANAGED          │
│  ────────────               ──────                    ─────────────          │
│                                                                              │
│  ┌─────────┐       ┌─────────┐ ┌─────────┐       ┌─────────────────┐        │
│  │ Docker  │       │ App     │ │ Managed │       │   Cloud Only    │        │
│  │ Compose │       │ (K8s)   │ │ Services│       │                 │        │
│  │         │       │         │ │ (RDS,   │       │ • RDS/Cloud SQL │        │
│  │ • Postgres      │ • Workers│ │  MSK,  │       │ • MSK/Pub-Sub   │        │
│  │ • Kafka │       │ • Outbox│ │  etc)  │       │ • ElastiCache   │        │
│  │ • Redis │       └─────────┘ └─────────┘       │ • CloudWatch    │        │
│  │ • Prom  │                                     └─────────────────┘        │
│  │ • Graf  │                                                                 │
│  └─────────┘                                                                 │
│                                                                              │
│  Cost: $0          Cost: $50-200/mo              Cost: $100-500/mo          │
│  Ops: High         Ops: Medium                   Ops: Low                   │
│  Scale: Limited    Scale: High                   Scale: High                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Interactive Setup Wizard (Context-Aware)

The wizard shows only relevant options based on deployment mode:

```bash
$ sagaz init

🚀 Welcome to Sagaz Setup!

? Select deployment mode:
  ❯ Local (Docker Compose) - Free, for development
    Self-hosted (Kubernetes) - Full control
    Hybrid (App self-hosted + Managed services)
    Fully Managed (Cloud services)
```

**If Local or Self-Hosted selected** (cloud options hidden):

```bash
# Only self-hosted options shown
? Select database:
  ❯ PostgreSQL - Uses existing k8s/postgresql.yaml
    Existing connection string - Bring your own

? Select message broker:
  ❯ Apache Kafka - Uses existing k8s templates
    RabbitMQ - Uses existing k8s/rabbitmq.yaml
    Redis Streams - Lightweight option
    Existing connection - Bring your own

? Select cache:
  ❯ Redis - Uses existing k8s templates
    Existing connection - Bring your own

? Select observability:
  ❯ Prometheus + Grafana - Uses k8s/monitoring/
    Existing setup - Bring your own

✅ Using existing k8s manifests from: k8s/
```

**If Hybrid or Managed selected** (cloud options shown):

```bash
? Select cloud provider:
  ❯ AWS
    GCP
    Azure

? Select database:
  ❯ AWS RDS PostgreSQL - Managed
    PostgreSQL (self-hosted) - On your K8s
    Existing connection - Bring your own

? Select message broker:
  ❯ AWS MSK - Managed Kafka
    Confluent Cloud - Managed Kafka
    Apache Kafka (self-hosted) - On your K8s
    Existing connection - Bring your own

# ... etc
```

### Existing K8s Resources

The CLI leverages your existing k8s manifests:

```
k8s/
├── postgresql.yaml           # PostgreSQL StatefulSet
├── postgresql-local.yaml     # PostgreSQL (local dev)
├── rabbitmq.yaml             # RabbitMQ deployment
├── outbox-worker.yaml        # Outbox worker
├── configmap.yaml            # Configuration
├── secrets-example.yaml      # Secret templates
└── monitoring/               # Observability stack (consolidated)
    ├── monitoring-stack.yaml       # Prometheus + Grafana
    ├── prometheus-alerts.yaml      # Alert rules
    ├── kustomization.yaml          # Kustomize config
    ├── grafana-dashboard-main.json # Main saga dashboard
    └── grafana-dashboard-outbox.json
```

### CLI Flags for Non-Interactive Mode

```bash
# Fully self-hosted (local dev)
sagaz init --mode local

# Self-hosted on Kubernetes
sagaz init --mode k8s \
  --database postgres:docker \
  --broker kafka:docker \
  --cache redis:docker

# Hybrid: App on K8s, managed data services
sagaz init --mode hybrid \
  --database postgres:aws-rds \
  --broker kafka:aws-msk \
  --cache redis:aws-elasticache

# Fully managed AWS
sagaz init --mode managed --provider aws

# Custom mix (bring your own)
sagaz init \
  --database postgres:existing --database-url="postgresql://..." \
  --broker kafka:existing --broker-url="kafka://..." \
  --cache redis:docker
```

### Deployment Presets

```bash
# Development (free, local)
sagaz init --preset dev
# → postgres:docker, redis:docker, prometheus:docker

# Production Self-Hosted (K8s)
sagaz init --preset prod-selfhosted
# → postgres:docker (PV), kafka:docker (3 nodes), redis:docker

# Production AWS (managed)
sagaz init --preset prod-aws
# → aws-rds, aws-msk, aws-elasticache, cloudwatch

# Budget Production (hybrid)
sagaz init --preset budget-prod
# → aws-rds (managed), kafka:docker (saves $), redis:docker
```

### Configuration File (`sagaz.yaml`)

```yaml
# sagaz.yaml - Generated by `sagaz init`
version: "1.0"

project:
  name: order-service
  environment: production

mode: hybrid  # local | k8s | hybrid | managed
provider: aws  # aws | gcp | azure | none

# ═══════════════════════════════════════════════════════════════
# SERVICES - Each independently self-hosted, managed, or existing
# ═══════════════════════════════════════════════════════════════

database:
  type: aws-rds  # docker | aws-rds | gcp-cloudsql | existing
  managed:
    instance_class: db.t3.medium
    multi_az: true
  # For existing:
  # connection:
  #   url: postgresql://host:5432/db

broker:
  type: kafka:docker  # kafka:docker | kafka:aws-msk | kafka:confluent | existing
  docker:
    nodes: 3
  # For managed:
  # managed:
  #   instance_type: kafka.m5.large

cache:
  type: redis:docker  # docker | aws-elasticache | existing

observability:
  metrics:
    type: prometheus:docker  # docker | aws-cloudwatch | datadog
  dashboards:
    type: grafana:docker
  tracing:
    type: jaeger:docker  # jaeger | aws-xray | datadog

# Optional: Analytics (v2.1+)
analytics:
  enabled: false
  type: fluss:docker
  storage: s3://bucket/sagaz-analytics/

# Compute configuration
compute:
  type: k8s  # docker | k8s | aws-ecs
  workers:
    replicas: 3
```

### Cost Calculator

```bash
$ sagaz deploy --cost-estimate

📊 Monthly Cost Estimate
═══════════════════════════════════════════════════════════════

Component            Type                    Est. Cost
─────────────────────────────────────────────────────────────
Database             AWS RDS (db.t3.medium)  $58/mo
Broker               Kafka (Docker - K8s)    $0 (compute only)
Cache                Redis (Docker - K8s)    $0 (compute only)
Compute              EKS (3 workers)         $73/mo
Observability        Prometheus (Docker)     $0 (compute only)
─────────────────────────────────────────────────────────────
                     TOTAL                   ~$131/mo

💡 vs. Fully Managed ($386/mo) → You save $255/mo with hybrid!

? Proceed with deployment? (y/n)
```

### Comparison Command

```bash
$ sagaz compare-cost

📊 Cost Comparison (10,000 saga executions/month)
═══════════════════════════════════════════════════════════════

Platform                  Setup           Monthly Cost
─────────────────────────────────────────────────────────────
AWS Step Functions        None            ~$250
Temporal Cloud            None            ~$200
Azure Durable Functions   None            ~$150
─────────────────────────────────────────────────────────────
Sagaz (Fully Managed)     15 min          ~$180
Sagaz (Hybrid)            15 min          ~$75
Sagaz (Self-Hosted)       30 min          ~$0*
─────────────────────────────────────────────────────────────

* Self-hosted: Only compute costs (your existing infra)

✅ Sagaz advantages over alternatives:
   • Exactly-once guarantees (Step Functions doesn't have)
   • Transactional outbox (neither has this)
   • No vendor lock-in
   • Sub-10ms event publishing
```

---

## Phase 2: Documentation & Community (Q1-Q2 2025)

### Documentation Goals

1. **"5-Minute Quickstart"**
   - Video walkthrough (YouTube/Loom)
   - Uses `sagaz init --local`
   - Shows working saga with monitoring
   - Linked from GitHub README

2. **"Why Sagaz > Alternatives"**
   - Head-to-head comparison table
   - Cost calculator (interactive)
   - Performance benchmarks
   - Migration guides FROM Step Functions/Temporal

3. **"Production Checklist"**
   - Security hardening
   - HA configuration
   - Backup strategies
   - Disaster recovery

### Competitive Comparison

Create this table for homepage:

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

### Community Launch

- [ ] Hacker News "Show HN" post
- [ ] Reddit: r/python, r/devops, r/aws
- [ ] Python Weekly newsletter submission
- [ ] Dev.to article series
- [ ] YouTube demo video

---

## Phase 3: Framework Integrations (Q2 2025)

### Official Integrations

```bash
pip install sagaz-fastapi   # FastAPI middleware
pip install sagaz-django    # Django integration
pip install sagaz-celery    # Celery orchestration
```

**sagaz-fastapi:**
```python
from fastapi import FastAPI
from sagaz.fastapi import SagazMiddleware

app = FastAPI()
app.add_middleware(SagazMiddleware, config=saga_config)

@app.post("/orders")
async def create_order(order: OrderRequest):
    result = await order_saga.execute(order.dict())
    return {"saga_id": result.saga_id}
```

**sagaz-django:**
```python
# settings.py
INSTALLED_APPS = [
    ...
    'sagaz.django',
]

SAGAZ = {
    'DATABASE': 'default',
    'BROKER': 'redis://localhost:6379',
}
```

### Saga Templates

Pre-built patterns for common use cases:

```bash
sagaz add template payment      # Stripe payment saga
sagaz add template order        # E-commerce order saga
sagaz add template notification # Multi-channel notification
sagaz add template approval     # Approval workflow
```

---

## Phase 4: Managed Offering (Q3-Q4 2025)

### Tier Structure

| Tier | Price | Target | Features |
|------|-------|--------|----------|
| **Community** | Free | Learners | Self-hosted, community support |
| **Developer** | $0-5/mo | Indie devs | Hosted dev env, 1k exec/mo |
| **Pro** | $49/mo | Startups | 10k exec, auto-scaling, email support |
| **Enterprise** | Custom | Enterprise | SLA, dedicated, on-prem option |

### Technical Implementation

**Sagaz Cloud Architecture:**
```
┌─────────────────────────────────────────────────────────────────┐
│                     Sagaz Cloud Platform                         │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  Control    │  │   Data      │  │  Compute    │              │
│  │   Plane     │  │   Plane     │  │  Plane      │              │
│  ├─────────────┤  ├─────────────┤  ├─────────────┤              │
│  │ • Auth      │  │ • PostgreSQL│  │ • Workers   │              │
│  │ • Billing   │  │ • Redis     │  │ • CDC       │              │
│  │ • Dashboard │  │ • Kafka     │  │ • Outbox    │              │
│  │ • CLI API   │  │ • Fluss     │  │ • Analytics │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
├─────────────────────────────────────────────────────────────────┤
│  Tenant Isolation: Schema-per-tenant or dedicated instances      │
└─────────────────────────────────────────────────────────────────┘
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

## Quick Wins Checklist (Next 30 Days)

### Week 1: CLI Foundation
- [ ] Create `sagaz-cli` Python package structure
- [ ] Implement `sagaz init --local` with Docker Compose
- [ ] Interactive wizard with Rich library
- [ ] Generate working `sagaz.yaml`

### Week 2: Core Commands
- [ ] Implement `sagaz dev` (start containers)
- [ ] Implement `sagaz status` (health checks)
- [ ] Implement `sagaz logs` (log tailing)
- [ ] Create "Getting Started" README section

### Week 3: Documentation
- [ ] Record 5-minute quickstart video
- [ ] Create cost comparison calculator
- [ ] Write "Why Sagaz" comparison page
- [ ] Update GitHub README with CLI examples

### Week 4: Launch
- [ ] Submit to Hacker News
- [ ] Post to Reddit communities
- [ ] Submit to Python Weekly
- [ ] Create Dev.to launch article

---

## Related Documents

- [Technical Roadmap](ROADMAP.md) - Feature development timeline
- [ADR-011: CDC Support](architecture/adr/adr-011-cdc-support.md)
- [ADR-013: Fluss Analytics](architecture/adr/adr-013-fluss-iceberg-analytics.md)
- [Fluss Architecture](architecture/fluss-analytics.md)
- [DLQ Pattern](patterns/dead-letter-queue.md)
- [Multi-Sink Pattern](patterns/multi-sink-fanout.md)

---

## Appendix: Competitive Landscape

### AWS Step Functions
- **Strengths**: Easy for AWS users, managed
- **Weaknesses**: No exactly-once, JSON-based, expensive, AWS-only
- **Sagaz advantage**: 10x cheaper, Python-native, exactly-once

### Temporal
- **Strengths**: Mature, proven at scale, open source
- **Weaknesses**: Complex setup, resource-intensive, no outbox
- **Sagaz advantage**: Lighter weight, transactional outbox, simpler

### Azure Durable Functions
- **Strengths**: Serverless, Azure integration
- **Weaknesses**: Azure-only, no exactly-once, C#/JavaScript focus
- **Sagaz advantage**: Multi-cloud, Python-first, exactly-once

### Prefect/Dagster
- **Strengths**: Great for data pipelines
- **Weaknesses**: Not designed for distributed transactions
- **Sagaz advantage**: Purpose-built for transactions + compensation
