# Kubernetes Deployment Manifests for sagaz Saga Pattern

This directory contains production-ready Kubernetes manifests for deploying the sagaz Saga Pattern system.

## Quick Start

```bash
# 1. Create namespace
kubectl create namespacesagaz

# 2. Create database secret
kubectl create secret generic sagaz-db-credentials \
  --from-literal=connection-string="postgresql://user:pass@postgres:5432/saga_db" \
  -n sagaz

# 3. Create broker secret (Kafka example)
kubectl create secret generic sagaz-broker-credentials \
  --from-literal=bootstrap-servers="kafka:9092" \
  -n sagaz

# 4. Deploy PostgreSQL (if needed)
kubectl apply -f postgresql.yaml

# 5. Run database migration
kubectl apply -f migration-job.yaml

# 6. Deploy outbox worker
kubectl apply -f outbox-worker.yaml

# 7. Verify deployment
kubectl get pods -n sagaz
kubectl logs -f deployment/outbox-worker -n sagaz
```

## Files

### Core Deployments
- `postgresql.yaml` - PostgreSQL StatefulSet with persistent storage
- `migration-job.yaml` - One-time database schema migration
- `outbox-worker.yaml` - Outbox worker Deployment with HPA

### Monitoring
- `monitoring/` - Complete monitoring stack
  - `grafana-dashboard-saga.json` - Saga orchestration dashboard
  - `grafana-dashboard-outbox.json` - Outbox pattern dashboard
  - `prometheus-alerts.yaml` - Comprehensive alert rules
  - `monitoring-stack.yaml` - Grafana deployment and configs
  - `RUNBOOKS.md` - Operational runbooks for troubleshooting
  - `README.md` - Monitoring setup guide

### Configuration
- `configmap.yaml` - Application configuration
- `secrets-example.yaml` - Example secrets (DO NOT commit real secrets!)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                   │
│                                                          │
│  ┌──────────────┐       ┌──────────────┐               │
│  │ Application  │──────▶│   Outbox     │               │
│  │   Pods       │       │   Worker     │               │
│  │              │       │  (3-10 pods) │               │
│  └──────┬───────┘       └──────┬───────┘               │
│         │                      │                        │
│         ▼                      ▼                        │
│  ┌──────────────────────────────────┐                  │
│  │       PostgreSQL StatefulSet      │                  │
│  │     (Persistent Volume Claim)     │                  │
│  └──────────────────────────────────┘                  │
│         │                      │                        │
│         └──────────┬───────────┘                        │
│                    │                                    │
│                    ▼                                    │
│         ┌──────────────────┐                           │
│         │   Kafka/RabbitMQ  │                           │
│         │   (External or    │                           │
│         │    in-cluster)    │                           │
│         └──────────────────┘                           │
└─────────────────────────────────────────────────────────┘
```

## Scaling

### Horizontal Pod Autoscaling (HPA)

The outbox worker automatically scales based on pending events:

```yaml
# Defined in outbox-worker.yaml
spec:
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Pods
      pods:
        metric:
          name: outbox_pending_events_total
        target:
          type: AverageValue
          averageValue: "1000"  # Scale when >1000 pending per pod
```

### Manual Scaling

```bash
# Scale up during high traffic
kubectl scale deployment outbox-worker --replicas=10 -n sagaz

