# Monitoring Setup Guide

This directory contains monitoring configurations for the sagaz saga orchestration system with the complete three pillars of observability: metrics, traces, and logs.

## Contents

- **Grafana Dashboards**
  - `grafana-dashboard-main.json` - Saga orchestration metrics
  - `grafana-dashboard-outbox.json` - Outbox pattern metrics
  - `grafana-dashboard-logs.json` - Log aggregation and analysis

- **Prometheus Alerts**
  - `prometheus-alerts.yaml` - Alert rules for saga and outbox

- **Log Aggregation Stack**
  - `loki.yaml` - Loki log aggregation system
  - `promtail.yaml` - Promtail log shipping agent

- **Operational Runbooks**
  - `RUNBOOKS.md` - Detailed troubleshooting procedures

## Three Pillars of Observability

### 1. **Metrics** (Prometheus + Grafana)
- Real-time saga execution metrics
- Outbox pattern performance
- Resource utilization and health checks

### 2. **Traces** (OpenTelemetry + Jaeger/Tempo)
- Distributed tracing across saga steps
- End-to-end transaction visibility
- Performance bottleneck identification

### 3. **Logs** (Loki + Promtail + Grafana)
- Centralized log aggregation
- Structured JSON log parsing
- Correlation with metrics and traces via saga_id

## Quick Start

### 1. Deploy Complete Monitoring Stack

```bash
# Create monitoring namespace
kubectl create namespace monitoring

# Deploy all monitoring components using Kustomize
kubectl apply -k .

# Or deploy individually
kubectl apply -f monitoring-stack.yaml
kubectl apply -f prometheus-alerts.yaml
kubectl apply -f loki.yaml
kubectl apply -f promtail.yaml
```

### 2. Verify Deployment

```bash
# Check all monitoring pods
kubectl get pods -n monitoring

# Expected output:
# NAME                      READY   STATUS    RESTARTS   AGE
# grafana-xxx               1/1     Running   0          2m
# loki-0                    1/1     Running   0          2m
# promtail-xxx              1/1     Running   0          2m
# prometheus-0              1/1     Running   0          2m

# Check Loki is ready
kubectl logs -n monitoring loki-0 | grep "server listening"

# Check Promtail is scraping
kubectl logs -n monitoring -l app=promtail | grep "Starting Promtail"
```

### 3. Access Grafana

```bash
# Port forward to Grafana
kubectl port-forward -n monitoring svc/grafana 3000:3000

# Open browser: http://localhost:3000
# Default credentials: admin / changeme (change in production!)
```

### 4. Import Grafana Dashboards

#### Option A: Via Grafana UI
1. Login to Grafana
2. Go to Dashboards → Import
3. Upload `grafana-dashboard-main.json`
4. Upload `grafana-dashboard-outbox.json`
5. Upload `grafana-dashboard-logs.json`

#### Option B: Via ConfigMap (Automated)
The dashboards are automatically provisioned via the `sagaz-grafana-dashboards` ConfigMap in `kustomization.yaml`. They will appear in the "Sage" folder in Grafana after deployment.

### 5. Explore Logs in Grafana

```bash
# Navigate to Explore → Select "Loki" datasource
# Try these LogQL queries (see examples below)
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

## LogQL Query Examples

LogQL is Loki's query language for searching and analyzing logs. Below are common queries for sagaz monitoring.

### Basic Log Queries

```logql
# View all saga logs
{namespace="sagaz"} | json

# View logs for a specific saga type
{namespace="sagaz", saga_name="OrderProcessing"} | json

# View logs by log level
{namespace="sagaz", level="ERROR"} | json

# View logs for a specific pod
{namespace="sagaz", pod="saga-orchestrator-xyz"} | json
```

### Saga-Specific Queries

```logql
# Find logs for a specific saga execution
{namespace="sagaz", saga_id="abc-123"} | json

# Find logs by correlation ID (trace across services)
{namespace="sagaz", correlation_id="req-xyz-789"} | json

