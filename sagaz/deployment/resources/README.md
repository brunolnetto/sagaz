# Sagaz Resources Directory Structure

**Version:** 1.1.0  
**Last Updated:** 2025-12-30

---

## 📁 Directory Structure

```
sagaz/resources/
├── local/                          # Local development resources
│   ├── postgres/                   # HA PostgreSQL (primary + replica + PgBouncer)
│   │   ├── docker-compose.yaml     # Complete HA setup
│   │   ├── init-primary.sh         # Primary initialization
│   │   ├── README.md               # Usage guide
│   │   ├── partitioning/           # SQL migrations
│   │   │   ├── 001_create_partitioned_tables.sql
│   │   │   ├── 002_partition_maintenance_functions.sql
│   │   │   └── 003_initial_partitions.sql
│   │   └── monitoring/
│   │       └── prometheus.yml      # Metrics config
│   │
│   ├── redis/                      # Redis (default broker)
│   │   ├── docker-compose.yaml
│   │   └── monitoring/
│   │       └── prometheus.yml
│   │
│   ├── kafka/                      # Kafka broker
│   │   ├── docker-compose.yaml
│   │   └── monitoring/
│   │       └── prometheus.yml
│   │
│   └── rabbitmq/                   # RabbitMQ broker
│       ├── docker-compose.yaml
│       └── monitoring/
│           └── prometheus.yml
│
├── k8s/                            # Kubernetes production resources
│   ├── postgresql-ha.yaml          # StatefulSet (primary + replicas)
│   ├── pgbouncer.yaml              # Connection pooling (RW/RO pools + HPA)
│   ├── postgresql.yaml             # Single-node PostgreSQL (non-HA)
│   ├── outbox-worker.yaml          # Outbox worker deployment
│   ├── configmap.yaml              # Application config
│   ├── secrets-example.yaml        # Secrets template
│   ├── migration-job.yaml          # Database migration job
│   └── prometheus-monitoring.yaml  # Monitoring stack
│
└── sagaz.yaml.template             # Application config template
```

---

## 🗂️ Usage by Deployment Type

### Local Development (Docker Compose)

**Default (Redis):**
```bash
sagaz init --local
# Copies: local/redis/docker-compose.yaml
```

**HA PostgreSQL:**
```bash
sagaz init --with-ha
# Copies: local/postgres/docker-compose.yaml
#         local/postgres/init-primary.sh
#         local/postgres/partitioning/*.sql
#         local/postgres/monitoring/prometheus.yml
```

**Other Brokers:**
```bash
sagaz init --preset kafka
# Copies: local/kafka/docker-compose.yaml
#         local/kafka/monitoring/prometheus.yml

sagaz init --preset rabbitmq
# Copies: local/rabbitmq/docker-compose.yaml
#         local/rabbitmq/monitoring/prometheus.yml
```

### Kubernetes (Production)

**Standard PostgreSQL:**
```bash
sagaz init --k8s
# Copies: k8s/postgresql.yaml
#         k8s/outbox-worker.yaml
#         k8s/configmap.yaml
#         k8s/secrets-example.yaml
#         k8s/migration-job.yaml
#         k8s/prometheus-monitoring.yaml (if --with-monitoring)
```

**HA PostgreSQL:**
```bash
sagaz init --k8s --with-ha
# Copies: k8s/postgresql-ha.yaml (StatefulSet with replicas)
#         k8s/pgbouncer.yaml (RW/RO pools)
#         local/postgres/partitioning/*.sql (as ConfigMap)
#         k8s/outbox-worker.yaml
#         k8s/configmap.yaml
#         k8s/secrets-example.yaml
#         k8s/migration-job.yaml
#         k8s/prometheus-monitoring.yaml (if --with-monitoring)
```

---

## 🔄 Migration from Old Structure

**Old structure (pre-v1.1.0):**
```
sagaz/resources/
├── local-postgres/
├── local-redis/
├── local-kafka/
├── local-rabbitmq/
└── k8s/
```

