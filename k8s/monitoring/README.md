# Monitoring Setup Guide

This directory contains monitoring configurations for the sagaz saga orchestration system.

## Contents

- **Grafana Dashboards**
  - `grafana-dashboard-saga.json` - Saga orchestration metrics
  - `grafana-dashboard-outbox.json` - Outbox pattern metrics

- **Prometheus Alerts**
  - `prometheus-alerts.yaml` - Alert rules for saga and outbox

- **Operational Runbooks**
  - `RUNBOOKS.md` - Detailed troubleshooting procedures

## Quick Start

### 1. Deploy Prometheus Alerts

```bash
# Apply alert rules
kubectl apply -f prometheus-alerts.yaml

# Verify alerts are loaded
kubectl exec -n monitoring prometheus-0 -- promtool check config /etc/prometheus/prometheus.yml
```

### 2. Import Grafana Dashboards

#### Option A: Via Grafana UI
1. Login to Grafana
2. Go to Dashboards → Import
3. Upload `grafana-dashboard-saga.json`
4. Upload `grafana-dashboard-outbox.json`

#### Option B: Via ConfigMap
```bash
# Create configmap
kubectl create configmap grafana-dashboards \
  --from-file=grafana-dashboard-saga.json \
  --from-file=grafana-dashboard-outbox.json \
  -n monitoring

# Label for auto-discovery
kubectl label configmap grafana-dashboards \
  grafana_dashboard=1 \
  -n monitoring
```

#### Option C: Via Kubernetes Manifest
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name:sagaz-grafana-dashboards
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
 sagaz-saga.json: |
    # Paste contents of grafana-dashboard-saga.json
 sagaz-outbox.json: |
    # Paste contents of grafana-dashboard-outbox.json
```

### 3. Configure Prometheus

Ensure Prometheus is scraping the correct endpoints:

```yaml
# prometheus-config.yaml
scrape_configs:
  - job_name: 'saga-orchestrator'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            -sagaz
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: saga-orchestrator
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
      - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        regex: ([^:]+)(?::\d+)?;(\d+)
        replacement: $1:$2
        target_label: __address__

  - job_name: 'outbox-worker'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            -sagaz
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: outbox-worker
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
```

## Metrics Exposed

### Saga Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `saga_executions_total` | Counter | Total saga executions by status and type |
| `saga_duration_seconds` | Histogram | Saga execution duration |
| `saga_status_gauge` | Gauge | Current sagas by status |
| `saga_step_executions_total` | Counter | Step executions by status |
| `saga_step_duration_seconds` | Histogram | Step execution duration |
| `saga_compensations_total` | Counter | Compensation executions |
| `saga_storage_errors_total` | Counter | Storage operation errors |

### Outbox Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `outbox_pending_events_total` | Gauge | Events pending publication |
| `outbox_processing_events_total` | Gauge | Events currently being processed |
| `outbox_published_events_total` | Counter | Successfully published events |
| `outbox_failed_events_total` | Counter | Failed publication attempts |
| `outbox_dead_letter_events_total` | Counter | Events moved to DLQ |
| `outbox_publish_duration_seconds` | Histogram | Event publication duration |
| `outbox_retry_attempts_total` | Counter | Retry attempts by count |
| `outbox_batch_processed_total` | Counter | Processed batches |
| `outbox_batch_size` | Histogram | Events per batch |
| `outbox_optimistic_send_attempts_total` | Counter | Optimistic send attempts |
| `outbox_optimistic_send_failures_total` | Counter | Optimistic send failures |

## Alert Configuration

### Severity Levels

- **Critical**: Immediate action required, system degraded
- **Warning**: Issue detected, may become critical
- **Info**: Informational, no action required

### Alert Routing

Configure Alertmanager routes:

```yaml
# alertmanager-config.yaml
route:
  receiver: 'default'
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  routes:
    - match:
        severity: critical
        component: outbox-worker
      receiver: 'pagerduty-critical'
      continue: true
    
    - match:
        severity: critical
        component: saga
      receiver: 'pagerduty-critical'
      continue: true
    
    - match:
        severity: warning
      receiver: 'slack-warnings'
    
    - match:
        severity: info
      receiver: 'slack-info'

receivers:
  - name: 'default'
    slack_configs:
      - api_url: 'YOUR_SLACK_WEBHOOK'
        channel: '#sage-alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'

  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_KEY'
        description: '{{ .GroupLabels.alertname }}: {{ .Alerts.Firing | len }} firing'

  - name: 'slack-warnings'
    slack_configs:
      - api_url: 'YOUR_SLACK_WEBHOOK'
        channel: '#sage-warnings'
        
  - name: 'slack-info'
    slack_configs:
      - api_url: 'YOUR_SLACK_WEBHOOK'
        channel: '#sage-info'
