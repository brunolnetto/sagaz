# Sagaz Kubernetes Deployment

**Version:** 1.1.0  
**Structure:** Kustomize-based  
**Last Updated:** 2025-12-30

---

## 🚀 Quick Start

### Simple Deployment (Single PostgreSQL)

```bash
# Deploy base resources + simple PostgreSQL
kubectl apply -k k8s/base
kubectl apply -k k8s/database/simple

# Run migrations
kubectl apply -f k8s/jobs/migration-job.yaml

# Verify deployment
kubectl get pods -n sagaz
```

### HA Deployment (Primary + Replicas + PgBouncer)

```bash
# Deploy base resources + HA PostgreSQL
kubectl apply -k k8s/base
kubectl apply -k k8s/database/ha

# Run partition setup (included in HA deployment)
kubectl logs -n sagaz postgresql-0

# Verify replication
kubectl exec -n sagaz postgresql-0 -- psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Check PgBouncer pools
kubectl get deploy -n sagaz | grep pgbouncer
```

### Add Monitoring (Optional)

```bash
# Deploy Prometheus + Grafana
kubectl apply -k k8s/monitoring

# Access Grafana
kubectl port-forward -n sagaz-monitoring svc/grafana 3000:3000
# Open: http://localhost:3000
```

---

## 📁 Directory Structure

```
k8s/
├── README.md                        # This file
├── base/                            # Common resources (required)
│   ├── kustomization.yaml
│   ├── namespace.yaml               # Sagaz namespace
│   ├── configmap.yaml               # App configuration
│   ├── secrets.yaml                 # Credentials template
│   └── outbox-worker.yaml           # Outbox worker deployment
│
├── database/                        # Database deployment options
│   ├── simple/                      # Single-node PostgreSQL
│   │   ├── kustomization.yaml
│   │   └── postgresql.yaml
│   └── ha/                          # HA PostgreSQL
│       ├── kustomization.yaml
│       ├── postgresql-ha.yaml       # StatefulSet (primary + replicas)
│       ├── pgbouncer.yaml           # Connection pooling
│       └── partitioning/            # SQL migrations (auto-loaded)
│           ├── 001_create_partitioned_tables.sql
│           ├── 002_partition_maintenance_functions.sql
│           └── 003_initial_partitions.sql
│
├── jobs/                            # One-time or scheduled jobs
│   ├── migration-job.yaml           # Initial DB setup
│   └── benchmark-job.yaml           # Performance testing
│
└── monitoring/                      # Optional monitoring stack
    ├── README.md                    # Monitoring setup guide
    ├── kustomization.yaml
    ├── namespace.yaml               # sagaz-monitoring namespace
    ├── prometheus.yaml              # Metrics collection
    ├── grafana.yaml                 # Dashboards
    ├── dashboards/
    │   ├── main-dashboard.json      # Main Sagaz dashboard
    │   └── outbox-dashboard.json    # Outbox worker metrics
    └── alerts/
        ├── postgres-alerts.yaml     # PostgreSQL alerts
        └── outbox-alerts.yaml       # Outbox worker alerts
```

---

## 🛠️ Deployment Scenarios

### Scenario 1: Development/Testing (Minimal)

```bash
# Minimal deployment with single PostgreSQL
kubectl apply -k k8s/base
kubectl apply -k k8s/database/simple
kubectl apply -f k8s/jobs/migration-job.yaml
```

**Resources created:**
- Namespace: `sagaz`
- PostgreSQL: Single pod (no HA)
- Outbox Worker: 1 replica
- ConfigMap: Application config
- Secret: Database credentials

### Scenario 2: Production (HA + Monitoring)

```bash
# Full production deployment
kubectl apply -k k8s/base
kubectl apply -k k8s/database/ha
kubectl apply -k k8s/monitoring

# Wait for all pods
kubectl wait --for=condition=Ready pod -l app=postgresql -n sagaz --timeout=300s
kubectl wait --for=condition=Ready pod -l app=pgbouncer -n sagaz --timeout=120s
```

