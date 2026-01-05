# Sagaz High-Availability PostgreSQL Setup

Complete production-ready PostgreSQL deployment with:
- **Primary/Replica** streaming replication
- **PgBouncer** connection pooling (separate RW/RO pools)
- **Table partitioning** (time-based for scalability)
- **Monitoring** (Prometheus + Grafana)

---

## Quick Start

```bash
# 1. Start all services
docker-compose up -d

# 2. Wait for initialization (30-60 seconds)
docker-compose logs -f postgres-init

# 3. Verify services are healthy
docker-compose ps

# 4. Check partition setup
docker-compose exec postgres-primary psql -U postgres -d sagaz -c "SELECT * FROM get_partition_statistics();"

# 5. Open Grafana dashboard
open http://localhost:3000
```

---

## Architecture

```
Application
    │
    ├─► PgBouncer-RW (6432) ──► PostgreSQL Primary (5432)
    │                              │
    │                              │ (streaming replication)
    │                              ▼
    └─► PgBouncer-RO (6433) ──► PostgreSQL Replica (5433)
```

**OLTP (Write Traffic):**
- Application → `pgbouncer-rw:6432` → `postgres-primary:5432`
- Pool mode: `transaction` (fast, stateless)
- Use for: Saga executions, outbox writes, inbox checks

**OLAP (Read Traffic):**
- Dashboards → `pgbouncer-ro:6433` → `postgres-replica:5432`
- Pool mode: `session` (supports long queries)
- Use for: Analytics, Grafana dashboards, reporting

---

## Connection Strings

```bash
# OLTP - Write operations (saga orchestration)
SAGAZ_STORAGE_URL="postgresql://postgres:postgres@localhost:6432/sagaz"

# OLAP - Read operations (analytics, dashboards)
SAGAZ_ANALYTICS_URL="postgresql://postgres:postgres@localhost:6433/sagaz"

# Direct connections (for debugging)
POSTGRES_PRIMARY="postgresql://postgres:postgres@localhost:5432/sagaz"
POSTGRES_REPLICA="postgresql://postgres:postgres@localhost:5433/sagaz"
```

---

## Services

| Service | Port | Purpose | Health Check |
|---------|------|---------|--------------|
| `postgres-primary` | 5432 | Write master | `docker-compose exec postgres-primary pg_isready` |
| `postgres-replica` | 5433 | Read replica | `docker-compose exec postgres-replica pg_isready` |
| `pgbouncer-rw` | 6432 | Write pool | `psql -h localhost -p 6432 -U postgres -d pgbouncer -c 'SHOW POOLS;'` |
| `pgbouncer-ro` | 6433 | Read pool | `psql -h localhost -p 6433 -U postgres -d pgbouncer -c 'SHOW POOLS;'` |
| `postgres-init` | - | Partitioning setup | `docker-compose logs postgres-init` |
| `redis` | 6379 | Broker/Cache | `redis-cli ping` |
| `prometheus` | 9090 | Metrics | http://localhost:9090 |
| `grafana` | 3000 | Dashboards | http://localhost:3000 |

---

## Table Partitioning

### Partitioned Tables

**`saga_executions`** (monthly partitions)
```sql
-- Partition naming: saga_executions_y2025m01
-- Retention: 12 months
-- Indexes: (status, created_at), (saga_name, created_at)
```

**`saga_outbox`** (daily partitions)
```sql
-- Partition naming: saga_outbox_y2025m01d15
-- Retention: 30 days
-- Indexes: (status, created_at WHERE status='PENDING')
```

**`saga_audit_log`** (monthly partitions)
```sql
-- Partition naming: saga_audit_log_y2025m01
-- Retention: 12 months
-- Indexes: (saga_id, created_at), (event_type, created_at)
```

### Partition Management

```bash
# View current partitions
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "SELECT * FROM get_partition_statistics();"

# List all partitions
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "SELECT * FROM partition_metadata ORDER BY partition_start DESC;"

# Manual maintenance (create/drop partitions)
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "SELECT * FROM maintain_all_partitions();"

# Clean up old inbox entries (90+ days old)
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "SELECT cleanup_consumer_inbox(90);"
```

### Automated Maintenance

Partitions are auto-created and cleaned up via `maintain_all_partitions()`:
- **Creates:** Next 3 months (saga_executions), next 7 days (saga_outbox)
- **Drops:** Older than 12 months (executions), older than 30 days (outbox)

For production, schedule with `pg_cron`:
```sql
-- Daily maintenance at 2 AM
SELECT cron.schedule('sagaz-partition-maintenance', '0 2 * * *', 
  $$SELECT maintain_all_partitions();$$);
```

---

## PgBouncer Configuration

### Write Pool (pgbouncer-rw)

```ini
pool_mode = transaction       # Fast, stateless connections
max_client_conn = 200          # Max app connections
default_pool_size = 25         # Connections to PostgreSQL
min_pool_size = 5              # Minimum kept open
server_lifetime = 3600         # Recycle connection after 1 hour
```

