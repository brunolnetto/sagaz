# Scalable Deployment Architecture Plan

**Created:** 2025-12-30  
**Status:** Implementation Roadmap  
**Target Version:** v1.1.0

## Objective

Organize Sagaz deployment architecture to support:
1. **OLTP** (transactional saga orchestration) - Write-optimized
2. **OLAP** (analytics & reporting) - Read-optimized
3. **Easy deployment** across local Docker Compose and Kubernetes
4. **Horizontal scalability** with connection pooling and read replicas
5. **Vertical scalability** with table partitioning

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        Application Layer                          │
│  ┌──────────────────┐           ┌──────────────────┐             │
│  │  Outbox Workers  │           │  Analytics Apps  │             │
│  │  (OLTP writes)   │           │  (OLAP reads)    │             │
│  └────────┬─────────┘           └────────┬─────────┘             │
└───────────┼──────────────────────────────┼────────────────────────┘
            │                              │
   ┌────────▼──────────┐          ┌────────▼──────────┐
   │  PgBouncer (RW)   │          │ PgBouncer (RO)    │
   │  Transaction Pool │          │  Session Pool     │
   └────────┬──────────┘          └────────┬──────────┘
            │                              │
      ┌─────▼──────────────────────────────▼──────┐
      │         PostgreSQL Primary                 │
      │  - Saga executions (partitioned by date)   │
      │  - Outbox events (partitioned by date)     │
      │  - Consumer inbox (idempotency)            │
      │  - Compensation graph state                │
      └─────┬──────────────────────────────────────┘
            │ (streaming replication)
            │
   ┌────────▼──────────┐          ┌─────────────────┐
   │  Read Replica 1   │          │  Read Replica 2 │
   │  (Analytics)      │          │  (Dashboards)   │
   └───────────────────┘          └─────────────────┘
```

---

## Components Breakdown

### 1. PostgreSQL Primary (OLTP)
**Purpose:** Handle all write operations (saga state, outbox, inbox)

**Configuration:**
- Connection pooling via PgBouncer (transaction mode)
- Partitioned tables (time-based)
- Write-optimized indexes
- Synchronous replication to 1+ read replicas

**Tables:**
```sql
-- Partitioned by execution date (monthly)
saga_executions (
    saga_id UUID,
    status VARCHAR,
    context JSONB,
    created_at TIMESTAMP,
    ...
) PARTITION BY RANGE (created_at);

-- Partitioned by creation date (daily)
saga_outbox (
    id BIGSERIAL,
    event_id UUID,
    topic VARCHAR,
    payload JSONB,
    status VARCHAR,
    created_at TIMESTAMP,
    ...
) PARTITION BY RANGE (created_at);

-- Idempotency table (no partitioning - needs fast lookups)
consumer_inbox (
    event_id UUID PRIMARY KEY,
    consumer_name VARCHAR,
    processed_at TIMESTAMP,
    result JSONB
);
```

### 2. PostgreSQL Read Replicas (OLAP)
**Purpose:** Serve analytics queries, dashboards, reporting

**Configuration:**
- Async streaming replication from primary
- 1-2 replicas (auto-scale based on CPU)
- Read-optimized indexes (aggregation-focused)
- Connection pooling via PgBouncer (session mode)

**Use Cases:**
- Grafana dashboards (saga health metrics)
- Saga execution history queries
- Event audit logs
- Reporting APIs

### 3. PgBouncer (Connection Pooling)
**Two instances:**

**PgBouncer-RW (Primary):**
- Pool mode: `transaction` (for OLTP)
- Max connections: 100
- Default pool size: 25
- Targets: PostgreSQL primary

**PgBouncer-RO (Replicas):**
- Pool mode: `session` (for OLAP long queries)
- Max connections: 200
- Default pool size: 50
- Targets: Read replicas (round-robin)

---

## Deployment Scenarios

### Scenario 1: Local Development (Docker Compose)

**File:** `sagaz/resources/local-postgres/docker-compose.yaml`

**Services:**
- `postgres-primary` (1 container)
- `postgres-replica` (1 container, streaming from primary)
- `pgbouncer-rw` (connection pool for writes)
- `pgbouncer-ro` (connection pool for reads)
- `postgres-init` (runs partitioning migration)

**Init command:**
```bash
sagaz init --local --preset postgres
```

**Environment variables:**
```bash
# Application writes
SAGAZ_STORAGE_URL=postgresql://pgbouncer-rw:6432/sagaz

# Analytics reads
SAGAZ_ANALYTICS_URL=postgresql://pgbouncer-ro:6432/sagaz
```

### Scenario 2: Kubernetes (Production)

**Manifests:**
- `k8s/postgresql-ha.yaml` - StatefulSet with 1 primary + 2 replicas
- `k8s/pgbouncer-rw.yaml` - Deployment for write pool
- `k8s/pgbouncer-ro.yaml` - Deployment for read pool (with HPA)
- `k8s/postgresql-partitioning-job.yaml` - CronJob for partition maintenance

**Init command:**
```bash
sagaz init --k8s --with-ha
```

**Services:**
```yaml
# Write traffic
postgresql-primary:5432 → StatefulSet pod-0