```

## Dashboard Panels Overview

### Saga Orchestration Dashboard

1. **Saga Execution Rate** - Ops/sec by saga type
2. **Saga Success Rate** - % successful executions
3. **Active Sagas** - Currently running sagas
4. **Status Distribution** - Pie chart of saga states
5. **Execution Duration** - p50/p95/p99 latencies
6. **Step Success Rate** - Per-step success metrics
7. **Compensation Executions** - Compensation activity
8. **Failed Steps** - Top 10 failing steps
9. **Rollback Rate** - Saga rollback frequency
10. **Step Duration Heatmap** - Step performance distribution

### Outbox Pattern Dashboard

1. **Outbox Pending Events** - Queue depth
2. **Event Publish Rate** - Throughput metrics
3. **Publish Success Rate** - % successful publishes
4. **Dead Letter Queue** - DLQ event count
5. **Worker Health** - Active worker count
6. **Average Publish Latency** - p95 latency
7. **Latency Distribution** - p50/p95/p99 publish times
8. **Retry Distribution** - Retry attempt patterns
9. **Events by State** - State distribution
10. **Optimistic Send Performance** - Optimistic send metrics
11. **Worker CPU Usage** - Resource utilization
12. **Worker Memory Usage** - Memory consumption
13. **Batch Processing Metrics** - Batch size and throughput

## Monitoring Best Practices

### 1. Set Baselines
- Monitor metrics for 1-2 weeks to establish normal patterns
- Document baseline values for each metric
- Set alert thresholds based on baselines

### 2. Alert Fatigue Prevention
- Start with conservative thresholds
- Use `for` duration to avoid flapping
- Group related alerts
- Regular alert review and tuning

### 3. Dashboard Organization
- Use variables for filtering (namespace, pod, saga type)
- Set appropriate time ranges
- Add annotations for deployments
- Use consistent color schemes

### 4. On-Call Readiness
- Ensure runbooks are accessible
- Test alert routing
- Practice incident response
- Document common issues

### 5. Regular Reviews
- Weekly metrics review
- Monthly alert tuning
- Quarterly dashboard updates
- Annual monitoring strategy review

## Testing Alerts

### Trigger Test Alerts

```bash
# High pending events
kubectl exec -n sagaz postgresql-0 -- psql -U sagaz -c \
  "INSERT INTO outbox_events (aggregate_id, event_type, payload, state) 
   SELECT gen_random_uuid(), 'test', '{}', 'pending' 
   FROM generate_series(1, 11000);"

# Simulate worker down
kubectl scale deployment/outbox-worker -n sagaz --replicas=0
sleep 120  # Wait for alert
kubectl scale deployment/outbox-worker -n sagaz --replicas=3

# Simulate high failure rate
# (Requires mock failures in application code)
```

### Verify Alert Flow

```bash
# Check Prometheus alerts
curl http://prometheus:9090/api/v1/alerts | jq '.data.alerts'

# Check Alertmanager
curl http://alertmanager:9093/api/v2/alerts | jq '.'

# Check alert firing in Prometheus UI
# Navigate to: Alerts → View in Prometheus
```

## Troubleshooting

### Metrics Not Appearing

1. **Check service discovery:**
   ```bash
   # View discovered targets
   curl http://prometheus:9090/api/v1/targets
   ```

2. **Verify pod annotations:**
   ```bash
   kubectl get pods -n sagaz -o yaml | grep -A 5 annotations
   ```

3. **Check metrics endpoint:**
   ```bash
   kubectl port-forward -n sagaz pod/outbox-worker-xxx 8000:8000
   curl localhost:8000/metrics
   ```

### Dashboard Not Loading

1. **Check datasource configuration**
2. **Verify metric names match**
3. **Check time range settings**
4. **Validate PromQL queries**

### Alerts Not Firing

1. **Check alert rules loaded:**
   ```bash
   kubectl exec -n monitoring prometheus-0 -- \
     wget -qO- localhost:9090/api/v1/rules | jq '.data.groups[].rules'
   ```

2. **Verify thresholds:**
   ```bash
   # Query current values
   curl "http://prometheus:9090/api/v1/query?query=outbox_pending_events_total"
   ```

3. **Check Alertmanager config:**
   ```bash
   kubectl exec -n monitoring alertmanager-0 -- \
     amtool config show
   ```

## Additional Resources

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Alertmanager Documentation](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Runbooks](./RUNBOOKS.md)

## Support

For issues or questions:
- **Slack**: #sage-monitoring
- **GitHub**: Open an issue
- **Docs**: https://github.com/yourorg/sage/wiki
