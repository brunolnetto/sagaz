# Sagaz High-Availability PostgreSQL - Quick Reference

**Version:** 1.1.0  
**Last Updated:** 2025-12-30

---

## 🚀 Quick Start

### Local Development (Docker Compose)

```bash
# Initialize HA setup
sagaz init --with-ha

# Start all services (PostgreSQL primary + replica + PgBouncer + monitoring)
docker-compose up -d

# Wait for initialization (check logs)
docker-compose logs -f postgres-init

# Verify all services are running
docker-compose ps

# Check partition statistics
docker-compose exec postgres-primary psql -U postgres -d sagaz -c "SELECT * FROM get_partition_statistics();"
```

### Kubernetes (Production)

```bash
# Initialize K8s manifests with HA
sagaz init --k8s --with-ha

# Create namespace
kubectl create namespace sagaz

# Deploy secrets (edit k8s/secrets-example.yaml first)
kubectl apply -f k8s/secrets-example.yaml

# Deploy HA PostgreSQL (StatefulSet + PgBouncer)
kubectl apply -f k8s/postgresql-ha.yaml
kubectl apply -f k8s/pgbouncer.yaml

# Deploy outbox workers
kubectl apply -f k8s/outbox-worker.yaml

# Monitor deployment
kubectl get pods -n sagaz -w
```

---

## 📐 Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Application Layer                         │
│  ┌──────────────────┐                 ┌──────────────────┐       │
│  │  Saga Workers    │                 │  Analytics/      │       │
│  │  (OLTP writes)   │                 │  Dashboards      │       │
│  └────────┬─────────┘                 └────────┬─────────┘       │
└───────────┼──────────────────────────────────┼<br/>────────────────┘
            │                                  │
   ┌────────▼──────────┐            ┌──────────▼──────────┐
   │  PgBouncer-RW     │            │  PgBouncer-RO       │
   │  (Transaction)    │            │  (Session)          │
   │  Port: 6432       │            │  Port: 6433         │
   └────────┬──────────┘            └──────────┬──────────┘
            │                                  │
      ┌─────▼──────────────────────────────────▼──────┐
      │         PostgreSQL Primary (pod-0)            │
      │  - OLTP transactions                          │
      │  - Partitioned tables                         │
      │  - Port: 5432                                 │
      └─────┬─────────────────────────────────────────┘
            │ (streaming replication)
            │
   ┌────────▼──────────┐          ┌─────────────────┐
   │  Replica (pod-1)  │          │  Replica (pod-2) │
   │  OLAP queries     │          │  OLAP queries   │
   │  Port: 5432       │          │  Port: 5432     │
   └───────────────────┘          └─────────────────┘
```

### Services & Endpoints

| Component | Port | Purpose | Connection String |
|-----------|------|---------|-------------------|
| **postgres-primary** | 5432 | Write master | `postgresql://postgres:postgres@postgres-primary:5432/sagaz` |
| **postgres-replica** | 5433 (local)<br/>5432 (K8s) | Read replicas | `postgresql://postgres:postgres@postgres-replica:5433/sagaz` |
| **pgbouncer-rw** | 6432 | Write pool (transaction mode) | `postgresql://postgres:postgres@pgbouncer-rw:6432/sagaz` |
| **pgbouncer-ro** | 6433 | Read pool (session mode) | `postgresql://postgres:postgres@pgbouncer-ro:6433/sagaz` |

---

## 🗂️ Table Partitioning

### Partitioned Tables

| Table | Partition Interval | Retention | Purpose |
|-------|-------------------|-----------|---------|
| `saga_executions` | Monthly | 12 months | Saga state & history |
| `saga_outbox` | Daily | 30 days | Transactional outbox events |
| `saga_audit_log` | Monthly | 12 months | Audit trail |
| `consumer_inbox` | **Not partitioned** | 90 days | Idempotency (fast PK lookups) |

### Partition Naming

```sql
-- saga_executions partitions (monthly)
saga_executions_y2025m01  -- January 2025
saga_executions_y2025m02  -- February 2025
...

-- saga_outbox partitions (daily)
saga_outbox_y2025m01d15   -- January 15, 2025
saga_outbox_y2025m01d16   -- January 16, 2025
...

-- saga_audit_log partitions (monthly)
saga_audit_log_y2025m01   -- January 2025
...
```

### Partition Management Commands

```sql
-- View current partition statistics
SELECT * FROM get_partition_statistics();

-- Create new partition manually
SELECT create_saga_executions_partition('2025-12-01'::DATE);
SELECT create_saga_outbox_partition('2025-12-15'::DATE);

-- Run full maintenance (create future, drop old, analyze recent)
SELECT * FROM maintain_all_partitions();

-- Cleanup old inbox entries (90+ days)
SELECT cleanup_consumer_inbox(90);
```