# Read traffic (load-balanced)
postgresql-read:5432 → StatefulSet pod-1, pod-2

# Application uses
pgbouncer-rw:6432 → postgresql-primary:5432
pgbouncer-ro:6432 → postgresql-read:5432
```

### Scenario 3: Self-Hosted (VMs/Bare Metal)

**File:** `sagaz/resources/selfhost/postgresql-ha.sh`

**Components:**
- Primary PostgreSQL instance (systemd)
- 1+ replica instances (systemd)
- PgBouncer systemd services
- Repmgr for failover (optional)

**Init command:**
```bash
sagaz init --selfhost --with-ha
```

---

## Table Partitioning Strategy

### Why Partition?

1. **Query performance** - Partition pruning for time-range queries
2. **Maintenance** - Drop old partitions instead of DELETE
3. **Indexing** - Smaller indexes per partition
4. **Archival** - Move old partitions to cheaper storage

### Partitioning Scheme

**saga_executions:**
- Strategy: `RANGE` partitioning by `created_at`
- Interval: **Monthly** partitions
- Retention: Keep 12 months, archive older
- Indexes per partition: `(saga_id)`, `(status, created_at)`

**saga_outbox:**
- Strategy: `RANGE` partitioning by `created_at`
- Interval: **Daily** partitions (high volume)
- Retention: Keep 30 days, drop older (events already published)
- Indexes per partition: `(status, created_at)` for worker polling

**consumer_inbox:**
- **No partitioning** (needs fast `event_id` PK lookups)
- Retention: Periodic cleanup via scheduled job

### Automatic Partition Maintenance

**Kubernetes CronJob:**
```yaml
# Runs daily at 2 AM
apiVersion: batch/v1
kind: CronJob
metadata:
  name: postgresql-partition-maintenance
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: partition-maintenance
            image: postgres:16-alpine
            command:
            - psql
            - -c
            - "SELECT maintain_partitions();"
```

**SQL Function:**
```sql
CREATE OR REPLACE FUNCTION maintain_partitions()
RETURNS void AS $$
BEGIN
    -- Create next month's saga_executions partition
    -- Create next 7 days of saga_outbox partitions
    -- Drop partitions older than retention period
END;
$$ LANGUAGE plpgsql;
```

---

## Migration Path

### Phase 1: Create Partitioned Tables (v1.1.0)
1. Create new partitioned tables (`saga_executions_v2`, `saga_outbox_v2`)
2. Create partitioning maintenance functions
3. Create initial partitions (past 3 months + future 3 months)
4. Add indexes to all partitions

### Phase 2: Data Migration (Optional)
1. Copy existing data to partitioned tables
2. Validate data integrity
3. Swap tables via transaction

### Phase 3: Add Read Replicas
1. Deploy read replica(s)
2. Configure streaming replication
3. Deploy PgBouncer instances
4. Update application connection strings

### Phase 4: Monitoring & Tuning
1. Add Prometheus metrics for replication lag
2. Add alerts for partition maintenance failures
3. Monitor PgBouncer pool saturation
4. Tune autovacuum settings for partitions

---

## Files to Create/Update

### New Files

**Docker Compose:**
- `sagaz/resources/local-postgres/docker-compose.yaml` - Full HA setup
- `sagaz/resources/local-postgres/pgbouncer-rw.ini` - Write pool config
- `sagaz/resources/local-postgres/pgbouncer-ro.ini` - Read pool config
- `sagaz/resources/local-postgres/init-replica.sh` - Replica setup script
- `sagaz/resources/local-postgres/partitioning/init.sql` - Partitioning DDL

**Kubernetes:**
- `sagaz/resources/k8s/postgresql-ha.yaml` - StatefulSet with replicas
- `sagaz/resources/k8s/pgbouncer-rw.yaml` - Write pool deployment
- `sagaz/resources/k8s/pgbouncer-ro.yaml` - Read pool deployment + HPA
- `sagaz/resources/k8s/postgresql-partitioning-job.yaml` - Partition maintenance CronJob

**Self-Hosted:**
- `sagaz/resources/selfhost/postgresql-primary.service` - Systemd service
- `sagaz/resources/selfhost/postgresql-replica.service` - Systemd service
- `sagaz/resources/selfhost/pgbouncer-rw.service` - Systemd service
- `sagaz/resources/selfhost/pgbouncer-ro.service` - Systemd service
- `sagaz/resources/selfhost/setup-replication.sh` - Automated setup script

**SQL Migrations:**
- `sagaz/storage/postgresql/migrations/001_create_partitioned_tables.sql`
- `sagaz/storage/postgresql/migrations/002_partition_maintenance_functions.sql`
- `sagaz/storage/postgresql/migrations/003_initial_partitions.sql`

**Documentation:**
- `docs/guides/high-availability.md` - HA deployment guide
- `docs/guides/partitioning.md` - Partitioning strategy & maintenance
- `docs/guides/connection-pooling.md` - PgBouncer configuration guide

### Updated Files

**CLI:**
- `sagaz/cli_app.py` - Add `--with-ha` flag to `sagaz init`
- Add `sagaz partition create` command
- Add `sagaz partition list` command
- Add `sagaz partition cleanup` command

**Configuration:**
- `sagaz/config.py` - Add `analytics_storage_url` for read replicas
- Add `connection_pool_config` settings

**Storage:**
- `sagaz/storage/postgresql/storage.py` - Add read replica support
- Add partition-aware query methods

---

## CLI Commands

### New Commands

```bash
# Initialize with HA
sagaz init --local --with-ha
sagaz init --k8s --with-ha
sagaz init --selfhost --with-ha