# View all logs for a saga's specific step
{namespace="sagaz"} | json | step_name="reserve_inventory"

# Find saga completion logs
{namespace="sagaz"} | json | message =~ "(?i)saga (completed|finished)"
```

### Error Analysis Queries

```logql
# All error and critical logs
{namespace="sagaz", level=~"ERROR|CRITICAL"} | json

# Errors for a specific saga type
{namespace="sagaz", level="ERROR"} | json | saga_name="PaymentProcessing"

# Find compensation failures (critical!)
{namespace="sagaz", level="CRITICAL"} | json | message =~ "(?i)compensation.*failed"

# Count errors by saga type (last hour)
sum by (saga_name) (count_over_time({namespace="sagaz", level="ERROR"} | json [1h]))

# Top error types
topk(10, sum by (error_type) (count_over_time({namespace="sagaz", level="ERROR"} | json [1h])))
```

### Performance Analysis

```logql
# Extract and analyze step durations
{namespace="sagaz"} | json | duration_ms > 0 | unwrap duration_ms

# Steps taking longer than 1 second
{namespace="sagaz"} | json | duration_ms > 1000

# Average duration by saga type
avg by (saga_name) (
  rate({namespace="sagaz"} | json | duration_ms > 0 | unwrap duration_ms [5m])
)

# 95th percentile duration by step
quantile_over_time(0.95, {namespace="sagaz"} | json | duration_ms > 0 | unwrap duration_ms [5m])
```

### Compensation Monitoring

```logql
# All compensation activity
{namespace="sagaz"} | json | message =~ "(?i)compensation"

# Compensation started events
{namespace="sagaz"} | json | message =~ "(?i)compensation started"

# Count compensations by saga type
sum by (saga_name) (count_over_time({namespace="sagaz"} | json | message =~ "(?i)compensation" [1h]))

# Find sagas that triggered compensations
{namespace="sagaz"} | json | message =~ "(?i)compensation" | saga_id != ""
```

### Timeline and Flow Analysis

```logql
# Complete execution timeline for a specific saga (chronological order)
{namespace="sagaz", saga_id="abc-123"} | json 
| line_format "{{.timestamp}} [{{.level}}] {{.step_name}} - {{.message}}"

# See saga flow from start to completion
{namespace="sagaz"} | json 
| message =~ "(?i)(saga started|step (started|completed|failed)|compensation|saga (completed|failed))"
| saga_id="abc-123"

# Retry analysis - find steps with retries
{namespace="sagaz"} | json | retry_count > 0
```

### Log Volume and Rate

```logql
# Log rate per second
rate({namespace="sagaz"} [1m])

# Log volume by level
sum by (level) (count_over_time({namespace="sagaz"} | json [5m]))

# Logs per saga type
sum by (saga_name) (count_over_time({namespace="sagaz"} | json [1h]))

# Detect log volume spikes (compared to 1h ago)
sum(rate({namespace="sagaz"} [5m])) 
/ 
sum(rate({namespace="sagaz"} [5m] offset 1h))
```

### Advanced Pattern Matching

```logql
# Find database connection errors
{namespace="sagaz"} | json | message =~ "(?i)(database|connection|postgres).*error"

# Find timeout errors
{namespace="sagaz"} | json | error_type =~ ".*Timeout.*"

# Search for specific error messages
{namespace="sagaz"} | json | error_message =~ "(?i)insufficient.*funds"

# Multi-condition filtering
{namespace="sagaz"} 
| json 
| saga_name="OrderProcessing" 
| level="ERROR" 
| step_name="charge_payment"
```

### Alerting Queries (for Loki Ruler)

```logql
# High error rate alert (>10 errors/min)
sum(rate({namespace="sagaz", level="ERROR"} | json [1m])) > 10

# Compensation failure alert (any critical compensation failures)
count_over_time({namespace="sagaz", level="CRITICAL"} | json | message =~ "(?i)compensation.*failed" [5m]) > 0