---

## 🔧 PgBouncer Configuration

### Write Pool (pgbouncer-rw)

**Configuration:**
```ini
pool_mode = transaction     # Stateless, fast
max_client_conn = 200        # App connections
default_pool_size = 25       # Postgres connections
min_pool_size = 5            # Keep-alive
server_lifetime = 3600       # 1 hour
```

**Use for:**
- ✅ Saga executions
- ✅ Outbox inserts
- ✅ Inbox deduplication checks
- ✅ Short OLTP transactions

### Read Pool (pgbouncer-ro)

**Configuration:**
```ini
pool_mode = session          # Supports long queries
max_client_conn = 300        # More clients
default_pool_size = 50       # More connections
min_pool_size = 10           # Baseline
server_lifetime = 7200       # 2 hours
```

**Use for:**
- ✅ Grafana dashboards
- ✅ Analytics queries
- ✅ Reporting APIs
- ✅ Long-running SELECT queries

---

## 📊 Monitoring & Health Checks

### PgBouncer Monitoring

```bash
# View pool statistics (local)
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW POOLS;"
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW STATS;"

# K8s (exec into pod)
kubectl exec -it -n sagaz pgbouncer-rw-xxx -- psql -h 127.0.0.1 -p 5432 -U postgres -d pgbouncer -c "SHOW POOLS;"
```

### Replication Monitoring

```bash
# Check replication status (local)
docker-compose exec postgres-primary psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Check replication lag
docker-compose exec postgres-primary psql -U postgres -c "
  SELECT 
    client_addr, 
    state,
    pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS sending_lag_bytes,
    pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes
  FROM pg_stat_replication;
"

# Verify replica is in recovery mode
docker-compose exec postgres-replica psql -U postgres -c "SELECT pg_is_in_recovery();"  # Should return 't'
```

### Kubernetes Monitoring

```bash
# Check StatefulSet status
kubectl get statefulset postgresql -n sagaz

# Check pod status
kubectl get pods -n sagaz -l app=postgresql

# Check PgBouncer deployment
kubectl get deploy -n sagaz | grep pgbouncer

# View logs
kubectl logs -n sagaz postgresql-0  # Primary
kubectl logs -n sagaz postgresql-1  # Replica 1
kubectl logs -n sagaz -l app=pgbouncer,pool-type=write  # Write pool
```

---

## 🛠️ Common Operations

### Add/Remove Read Replicas

**Docker Compose:**
```yaml
# Edit docker-compose.yaml - add postgres-replica-2
```

**Kubernetes:**
```bash
# Scale StatefulSet
kubectl scale statefulset postgresql --replicas=5 -n sagaz

# Verify
kubectl get pods -n sagaz -l app=postgresql
```

### Manual Partition Creation

```sql
-- Create next month's saga_executions partition
SELECT create_saga_executions_partition('2025-02-01'::DATE);

-- Create next week of outbox partitions
SELECT create_saga_outbox_partition('2025-01-20'::DATE);
SELECT create_saga_outbox_partition('2025-01-21'::DATE);
-- ... repeat for 7 days
```

### Force Partition Maintenance

```bash
# Local
docker-compose exec postgres-primary psql -U postgres -d sagaz -c "SELECT * FROM maintain_all_partitions();"

# Kubernetes
kubectl exec -it -n sagaz postgresql-0 -- psql -U postgres -d sagaz -c "SELECT * FROM maintain_all_partitions();"
```

### Test Replication

```bash
# Insert on primary (local)
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "INSERT INTO saga_executions (saga_name, status) VALUES ('test-saga', 'SUCCESS');"

# Wait 1-2 seconds for replication
sleep 2

# Query from replica
docker-compose exec postgres-replica psql -U postgres -d sagaz -c \
  "SELECT COUNT(*) FROM saga_executions WHERE saga_name = 'test-saga';"
# Should return: 1
```

---

## 🚨 Troubleshooting

### Replica Not Syncing

**Symptoms:** Replication lag growing, replica not receiving updates

**Solution:**
```bash
# 1. Check primary's replication status
docker-compose exec postgres-primary psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# 2. Check replica logs
docker-compose logs postgres-replica | grep -i error

# 3. Restart replica
docker-compose restart postgres-replica

# 4. If still broken, re-clone from primary
docker-compose stop postgres-replica
docker volume rm local-postgres_postgres_replica_data
docker-compose up -d postgres-replica
```

