# Sagaz - Scalable PostgreSQL HA Deployment

## 🎯 Overview

This directory contains the complete implementation of **High-Availability PostgreSQL** infrastructure for Sagaz, enabling:

- **OLTP/OLAP Separation** - Dedicated read/write pools for optimal performance
- **Horizontal Scalability** - Auto-scaling read replicas and connection pools
- **Table Partitioning** - Time-based partitioning for efficient data management
- **Easy Deployment** - One-command setup for local and Kubernetes environments

---

## 📁 Documentation Structure

### Architecture & Planning

| File | Description |
|------|-------------|
| [**scalable-deployment-plan.md**](scalable-deployment-plan.md) | 📋 Detailed architecture plan, component breakdown, and rollout strategy |
| [**ha-postgres-implementation.md**](ha-postgres-implementation.md) | ✅ Implementation summary with files created and deployment guide |
| [**overview.md**](overview.md) | 🏗️ Overall Sagaz architecture (includes HA PostgreSQL section) |

### Quick Reference & Guides

| File | Description |
|------|-------------|
| [**ha-postgres-quickref.md**](../guides/ha-postgres-quickref.md) | ⚡ Quick reference for operators (commands, troubleshooting, monitoring) |
| [**local-postgres/README.md**](../../sagaz/resources/local/postgres/README.md) | 🐳 Local Docker Compose setup guide with examples |

### Related Decisions

| File | Description |
|------|-------------|
| [**decisions.md**](decisions.md) | 📖 Architecture decision records |
| [**adr/adr-011-cdc-support.md**](adr/adr-011-cdc-support.md) | 🚀 Future CDC integration plan |

---

## 🚀 Quick Start

### Local Development (Docker Compose)

```bash
# Initialize HA PostgreSQL setup
sagaz init --with-ha

# Start all services (primary + replica + PgBouncer + monitoring)
docker-compose up -d

# Check status
docker-compose ps

# View partition statistics
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "SELECT * FROM get_partition_statistics();"
```

**Result:** Running PostgreSQL cluster with:
- Primary (writes): `localhost:5432`
- Replica (reads): `localhost:5433`
- PgBouncer-RW (write pool): `localhost:6432` ⭐ Use this for saga executions
- PgBouncer-RO (read pool): `localhost:6433` ⭐ Use this for analytics/dashboards

### Kubernetes (Production)

```bash
# Initialize K8s manifests with HA
sagaz init --k8s --with-ha

# Deploy to cluster
kubectl create namespace sagaz
kubectl apply -f k8s/secrets-example.yaml  # Edit passwords first!
kubectl apply -f k8s/postgresql-ha.yaml
kubectl apply -f k8s/pgbouncer.yaml

# Monitor deployment
kubectl get pods -n sagaz -w
```

**Result:** StatefulSet with:
- 1 Primary pod (pod-0) - accepts writes
- 2+ Replica pods (pod-1, pod-2, ...) - serve reads
- PgBouncer write pool (2 replicas) - `pgbouncer-rw:6432`
- PgBouncer read pool (3+ replicas with HPA) - `pgbouncer-ro:6433`

---

## 🏗️ Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Application Layer                         │
│  ┌──────────────────┐                 ┌──────────────────┐       │
│  │  Saga Workers    │                 │  Analytics/      │       │
│  │  (OLTP writes)   │                 │  Dashboards      │       │
│  └────────┬─────────┘                 └────────┬─────────┘       │
└───────────┼──────────────────────────────────┼─────────────────┘
            │                                  │
   ┌────────▼──────────┐            ┌──────────▼──────────┐
   │  PgBouncer-RW     │            │  PgBouncer-RO       │
   │  (Transaction)    │            │  (Session)          │
   │  Port: 6432       │            │  Port: 6433         │
   └────────┬──────────┘            └──────────┬──────────┘
            │                                  │
      ┌─────▼──────────────────────────────────▼──────┐
      │         PostgreSQL Primary                    │
      │  - OLTP transactions                          │
      │  - Partitioned tables (monthly/daily)         │
      │  - Port: 5432                                 │
      └─────┬─────────────────────────────────────────┘
            │ (streaming replication)
            │
   ┌────────▼──────────┐          ┌─────────────────┐
   │  Replica 1        │          │  Replica 2      │
   │  OLAP queries     │          │  OLAP queries   │
   │  Port: 5432       │          │  Port: 5432     │
   └───────────────────┘          └─────────────────┘
```

**Key Features:**
- ✅ Read/Write separation (OLTP vs OLAP)
- ✅ Connection pooling (25-50 connections vs 200-300 clients)
- ✅ Streaming replication (< 5 second lag)
- ✅ Table partitioning (50-80% query speedup on time-ranges)
- ✅ Auto-scaling (Kubernetes HPA for read pool)

---

## 📊 Components Summary

### 1. PostgreSQL Primary
- **Purpose:** All write operations (saga state, outbox events)
- **Features:** Partitioned tables, streaming replication enabled
- **Connection:** Direct (`5432`) or via PgBouncer (`6432`)

### 2. PostgreSQL Replicas
- **Purpose:** Read-only queries (analytics, dashboards, reporting)
- **Features:** Streaming replication from primary, read-only mode
- **Connection:** Direct (`5433` local) or via PgBouncer (`6433`)

### 3. PgBouncer Write Pool
- **Mode:** Transaction pooling (fast, stateless)
- **Use:** Saga executions, outbox inserts, short transactions
- **Performance:** 10-20x more clients than DB connections

### 4. PgBouncer Read Pool
- **Mode:** Session pooling (supports long queries)
- **Use:** Grafana dashboards, analytics, reporting
- **Scaling:** Auto-scales 2-10 replicas (K8s HPA)

### 5. Table Partitioning
- **saga_executions:** Monthly partitions, 12-month retention
- **saga_outbox:** Daily partitions, 30-day retention
- **saga_audit_log:** Monthly partitions, 12-month retention
- **Maintenance:** Automated via `maintain_all_partitions()` function

---

## 🛠️ Management Commands

### Partition Management

```sql
-- View statistics
SELECT * FROM get_partition_statistics();