# Scale down during low traffic
kubectl scale deployment outbox-worker --replicas=3 -n sagaz
```

## Resource Requirements

### Development/Staging
- **Outbox Worker**: 200m CPU, 256Mi RAM per pod
- **PostgreSQL**: 500m CPU, 1Gi RAM
- **Total**: ~1 CPU core, 2Gi RAM (minimum)

### Production
- **Outbox Worker**: 500m-1000m CPU, 512Mi-1Gi RAM per pod
- **PostgreSQL**: 2-4 CPU cores, 4-8Gi RAM
- **Total**: 5-10 CPU cores, 10-20Gi RAM (with 5 worker pods)

## Monitoring

### Prometheus Metrics

Exposed on port 8000:
- `outbox_pending_events_total` - Pending events gauge
- `outbox_published_events_total` - Published events counter
- `outbox_failed_events_total` - Failed events counter
- `outbox_publish_duration_seconds` - Publish latency histogram

### Grafana Dashboard

Import `grafana-dashboard.yaml` ConfigMap to get:
- Pending events graph
- Publish rate (events/sec)
- Latency percentiles (p50, p95, p99)
- Error rate by event type

### Alerts

AlertManager rules in `alertmanager-rules.yaml`:
- OutboxHighLag - Too many pending events
- OutboxWorkerDown - No workers running
- OutboxHighErrorRate - >1% publish failures

## Security

### Network Policies

```bash
# Apply network policies to restrict traffic
kubectl apply -f network-policies.yaml
```

Default policies:
- Workers can connect to PostgreSQL only
- Workers can connect to Kafka/RabbitMQ only
- No ingress from outside namespace

### Pod Security

All pods run with:
- Non-root user (UID 1000)
- Read-only root filesystem
- No privilege escalation
- Dropped all capabilities

### Secrets Management

**DO NOT** commit secrets to Git. Use:
- Kubernetes Secrets (encrypted at rest)
- External Secrets Operator (recommended)
- HashiCorp Vault
- AWS Secrets Manager / GCP Secret Manager

Example with External Secrets Operator:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name:sagaz-db-credentials
  namespace:sagaz
spec:
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name:sagaz-db-credentials
  data:
    - secretKey: connection-string
      remoteRef:
        key:sagaz/postgres/connection
```

## Backup & Recovery

### Database Backups

```bash
# Manual backup
kubectl exec -it postgresql-0 -n sagaz -- \
  pg_dump -U postgres saga_db > backup.sql

# Restore
kubectl exec -i postgresql-0 -n sagaz -- \
  psql -U postgres saga_db < backup.sql
```

### Automated Backups

Use Velero or similar:

```bash
# Backup entire namespace
velero backup createsagaz-backup --include-namespaces sagaz

# Restore
velero restore create --from-backup sagaz-backup
```

## Monitoring & Observability

### Three Pillars of Observability

The sagaz monitoring stack provides complete observability through:

1. **Metrics** (Prometheus + Grafana) - Real-time performance and health metrics
2. **Traces** (OpenTelemetry + Jaeger/Tempo) - Distributed request tracing
3. **Logs** (Loki + Promtail + Grafana) - Centralized log aggregation and search

### Deploy Monitoring Stack

```bash
# Create monitoring namespace
kubectl create namespace monitoring

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
# Check worker pods
kubectl get pods -n sagaz -l app=outbox-worker

# Check worker logs
kubectl logs -f deployment/outbox-worker -n sagaz

# Check database connectivity
kubectl exec -it deployment/outbox-worker -n sagaz -- \
  env | grep DATABASE_URL
```

#### High pending event count

```bash
# Scale up workers immediately
kubectl scale deployment outbox-worker --replicas=10 -n sagaz

# Check pending count
kubectl exec -it postgresql-0 -n sagaz -- \
  psql -U postgres saga_db -c \
  "SELECT COUNT(*) FROM saga_outbox WHERE status='pending';"

# Check for stuck events
kubectl exec -it postgresql-0 -n sagaz -- \
  psql -U postgres saga_db -c \
  "SELECT * FROM saga_outbox WHERE status='claimed' 
   AND claimed_at < NOW() - INTERVAL '5 minutes';"
```

### Database connection errors

```bash
# Test connection from worker
kubectl exec -it deployment/outbox-worker -n sagaz -- \
  python -c "import asyncpg; print('Testing...')"

# Check PostgreSQL logs
kubectl logs -f postgresql-0 -n sagaz

# Verify secret
kubectl get secretsagaz-db-credentials -n sagaz -o yaml
```

## Production Checklist

- [ ] Database backup strategy in place
- [ ] Secrets stored securely (not in Git)
- [ ] Resource limits configured
- [ ] HPA enabled and tested
- [ ] Prometheus metrics scraped
- [ ] Grafana dashboard imported
- [ ] Alerts configured in AlertManager
- [ ] Network policies applied
- [ ] Pod security policies enforced
- [ ] Disaster recovery tested
- [ ] Runbooks documented
- [ ] On-call rotation established

## Support

For issues and questions:
- Check logs: `kubectl logs -f deployment/outbox-worker -n sagaz`
- Check metrics: `kubectl port-forward service/outbox-worker-metrics 8000:8000 -n sagaz`
- Open an issue on GitHub
- Contact the platform team