### PgBouncer Pool Exhaustion

**Symptoms:** Connection errors, "no more connections allowed"

**Solution:**
```bash
# 1. Check pool status
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW POOLS;"

# 2. Kill idle connections
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW CLIENTS;"
# Note client IDs, then:
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "KILL <client_id>;"

# 3. Increase pool size (edit docker-compose.yaml)
# DEFAULT_POOL_SIZE: 50  # was 25
docker-compose up -d pgbouncer-rw
```

### Partition Creation Failed

**Symptoms:** postgres-init container errors

**Solution:**
```bash
# 1. Check init logs
docker-compose logs postgres-init

# 2. Manually run migrations
docker-compose exec postgres-primary psql -U postgres -d sagaz -f /partitioning/001_create_partitioned_tables.sql
docker-compose exec postgres-primary psql -U postgres -d sagaz -f /partitioning/002_partition_maintenance_functions.sql
docker-compose exec postgres-primary psql -U postgres -d sagaz -f /partitioning/003_initial_partitions.sql
```

### Out of Disk Space

**Solution:**
```bash
# 1. Drop old partitions manually
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "DROP TABLE saga_outbox_y2024m11d01 CASCADE;"

# 2. Run cleanup
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "SELECT maintain_all_partitions();"

# 3. Clean up inbox
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "SELECT cleanup_consumer_inbox(30);"  -- Keep only 30 days
```

---

## 📈 Performance Tuning

### Recommended Settings (postgresql.conf)

```ini
# Memory
shared_buffers = 1GB              # 25% of system RAM
effective_cache_size = 3GB        # 75% of system RAM
work_mem = 10MB                   # Per-operation memory
maintenance_work_mem = 256MB      # For VACUUM, index creation

# Checkpoints
checkpoint_completion_target = 0.9
wal_buffers = 16MB
min_wal_size = 1GB
max_wal_size = 4GB

# Query Planner
random_page_cost = 1.1            # For SSD
effective_io_concurrency = 200    # For SSD

# Connections
max_connections = 200             # + PgBouncer = many more clients

# Autovacuum (important for partitions!)
autovacuum_max_workers = 4
autovacuum_naptime = 10s
```

### Index Optimization

```sql
-- Add custom indexes if needed
CREATE INDEX idx_saga_custom ON saga_executions (saga_name, created_at DESC) 
  WHERE status IN ('RUNNING', 'PENDING');

-- Rebuild bloated indexes
REINDEX INDEX CONCURRENTLY idx_saga_executions_status_created;
```

---

## 📚 Additional Resources

- **Full Documentation:** [docs/architecture/scalable-deployment-plan.md](../../docs/architecture/scalable-deployment-plan.md)
- **Local Setup Guide:** [sagaz/resources/local/postgres/README.md](../../sagaz/resources/local/postgres/README.md)
- **Partitioning Guide:** [docs/guides/partitioning.md](../../docs/guides/partitioning.md) (TODO)
- **Connection Pooling Guide:** [docs/guides/connection-pooling.md](../../docs/guides/connection-pooling.md) (TODO)

---

## 🎯 Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Saga execution write latency | < 50ms (p99) | Via pgbouncer-rw |
| Analytics query latency | < 200ms (p95) | Via pgbouncer-ro |
| Replication lag | < 5 seconds (p99) | Local/K8s |
| PgBouncer overhead | < 1ms | Connection pooling |
| Partition maintenance | < 10 seconds | Daily cron job |

---

## ✅ Deployment Checklist

### Before Production

- [ ] Change all default passwords
- [ ] Enable PostgreSQL SSL/TLS
- [ ] Configure automated backups (pg_basebackup + WAL archiving)
- [ ] Set up monitoring alerts (replication lag, pool saturation)
- [ ] Test failover scenarios
- [ ] Load test with realistic traffic
- [ ] Review partition retention policies
- [ ] Configure external volumes (K8s persistent storage)
- [ ] Set up log aggregation (ELK/Loki)
- [ ] Document runbook for operations team

### Ongoing Maintenance

- [ ] Monitor partition growth weekly
- [ ] Review replication lag daily
- [ ] Check PgBouncer pool saturation
- [ ] Vacuum analyze partitions monthly
- [ ] Test backups & restore procedures
- [ ] Update PostgreSQL minor versions
- [ ] Audit security settings quarterly

---

**Questions or Issues?**  
Open an issue: https://github.com/brunolnetto/sagaz/issues

**Want to contribute?**  
See [CONTRIBUTING.md](../../CONTRIBUTING.md)