**Best for:** Saga executions, outbox inserts, short transactions

### Read Pool (pgbouncer-ro)

```ini
pool_mode = session            # Supports long queries
max_client_conn = 300          # Higher for dashboard users
default_pool_size = 50         # More connections for analytics
min_pool_size = 10             # Baseline for dashboards
server_lifetime = 7200         # Longer lifetime for analytics
```

**Best for:** Grafana dashboards, reporting queries, analytics

### Monitoring PgBouncer

```bash
# View pool statistics
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW POOLS;"
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW STATS;"

# Kill idle connections
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "KILL client_id;"
```

---

## Replication Monitoring

```bash
# Check replication status on primary
docker-compose exec postgres-primary psql -U postgres -c \
  "SELECT * FROM pg_stat_replication;"

# Check replication lag
docker-compose exec postgres-primary psql -U postgres -c \
  "SELECT client_addr, state, 
          pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS sending_lag_bytes,
          pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes
   FROM pg_stat_replication;"

# Verify replica is in recovery mode
docker-compose exec postgres-replica psql -U postgres -c \
  "SELECT pg_is_in_recovery();"  -- Should return 't' (true)
```

**Expected lag:** < 1 second for local Docker setup

---

## Testing Partitions

```bash
# Insert test saga execution
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "INSERT INTO saga_executions (saga_name, status) VALUES ('test-saga', 'SUCCESS');"

# Verify partition was used (should show partition pruning)
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "EXPLAIN (ANALYZE, BUFFERS) 
   SELECT * FROM saga_executions 
   WHERE created_at >= CURRENT_DATE - INTERVAL '1 day';"

# Insert test outbox event
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "INSERT INTO saga_outbox (topic, payload, status) 
   VALUES ('test.topic', '{\"foo\": \"bar\"}'::jsonb, 'PENDING');"

# Verify event is visible on replica (tests replication)
sleep 2  # Wait for replication
docker-compose exec postgres-replica psql -U postgres -d sagaz -c \
  "SELECT COUNT(*) FROM saga_outbox WHERE status = 'PENDING';"
```

---

## Performance Testing

```bash
# Generate load (requires pgbench)
docker-compose exec postgres-primary pgbench -i -s 10 sagaz

# Run benchmark through PgBouncer
docker-compose exec postgres-primary pgbench -h pgbouncer-rw -p 5432 -U postgres -d sagaz -c 10 -j 2 -T 60

# Monitor connection pool
watch -n 1 "psql -h localhost -p 6432 -U postgres -d pgbouncer -c 'SHOW POOLS;'"
```

---

## Troubleshooting

### Replica Not Syncing

```bash
# Check primary WAL sender status
docker-compose exec postgres-primary psql -U postgres -c \
  "SELECT * FROM pg_stat_replication;"

# Check replica logs
docker-compose logs postgres-replica

# Restart replica
docker-compose restart postgres-replica
```

### PgBouncer Connection Errors

```bash
# Check pool status
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW POOLS;"

# Check for waiting clients
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW CLIENTS;"

# Increase pool size (edit docker-compose.yaml and restart)
docker-compose up -d pgbouncer-rw
```

### Partition Not Created

```bash
# Check for errors in init logs
docker-compose logs postgres-init

# Manually create partition
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "SELECT create_saga_executions_partition(CURRENT_DATE);"
```

### Out of Space

```bash
# Check disk usage
docker system df

# Drop old partitions manually
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "DROP TABLE saga_outbox_y2024m12d01;"

# Run cleanup
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "SELECT maintain_all_partitions();"
```

---

## Production Deployment

For production use:

1. **Change passwords** in `docker-compose.yaml` and `init-primary.sh`
2. **Enable SSL/TLS** for PostgreSQL connections
3. **Setup pg_cron** for automated partition maintenance
4. **Configure backup** (pg_basebackup, WAL archiving)
5. **Add monitoring alerts** (replication lag, pool saturation)
6. **Use external volumes** for data persistence

See Kubernetes deployment: `sagaz/resources/k8s/postgresql-ha.yaml`

---

## Cleanup

```bash
# Stop all services
docker-compose down

# Remove all data (WARNING: DESTRUCTIVE)
docker-compose down -v

# Remove only specific volume
docker volume rm local-postgres_postgres_primary_data
```

---

## Next Steps

- [ ] Deploy to production (Kubernetes or VM)
- [ ] Add automated backups (pg_basebackup + WAL archiving)
- [ ] Configure Grafana alerts for replication lag
- [ ] Tune autovacuum settings for partitions
- [ ] Add more read replicas for geographic distribution

---

**Documentation:**
- [Partitioning Strategy](../../../docs/guides/partitioning.md)
- [Connection Pooling Guide](../../../docs/guides/connection-pooling.md)
- [High Availability Guide](../../../docs/guides/high-availability.md)

**Support:** https://github.com/brunolnetto/sagaz/issues