**Resources created:**
- Namespace: `sagaz`, `sagaz-monitoring`
- PostgreSQL: StatefulSet with 3 pods (1 primary, 2 replicas)
- PgBouncer: 2 deployments (RW pool, RO pool) with HPA
- Outbox Worker: 2 replicas with autoscaling
- Monitoring: Prometheus, Grafana, and alerting

### Scenario 3: Kubernetes-only (Production) 

```bash
# Use sagaz CLI
sagaz init --k8s --with-ha
cd k8s

# Deploy
kubectl apply -k base/
kubectl apply -k database/ha/
kubectl apply -k monitoring/  # optional
```

---

## 🔧 Configuration

### Secrets

Before deploying, edit `k8s/base/secrets.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: sagaz-db-credentials
  namespace: sagaz
type: Opaque
stringData:
  postgres-password: "CHANGE_THIS_PASSWORD"  # ⚠️ Required
  postgres-url: "postgresql://postgres:CHANGE_THIS_PASSWORD@postgresql-primary:5432/sagaz"
  analytics-url: "postgresql://postgres:CHANGE_THIS_PASSWORD@pgbouncer-ro:6433/sagaz"
```

### ConfigMap

Edit `k8s/base/configmap.yaml` for application settings:

```yaml
data:
  SAGAZ_LOG_LEVEL: "INFO"
  SAGAZ_METRICS_ENABLED: "true"
  SAGAZ_OUTBOX_BATCH_SIZE: "100"
  SAGAZ_OUTBOX_POLL_INTERVAL: "1000"  # milliseconds
```

---

## 📊 Kustomize Overlays

### Creating Custom Overlays

Create environment-specific configurations:

```bash
# Create staging overlay
mkdir -p k8s/overlays/staging
cat > k8s/overlays/staging/kustomization.yaml <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: sagaz-staging

bases:
  - ../../base
  - ../../database/ha

patchesStrategicMerge:
  - replica-count.yaml

replicas:
  - name: postgresql
    count: 2  # Fewer replicas for staging
EOF

# Deploy staging
kubectl apply -k k8s/overlays/staging
```

---

## 🚨 Troubleshooting

### StatefulSet Pods Not Starting

```bash
# Check StatefulSet status
kubectl get statefulset postgresql -n sagaz

# Check pod logs
kubectl logs -n sagaz postgresql-0
kubectl logs -n sagaz postgresql-1

# Check events
kubectl describe statefulset postgresql -n sagaz
```

## Monitoring & Observability

### Three Pillars of Observability

The sagaz monitoring stack provides complete observability through:

1. **Metrics** (Prometheus + Grafana) - Real-time performance and health metrics
2. **Traces** (OpenTelemetry + Jaeger/Tempo) - Distributed request tracing
3. **Logs** (Loki + Promtail + Grafana) - Centralized log aggregation and search

### Deploy Monitoring Stack

```bash
# Check PgBouncer logs
kubectl logs -n sagaz -l app=pgbouncer,pool-type=write

# Deploy complete monitoring stack (Grafana, Prometheus, Loki, Promtail)
kubectl apply -k monitoring/

# Verify deployment
kubectl get pods -n monitoring

# Access Grafana (port-forward)
kubectl port-forward -n monitoring svc/grafana 3000:3000

# Default credentials: admin / changeme (change in production!)
```

### Dashboards

Three pre-built Grafana dashboards are provided:

1. **Saga Orchestration Dashboard** - Monitor saga execution, success rates, latency, and compensations
2. **Outbox Pattern Dashboard** - Monitor event publishing, worker health, and queue metrics
3. **Logs Dashboard** - Centralized log search, error analysis, and saga timeline visualization

### Log Aggregation (Loki + Promtail)

The monitoring stack includes Loki for log aggregation with JSON log parsing:

```bash
# View logs in Grafana Explore
# Navigate to: Explore → Select "Loki" datasource

# Example LogQL queries:
{namespace="sagaz", saga_id="abc-123"}                    # All logs for a saga
{namespace="sagaz", level="ERROR"}                         # All error logs
{namespace="sagaz", correlation_id="req-xyz-789"}          # Logs by correlation ID
```

Key features:
- Automatic JSON log parsing
- Label extraction: `saga_id`, `saga_name`, `correlation_id`, `step_name`
- Correlation with metrics and traces
- 31-day retention (configurable)
- Full-text search across all logs

