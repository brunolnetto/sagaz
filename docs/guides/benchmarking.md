# Benchmarking Guide

Measure and optimizesagaz outbox worker performance.

## Overview

This guide covers:
1. Running the standard test suite
2. High-throughput benchmarking
3. Interpreting results
4. Performance optimization

---

## Quick Benchmark

### Prerequisites

```bash
# Port-forward PostgreSQL (use 5433 if 5432 is in use)
kubectl port-forward -nsagaz svc/postgresql 5433:5432 &

# Install dependencies
pip install asyncpg rich
```

### Run Basic Tests

```bash
python scripts/k8s_cluster_test.py all
```

**Expected Output:**

```
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Test             ┃ Result ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ Basic Processing │ ✓ PASS │
│ Bulk Processing  │ ✓ PASS │
│ Idempotency      │ ✓ PASS │
│ Monitor          │ ✓ PASS │
└──────────────────┴────────┘
```

---

## High-Throughput Benchmark

For maximum throughput testing, run the benchmark **inside** the cluster to avoid port-forward bottleneck.

### Run In-Cluster Benchmark

```bash
# Scale down workers (to avoid contention)
kubectl scale deployment outbox-worker --replicas=0 -nsagaz

# Apply benchmark job
kubectl apply -f k8s/benchmark-job.yaml

# Watch logs
kubectl logs -f job/outbox-benchmark -nsagaz
```

### Benchmark Configuration

Edit `k8s/benchmark-job.yaml`:

```yaml
env:
  - name: NUM_EVENTS
    value: "100000"      # Total events to process
  - name: NUM_WORKERS
    value: "10"          # Parallel processing workers
  - name: BATCH_SIZE
    value: "500"         # Events per batch
```

---

## Benchmark Results

### Local (kind cluster, single node)

| Metric | Value |
|--------|-------|
| Events | 50,000 |
| Insert Rate | **1,806/sec** |
| Process Rate | **1,265/sec** |
| Time to 1M | ~13.2 min |

### Performance by Configuration

| Workers | Batch | Throughput |
|---------|-------|------------|
| 5 | 100 | ~400/sec |
| 10 | 500 | ~1,200/sec |
| 20 | 1000 | ~1,500/sec* |

*Higher worker counts may cause connection issues on single-node clusters.

---

## Performance Optimization

### 1. Increase Batch Size

```yaml
# k8s/configmap.yaml
data:
  WORKER_BATCH_SIZE: "500"  # Default: 100
```

### 2. Scale Workers

```bash
kubectl scale deployment outbox-worker --replicas=10 -nsagaz
```

### 3. Reduce Poll Interval

```yaml
data:
  WORKER_POLL_INTERVAL_SECONDS: "0.5"  # Default: 1.0
```

### 4. Increase DB Connection Pool

```yaml
# In worker deployment
env:
  - name: DB_POOL_SIZE
    value: "20"
```

---

## Bottleneck Analysis

### Database Bottlenecks

```sql
-- Check lock contention
SELECT * FROM pg_stat_activity 
WHERE wait_event_type = 'Lock';

-- Check pending events
SELECT status, COUNT(*) 
FROM saga_outbox 
GROUP BY status;
```

### Worker Bottlenecks

```bash
# Check CPU/memory usage
kubectl top pods -nsagaz

# Check worker logs for errors
kubectl logs -nsagaz -l app=outbox-worker --tail=100 | grep -i error
```

---

## Benchmark Comparison

### With RabbitMQ (Production Mode)

```
Events: 1,000
Time: 33.9s
Throughput: ~30 events/sec
```

### With In-Memory Broker (Benchmark Mode)

```
Events: 50,000
Time: 39.5s
Throughput: ~1,265 events/sec
```

**Conclusion:** RabbitMQ adds ~40x overhead. For higher throughput:
- Use Kafka (better batching)
- Increase batch size
- Use CDC instead of polling

---

## Production Expectations

| Environment | Expected Throughput |
|-------------|---------------------|
| Local (kind) | 1,000-2,000/sec |
| Small K8s (3 nodes) | 3,000-5,000/sec |
| Medium K8s (10 nodes) | 10,000-15,000/sec |
| Large K8s + Kafka | 20,000+/sec |

---

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `scripts/k8s_cluster_test.py` | Basic cluster tests |
| `scripts/high_throughput_benchmark.py` | Local high-throughput test |
| `k8s/benchmark-job.yaml` | In-cluster benchmark job |

---

## Related

- [Kubernetes Deployment](kubernetes.md)
- [Architecture Overview](../architecture/overview.md)
- [Dataflow](../architecture/dataflow.md)