# Partition management
sagaz partition create --table saga_executions --range 2025-01-01:2025-12-31
sagaz partition list
sagaz partition cleanup --older-than 12m

# Connection pool monitoring
sagaz status --pool
```

---

## Monitoring & Alerts

### Prometheus Metrics

```python
# Replication lag
sagaz_postgres_replication_lag_seconds{replica="replica-1"}

# Connection pool saturation
sagaz_pgbouncer_active_connections{pool="rw", database="sagaz"}
sagaz_pgbouncer_waiting_connections{pool="ro", database="sagaz"}

# Partition maintenance
sagaz_partition_maintenance_duration_seconds
sagaz_partition_maintenance_errors_total
```

### Grafana Alerts

1. **Replication lag > 30 seconds** - Warn
2. **Replication lag > 120 seconds** - Critical
3. **PgBouncer pool exhaustion** - 90% utilization for 5 min
4. **Partition maintenance failure** - Any failure

---

## Performance Targets

| Metric | Target | Current |
|--------|--------|---------|
| Saga execution write latency | < 50ms (p99) | ~50ms |
| Analytics query latency | < 200ms (p95) | N/A |
| Outbox worker throughput | 5K events/sec | ~1K/sec |
| PgBouncer overhead | < 1ms | TBD |
| Replication lag | < 5 seconds (p99) | N/A |
| Partition maintenance | < 10 seconds | N/A |

---

## Rollout Plan

### Week 1: Infrastructure Setup
- [ ] Create Docker Compose HA setup
- [ ] Create Kubernetes manifests (StatefulSet + PgBouncer)
- [ ] Write partitioning SQL migrations
- [ ] Add CLI commands for HA deployment

### Week 2: Testing & Validation
- [ ] Integration tests for read replicas
- [ ] Performance benchmarks (with/without partitioning)
- [ ] Failover testing (primary failure scenarios)
- [ ] Load testing with PgBouncer

### Week 3: Documentation & Release
- [ ] Write HA deployment guide
- [ ] Update CLI documentation
- [ ] Create video tutorial for `sagaz init --with-ha`
- [ ] Release v1.1.0-rc1 for community testing

### Week 4: Production Rollout
- [ ] Release v1.1.0
- [ ] Monitor adoption metrics
- [ ] Collect feedback & iterate

---

## Open Questions

1. **How many read replicas by default?**
   - Suggestion: Local (1), K8s (2), Self-hosted (1)

2. **Partition retention defaults?**
   - Suggestion: saga_executions (12 months), saga_outbox (30 days)

3. **Should we support TimescaleDB for hyper-tables?**
   - Defer to v1.2.0 as optional optimization

4. **PgBouncer version and Docker image?**
   - Suggestion: `edoburu/pgbouncer:latest` (popular image)

5. **Automated failover?**
   - Local: No (manual)
   - K8s: Yes (via StatefulSet + service selector)
   - Self-hosted: Optional (Repmgr or Patroni)

---

## Success Criteria

✅ Local `docker-compose up` creates HA PostgreSQL cluster  
✅ K8s `kubectl apply` deploys StatefulSet with replicas  
✅ Partitioning reduces query time by 50%+ on time-range scans  
✅ Read replicas handle 100% of analytics queries  
✅ PgBouncer reduces connection overhead by 30%+  
✅ Documentation is complete and tested  

---

## Next Steps

1. Review this plan with team
2. Create GitHub issue/epic for tracking
3. Start implementation with local Docker Compose
4. Expand to Kubernetes after validation

**Estimated effort:** 2-3 weeks (one developer)

---

**References:**
- [PostgreSQL Partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html)
- [PgBouncer Documentation](https://www.pgbouncer.org/)
- [Kubernetes StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [PostgreSQL Streaming Replication](https://www.postgresql.org/docs/current/warm-standby.html)