See `monitoring/README.md` for comprehensive LogQL query examples.

### Alerts

Comprehensive Prometheus alerts covering:
- **Critical**: Worker down, high lag, DLQ activity, saga failures
- **Warning**: High latency, elevated lag, resource usage
- **Info**: Worker idle, low throughput

See `monitoring/README.md` for detailed alert configuration.

### Runbooks

Operational runbooks with step-by-step troubleshooting:
- Saga high failure rate
- Stuck sagas
- Compensation failures  
- Outbox worker down
- High lag scenarios
- Dead letter queue handling
- Loki/Promtail issues

See `monitoring/RUNBOOKS.md` for complete procedures.

## Troubleshooting

For detailed troubleshooting procedures, see the [Monitoring Runbooks](monitoring/RUNBOOKS.md).

### Quick Checks

#### No events being processed

```bash
# Check init logs from postgresql-0
kubectl logs -n sagaz postgresql-0 | grep -i partition

# Manually apply partitioning (if needed)
kubectl exec -it -n sagaz postgresql-0 -- \
  psql -U postgres -d sagaz -f /partitioning/001_create_partitioned_tables.sql
```

---

## 📈 Scaling

### Scale Read Replicas

```bash
# Scale PostgreSQL StatefulSet
kubectl scale statefulset postgresql --replicas=5 -n sagaz

# Verify
kubectl get pods -n sagaz -l app=postgresql
```

### Scale PgBouncer Read Pool

```bash
# Manual scaling
kubectl scale deploy pgbouncer-ro --replicas=5 -n sagaz

# HPA automatically scales based on CPU (already configured)
kubectl get hpa pgbouncer-ro-hpa -n sagaz
```

### Scale Outbox Workers

```bash
# Scale workers for higher throughput
kubectl scale deploy outbox-worker --replicas=5 -n sagaz
```

---

## 🔍 Monitoring

### Check Metrics

```bash
# Port-forward Prometheus
kubectl port-forward -n sagaz-monitoring svc/prometheus 9090:9090

# Open: http://localhost:9090
# Query: rate(sagaz_outbox_published_total[5m])
```

### View Dashboards

```bash
# Port-forward Grafana
kubectl port-forward -n sagaz-monitoring svc/grafana 3000:3000

# Open: http://localhost:3000
# Default credentials: admin / admin
```

### Check Alerts

```bash
# View Prometheus alerts
kubectl port-forward -n sagaz-monitoring svc/prometheus 9090:9090
# Open: http://localhost:9090/alerts
```

---

## 🧹 Cleanup

### Remove Specific Components

```bash
# Remove monitoring only
kubectl delete -k k8s/monitoring

# Remove HA database (keeps base)
kubectl delete -k k8s/database/ha

# Remove simple database
kubectl delete -k k8s/database/simple
```

### Full Cleanup

```bash
# Remove everything
kubectl delete namespace sagaz
kubectl delete namespace sagaz-monitoring

# Or use kubectl delete -k
kubectl delete -k k8s/monitoring
kubectl delete -k k8s/database/ha
kubectl delete -k k8s/base
```

---

## 📚 Additional Resources

- **Architecture Guide:** [docs/architecture/README.md](../../docs/architecture/README.md)
- **HA PostgreSQL Deep Dive:** [docs/guides/ha-postgres-quickref.md](../../docs/guides/ha-postgres-quickref.md)
- **Monitoring Setup:** [k8s/monitoring/README.md](monitoring/README.md)

---

## 🎯 Next Steps

1. **Configure secrets** - Edit `k8s/base/secrets.yaml`
2. **Deploy base resources** - `kubectl apply -k k8s/base`
3. **Choose database mode**:
   - Simple: `kubectl apply -k k8s/database/simple`
   - HA: `kubectl apply -k k8s/database/ha`
4. **Add monitoring** (optional) - `kubectl apply -k k8s/monitoring`
5. **Run migrations** - `kubectl apply -f k8s/jobs/migration-job.yaml`
6. **Verify deployment** - `kubectl get pods -n sagaz`

---

**Questions?** Open an issue: https://github.com/brunolnetto/sagaz/issues  
**Kubernetes Docs:** https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/