**New structure (v1.1.0+):**
```
sagaz/resources/
├── local/
│   ├── postgres/
│   ├── redis/
│   ├── kafka/
│   └── rabbitmq/
└── k8s/
```

**Migration steps:**
```bash
cd sagaz/resources
mkdir -p local
mv local-postgres local/postgres
mv local-redis local/redis
mv local-kafka local/kafka
mv local-rabbitmq local/rabbitmq
```

**Updated in v1.1.0:**
- ✅ CLI code (`cli_app.py`) - uses `local/{preset}` paths
- ✅ Documentation links - updated to new paths
- ✅ No user-facing changes - `sagaz init` commands remain the same

---

## 📋 Resource File Descriptions

### Local Development

| File | Purpose |
|------|---------|
| **docker-compose.yaml** | Complete service stack (DB, broker, monitoring) |
| **init-primary.sh** | PostgreSQL primary initialization (HA only) |
| **partitioning/*.sql** | Table partitioning setup (HA PostgreSQL only) |
| **monitoring/prometheus.yml** | Metrics scraping configuration |
| **README.md** | Setup and usage guide (postgres only) |

### Kubernetes

| File | Purpose |
|------|---------|
| **postgresql-ha.yaml** | StatefulSet with primary + replicas |
| **pgbouncer.yaml** | Connection pooling deployments with HPA |
| **postgresql.yaml** | Single-node PostgreSQL (simple deployments) |
| **outbox-worker.yaml** | Outbox worker deployment |
| **configmap.yaml** | Application configuration |
| **secrets-example.yaml** | Credentials template |
| **migration-job.yaml** | One-time migration job |
| **prometheus-monitoring.yaml** | Monitoring stack (optional) |

---

## 🎯 Design Principles

1. **Separation of Concerns**
   - `local/` for development environments
   - `k8s/` for production Kubernetes

2. **Preset-Based Organization**
   - Each broker has its own subdirectory
   - Easy to add new presets (e.g., `local/nats/`)

3. **Consistent Structure**
   - All presets use same file naming
   - Monitoring configs in `monitoring/` subdirectory

4. **No Duplication**
   - Partitioning SQL used by both local and K8s
   - Single source of truth for each resource type

5. **Backward Compatibility**
   - CLI commands unchanged
   - Migration path documented

---

## 🚀 Adding New Presets

To add a new broker preset (e.g., NATS):

1. Create directory structure:
   ```bash
   mkdir -p sagaz/resources/local/nats/monitoring
   ```

2. Add `docker-compose.yaml`:
   ```yaml
   version: '3.8'
   services:
     nats:
       image: nats:latest
       ports:
         - "4222:4222"
       # ...
   ```

3. Add monitoring config:
   ```yaml
   # monitoring/prometheus.yml
   scrape_configs:
     - job_name: 'nats'
       # ...
   ```

4. Update CLI:
   ```python
   # cli_app.py
   @click.option(
       "--preset",
type=click.Choice(["redis", "kafka", "rabbitmq", "nats", "postgres"]),
       # ...
   )
   ```

5. Test:
   ```bash
   sagaz init --preset nats
   ```

---

## 📚 Documentation Links

- **Architecture:** [docs/architecture/README.md](../docs/architecture/README.md)
- **HA PostgreSQL Guide:** [local/postgres/README.md](local/postgres/README.md)
- **Quick Reference:** [docs/guides/ha-postgres-quickref.md](../docs/guides/ha-postgres-quickref.md)
- **Implementation Summary:** [docs/architecture/ha-postgres-implementation.md](../docs/architecture/ha-postgres-implementation.md)

---

**Questions?** Open an issue: https://github.com/brunolnetto/sagaz/issues

## Cloud deployment (`sagaz deploy`)

- `infra/aws/`: Terraform module, ECS Fargate + RDS PostgreSQL + ElastiCache Redis
- `infra/gcp/`: Terraform module, Cloud Run worker pool + Cloud SQL + Memorystore
- `charts/sagaz/`: Helm chart for the outbox worker

Used by `sagaz deploy --provider aws|gcp|k8s` and `sagaz teardown`. See
`docs/guides/cloud-deployment.md`.