# Saga failure rate alert (>5% failure rate)
(
  sum(rate({namespace="sagaz"} | json | message =~ "(?i)saga.*failed" [5m]))
  /
  sum(rate({namespace="sagaz"} | json | message =~ "(?i)saga.*(completed|failed)" [5m]))
) > 0.05
```

## Integration with Metrics and Traces

The sagaz logging system includes correlation IDs that link logs with metrics and traces:

### Correlating Logs with Prometheus Metrics

```logql
# In Grafana, you can click on a saga_id in logs and jump to:
# - Prometheus metrics: saga_execution_total{saga_id="abc-123"}
# - Duration metrics: saga_duration_seconds{saga_id="abc-123"}
```

### Correlating Logs with Traces

The `correlation_id` field in logs matches trace IDs in your tracing system:
- **Jaeger**: Search for trace ID matching `correlation_id`
- **Tempo**: Query `traceID="correlation_id_value"`
- **Zipkin**: Search by trace ID

### Example Correlation Workflow

1. **Start with metrics**: Notice high error rate in Prometheus dashboard
2. **Jump to logs**: Query `{level="ERROR", saga_name="OrderProcessing"}`
3. **Identify saga**: Find failing `saga_id` in logs
4. **View full timeline**: Query `{saga_id="identified-id"}` to see complete flow
5. **Check trace**: Use `correlation_id` to view distributed trace in Jaeger/Tempo
6. **Root cause**: Combine all three pillars for complete picture

## Loki Configuration

### Storage and Retention

```yaml
# Default configuration (loki.yaml)
limits_config:
  retention_period: 744h  # 31 days
  
# Adjust based on your needs:
# - 168h (7 days) for development
# - 720h (30 days) for staging
# - 2160h (90 days) for production
```

### Performance Tuning

```yaml
# Increase limits for high-volume environments
limits_config:
  ingestion_rate_mb: 20          # Default: 10
  ingestion_burst_size_mb: 40    # Default: 20
  per_stream_rate_limit: 10MB    # Default: 5MB
  max_query_parallelism: 64      # Default: 32
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

### Loki/Promtail Troubleshooting

#### No Logs Appearing in Grafana

1. **Verify Loki is running:**
   ```bash
   # Check Loki pod status
   kubectl get pods -n monitoring -l app=loki
   
   # Check Loki logs
   kubectl logs -n monitoring loki-0 --tail=50
   
   # Test Loki API
   kubectl port-forward -n monitoring svc/loki 3100:3100
   curl http://localhost:3100/ready
   ```

2. **Verify Promtail is running:**
   ```bash
   # Check Promtail DaemonSet
   kubectl get daemonset -n monitoring promtail
   
   # Check Promtail pods on all nodes
   kubectl get pods -n monitoring -l app=promtail -o wide
   
   # Check Promtail logs for errors
   kubectl logs -n monitoring -l app=promtail --tail=100
   ```

3. **Check Promtail is sending logs:**
   ```bash
   # View Promtail targets
   kubectl port-forward -n monitoring svc/promtail 9080:9080
   curl http://localhost:9080/targets
   
   # Check for scraping errors
   kubectl logs -n monitoring -l app=promtail | grep -i error
   ```

4. **Verify pod logs are accessible:**
   ```bash
   # Check if logs exist on node
   kubectl exec -n monitoring -it promtail-xxx -- ls -la /var/log/pods/sagaz/
   
   # Verify sagaz pods are logging
   kubectl logs -n sagaz -l app=saga-orchestrator --tail=10
   ```

#### Logs Not Parsed Correctly

1. **Check JSON format:**
   ```bash
   # Verify sagaz pods output JSON logs
   kubectl logs -n sagaz -l app=saga-orchestrator --tail=5
   
   # Expected format:
   # {"timestamp":"2024-12-28T19:00:00.000Z","level":"INFO","saga_id":"abc-123",...}
   ```