-- Create partitions manually
SELECT create_saga_executions_partition('2025-12-01'::DATE);
SELECT create_saga_outbox_partition('2025-12-15'::DATE);

-- Full maintenance (create + drop + analyze)
SELECT * FROM maintain_all_partitions();

-- Cleanup old inbox entries
SELECT cleanup_consumer_inbox(90);  -- Keep 90 days
```

### Replication Monitoring

```bash
# Check replication status
docker-compose exec postgres-primary psql -U postgres -c \
  "SELECT * FROM pg_stat_replication;"

# Check replication lag
kubectl exec -it -n sagaz postgresql-0 -- psql -U postgres -c \
  "SELECT client_addr, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes FROM pg_stat_replication;"
```

### PgBouncer Monitoring

```bash
# View pool statistics
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW POOLS;"
psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW STATS;"

# Kubernetes
kubectl exec -it -n sagaz pgbouncer-rw-xxx -- \
  psql -h 127.0.0.1 -p 5432 -U postgres -d pgbouncer -c "SHOW POOLS;"
```

---

## 📈 Performance Targets

| Metric | Target | Method |
|--------|--------|--------|
| Write latency (p99) | < 50ms | Via PgBouncer-RW |
| Read latency (p95) | < 200ms | Via PgBouncer-RO + replicas |
| Replication lag (p99) | < 5 seconds | Streaming replication |
| Outbox throughput | 5K events/sec | Partitioned outbox + pooling |
| Query speedup (time-range) | 50-80% | Partition pruning |

---

## 🧪 Testing

### Quick Validation

```bash
# Test partitioning
docker-compose exec postgres-primary psql -U postgres -d sagaz <<EOF
-- Insert test data
INSERT INTO saga_executions (saga_name, status) VALUES ('test', 'SUCCESS');

-- Verify partition pruning (should show 1 partition scanned)
EXPLAIN (ANALYZE, BUFFERS) 
SELECT * FROM saga_executions WHERE created_at >= CURRENT_DATE;
EOF

# Test replication
docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
  "INSERT INTO saga_executions (saga_name, status) VALUES ('repl-test', 'SUCCESS');"

sleep 2  # Wait for replication

docker-compose exec postgres-replica psql -U postgres -d sagaz -c \
  "SELECT COUNT(*) FROM saga_executions WHERE saga_name = 'repl-test';"
# Should return: 1
```

---

## 🚨 Troubleshooting

See [**ha-postgres-quickref.md**](../guides/ha-postgres-quickref.md) for detailed troubleshooting scenarios.

**Common Issues:**
- **Replica not syncing** → Check `pg_stat_replication`, restart replica
- **Pool exhaustion** → Increase `DEFAULT_POOL_SIZE`, kill idle clients
- **Partition creation failed** → Re-run migrations manually
- **Out of disk** → Drop old partitions, run cleanup

---

## 📚 Further Reading

### Deep Dives
- [Scalable Deployment Plan](scalable-deployment-plan.md) - Complete architecture design
- [Implementation Summary](ha-postgres-implementation.md) - What was built & how

### Operations
- [HA PostgreSQL Quick Reference](../guides/ha-postgres-quickref.md) - Operator handbook
- [Local Development Guide](../../sagaz/resources/local/postgres/README.md) - Docker Compose setup

### Related Architecture
- [Architecture Overview](overview.md) - Overall Sagaz architecture
- [Dataflow Documentation](dataflow.md) - Event flow patterns
- [Design Decisions](decisions.md) - Why we made these choices

---

## 🗺️ Roadmap

### v1.1.0 (Current)
- ✅ HA PostgreSQL with read replicas
- ✅ PgBouncer connection pooling
- ✅ Table partitioning
- ✅ Automated partition maintenance
- ✅ Docker Compose + Kubernetes deployments

### v1.2.0 (Planned)
- [ ] **Unified Storage Layer** - [Implementation Plan](unified-storage-implementation-plan.md)
- [ ] Redis Outbox Storage (completes Redis as full backend)
- [ ] Storage-to-storage data transfer
- [ ] SQLite backend for local/embedded use
- [ ] Patroni/Stolon for automatic failover
- [ ] PgBouncer metrics exporters
- [ ] Pre-built Grafana dashboards

### v1.3.0 (Future)
- [ ] CDC support (Debezium + Kafka)
- [ ] Multi-region replication
- [ ] Connection pool auto-tuning
- [ ] Automated performance optimization

---

## ❓ Support

**Questions?** → Open an issue: https://github.com/brunolnetto/sagaz/issues  
**Bugs?** → Include logs and environment details  
**Feature Requests?** → Tag with `enhancement`

**Community:** See [CONTRIBUTING.md](../../CONTRIBUTING.md) for contribution guidelines

---

**Built for production-grade distributed systems** 🚀