2. **Test Promtail pipeline:**
   ```bash
   # View Promtail config
   kubectl get configmap -n monitoring promtail-config -o yaml
   
   # Check for pipeline errors in logs
   kubectl logs -n monitoring -l app=promtail | grep -i "pipeline"
   ```

3. **Verify labels are extracted:**
   ```bash
   # Query Loki labels API
   kubectl port-forward -n monitoring svc/loki 3100:3100
   curl http://localhost:3100/loki/api/v1/labels
   
   # Should include: saga_id, saga_name, correlation_id, level
   ```

#### High Loki Memory Usage

1. **Check retention settings:**
   ```bash
   # View Loki config
   kubectl get configmap -n monitoring loki-config -o yaml | grep retention
   ```

2. **Adjust limits:**
   ```yaml
   # Edit loki.yaml
   limits_config:
     retention_period: 168h  # Reduce from 744h to 7 days
     max_query_series: 500   # Reduce from 1000
   ```

3. **Check compactor is running:**
   ```bash
   kubectl logs -n monitoring loki-0 | grep compactor
   ```

#### Slow Log Queries

1. **Optimize queries:**
   - Use label filters instead of regex when possible
   - Limit time range (avoid "Last 30 days")
   - Use `| json` only once per query
   - Add `| line_format` to reduce output size

2. **Check query performance:**
   ```bash
   # Enable query logging in Loki
   kubectl logs -n monitoring loki-0 | grep "query"
   ```

3. **Increase resources if needed:**
   ```yaml
   # Edit loki.yaml
   resources:
     limits:
       cpu: 2000m      # Increase from 1000m
       memory: 2Gi     # Increase from 1Gi
   ```

#### Promtail Using Too Many Resources

1. **Check scraping configuration:**
   ```bash
   # View targets and positions
   kubectl exec -n monitoring promtail-xxx -- cat /tmp/positions.yaml
   ```

2. **Adjust resource limits:**
   ```yaml
   # Edit promtail.yaml
   resources:
     limits:
       cpu: 300m       # Increase if needed
       memory: 512Mi   # Increase if needed
   ```

3. **Reduce scraping scope:**
   ```yaml
   # In promtail-config, add namespace filter
   relabel_configs:
     - source_labels: [__meta_kubernetes_namespace]
       regex: sagaz    # Only scrape sagaz namespace
       action: keep
   ```

#### Labels Not Showing in Grafana

1. **Verify Loki datasource:**
   ```bash
   # Check Grafana datasources
   kubectl exec -n monitoring grafana-xxx -- \
     curl -s http://localhost:3000/api/datasources | jq '.[] | select(.type=="loki")'
   ```

2. **Test label query:**
   ```bash
   # Query Loki label values
   curl 'http://localhost:3100/loki/api/v1/label/saga_name/values'
   ```

3. **Refresh dashboard variables:**
   - In Grafana dashboard, click on variable dropdown
   - Click refresh icon to reload values from Loki

#### Storage Issues

1. **Check PVC status:**
   ```bash
   kubectl get pvc -n monitoring
   
   # Check Loki storage usage
   kubectl exec -n monitoring loki-0 -- df -h /loki
   ```

2. **Expand PVC if needed:**
   ```bash
   # Edit PVC (if storageClass supports expansion)
   kubectl edit pvc storage-loki-0 -n monitoring
   # Change: storage: 10Gi -> storage: 20Gi
   ```

3. **Monitor compaction:**
   ```bash
   # Check compactor logs
   kubectl logs -n monitoring loki-0 | grep -i compact
   ```

## Additional Resources

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [LogQL Documentation](https://grafana.com/docs/loki/latest/logql/)
- [Promtail Documentation](https://grafana.com/docs/loki/latest/clients/promtail/)
- [Alertmanager Documentation](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Runbooks](./RUNBOOKS.md)

## Support

For issues or questions:
- **Slack**: #sage-monitoring
- **GitHub**: Open an issue
- **Docs**: https://github.com/yourorg/sage/wiki
