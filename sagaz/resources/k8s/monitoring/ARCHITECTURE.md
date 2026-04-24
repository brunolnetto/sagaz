# Sagaz Observability Architecture

## Complete Three Pillars Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                               │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                    Sagaz Application Namespace                  │    │
│  │                                                                  │    │
│  │  ┌──────────────┐       ┌──────────────┐                      │    │
│  │  │    Saga      │       │   Outbox     │                      │    │
│  │  │ Orchestrator │       │   Worker     │                      │    │
│  │  │              │       │              │                      │    │
│  │  │ • Executes   │       │ • Publishes  │                      │    │
│  │  │   sagas      │       │   events     │                      │    │
│  │  │ • Logs JSON  │──────▶│ • Logs JSON  │                      │    │
│  │  │ • Exposes    │       │ • Exposes    │                      │    │
│  │  │   /metrics   │       │   /metrics   │                      │    │
│  │  └──────┬───────┘       └──────┬───────┘                      │    │
│  │         │                      │                               │    │
│  │         │ Writes JSON logs     │ Writes JSON logs              │    │
│  │         │ to stdout            │ to stdout                     │    │
│  │         ▼                      ▼                               │    │
│  │    ┌────────────────────────────────┐                         │    │
│  │    │  /var/log/pods/sagaz/.../*.log │                         │    │
│  │    └────────────────────────────────┘                         │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                   Monitoring Namespace                          │    │
│  │                                                                  │    │
│  │  ┌──────────────────────────────────────────────────────────┐ │    │
│  │  │                    PILLAR 1: LOGS                        │ │    │
│  │  │                                                          │ │    │
│  │  │  ┌─────────────┐    Scrapes    ┌──────────────┐        │ │    │
│  │  │  │  Promtail   │───────────────▶│     Loki     │        │ │    │
│  │  │  │ (DaemonSet) │    Pod Logs    │ (StatefulSet)│        │ │    │
│  │  │  │             │                │              │        │ │    │
│  │  │  │ • Mounts    │                │ • Stores logs│        │ │    │
│  │  │  │   /var/log  │                │ • 31d retain │        │ │    │
│  │  │  │ • Parses    │                │ • TSDB index │        │ │    │
│  │  │  │   JSON      │                │ • Compaction │        │ │    │
│  │  │  │ • Extracts  │                │              │        │ │    │
│  │  │  │   labels:   │                │   Port: 3100 │        │ │    │
│  │  │  │   - saga_id │                │              │        │ │    │
│  │  │  │   - level   │                └──────┬───────┘        │ │    │
│  │  │  │   - saga_   │                       │                │ │    │
│  │  │  │     name    │                       │                │ │    │
│  │  │  └─────────────┘                       │                │ │    │
│  │  └───────────────────────────────────────┼────────────────┘ │    │
│  │                                           │                   │    │
│  │  ┌──────────────────────────────────────┼────────────────┐ │    │
│  │  │                PILLAR 2: METRICS      │                │ │    │
│  │  │                                       │                │ │    │
│  │  │  ┌──────────────┐    Scrapes    ┌────▼──────┐        │ │    │
│  │  │  │  Prometheus  │◀──────────────│   Saga    │        │ │    │
│  │  │  │              │   /metrics     │ Pods      │        │ │    │
│  │  │  │ • Time-series│                └───────────┘        │ │    │
│  │  │  │   metrics    │                                     │ │    │
│  │  │  │ • Alerts     │                                     │ │    │
│  │  │  │ • 40+ saga   │                                     │ │    │
│  │  │  │   metrics    │                                     │ │    │
│  │  │  │              │                                     │ │    │
│  │  │  │  Port: 9090  │                                     │ │    │
│  │  │  └──────┬───────┘                                     │ │    │
│  │  └─────────┼─────────────────────────────────────────────┘ │    │
│  │            │                                                 │    │
│  │  ┌─────────┼─────────────────────────────────────────────┐ │    │
│  │  │         │         PILLAR 3: TRACES (Optional)         │ │    │
│  │  │         │                                              │ │    │
│  │  │  ┌──────▼────────┐         ┌──────────────┐          │ │    │
│  │  │  │ OpenTelemetry │────────▶│    Jaeger    │          │ │    │
│  │  │  │   Collector   │  Traces │  / Tempo     │          │ │    │
│  │  │  │               │         │  / Zipkin    │          │ │    │
│  │  │  │ • Receives    │         │              │          │ │    │
│  │  │  │   OTLP traces │         │ • Trace      │          │ │    │
│  │  │  │ • Exports to  │         │   storage    │          │ │    │
│  │  │  │   backend     │         │ • Trace      │          │ │    │
│  │  │  │               │         │   analysis   │          │ │    │
│  │  │  └───────────────┘         └──────────────┘          │ │    │
│  │  └──────────────────────────────────────────────────────┘ │    │
│  │                                                              │    │
│  │  ┌──────────────────────────────────────────────────────┐ │    │
│  │  │            UNIFIED VISUALIZATION: GRAFANA             │ │    │
│  │  │                                                        │ │    │
│  │  │  ┌──────────────────────────────────────────────┐    │ │    │
│  │  │  │              Datasources:                    │    │ │    │
│  │  │  │  • Prometheus (Metrics)                      │    │ │    │
│  │  │  │  • Loki (Logs) ◀── NEW!                      │    │ │    │
│  │  │  │  • Tempo/Jaeger (Traces - Optional)          │    │ │    │
│  │  │  └──────────────────────────────────────────────┘    │ │    │
│  │  │                                                        │ │    │
│  │  │  ┌──────────────────────────────────────────────┐    │ │    │
│  │  │  │              Dashboards:                     │    │ │    │
│  │  │  │  1. Saga Orchestration (Metrics)             │    │ │    │
│  │  │  │  2. Outbox Pattern (Metrics)                 │    │ │    │
│  │  │  │  3. Logs Dashboard (Logs) ◀── NEW!           │    │ │    │
│  │  │  │                                               │    │ │    │
│  │  │  │  Features:                                    │    │ │    │
│  │  │  │  • Drill-down from metrics to logs           │    │ │    │
│  │  │  │  • Correlation via saga_id/correlation_id    │    │ │    │
│  │  │  │  • Unified timeline view                     │    │ │    │
│  │  │  │  • Error analysis across all pillars         │    │ │    │
│  │  │  └──────────────────────────────────────────────┘    │ │    │
│  │  │                                                        │ │    │
│  │  │                    Port: 3000                          │ │    │
│  │  │              (admin / changeme)                        │ │    │
│  │  └──────────────────────────────────────────────────────┘ │    │
│  └────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Log Flow (NEW!)

```
Saga Pod
  │
  ├─ Writes JSON logs to stdout
  │  {
  │    "timestamp": "2024-12-28T19:00:00Z",
  │    "level": "INFO",
  │    "saga_id": "abc-123",
  │    "saga_name": "OrderProcessing",
  │    "correlation_id": "req-xyz-789",
  │    "message": "Step completed"
  │  }
  │
  ▼
Kubernetes writes to /var/log/pods/sagaz/.../app.log
  │
  ▼
Promtail (DaemonSet on each node)
  │
  ├─ Reads log file
  ├─ Parses JSON
  ├─ Extracts labels:
  │  • namespace=sagaz
  │  • level=INFO
  │  • saga_id=abc-123
  │  • saga_name=OrderProcessing
  │  • correlation_id=req-xyz-789
  │  • step_name=reserve_inventory
  │
  ▼
Loki (Port 3100)
  │
  ├─ Indexes by labels (fast filtering)
  ├─ Stores full log content
  ├─ Retains for 31 days
  ├─ Compacts old data
  │
  ▼
Grafana Logs Dashboard
  │
  ├─ Query with LogQL:
  │  {saga_id="abc-123"} | json
  │
  ├─ View timeline
  ├─ Filter by level, saga_name, etc.
  └─ Correlate with Prometheus metrics
```

### 2. Metric Flow (Existing)

```
Saga Pod (/metrics endpoint)
  │
  ├─ saga_execution_total{status="completed"}
  ├─ saga_duration_seconds{saga_name="OrderProcessing"}
  ├─ saga_step_duration_seconds{step="reserve_inventory"}
  │
  ▼
Prometheus (Port 9090)
  │
  ├─ Scrapes every 30s
  ├─ Stores time-series
  ├─ Evaluates alerts
  │
  ▼
Grafana Saga/Outbox Dashboards
  │
  └─ Visualize metrics, set alerts
```

### 3. Correlation Flow (All Three Pillars)

```
User investigates issue:
  │
  ├─ 1. Notice spike in Prometheus:
  │     saga_execution_total{status="failed"}
  │
  ├─ 2. Click saga_id link in metric
  │
  ├─ 3. Jump to Loki logs:
  │     {saga_id="abc-123"} | json
  │
  ├─ 4. See complete execution timeline:
  │     00:00 - Saga started
  │     00:05 - Step 1 completed
  │     00:10 - Step 2 failed (ERROR)
  │     00:11 - Compensation started
  │
  ├─ 5. Use correlation_id to view trace:
  │     Search in Jaeger/Tempo for trace_id
  │
  └─ 6. Full picture:
       • Metrics: What failed
       • Logs: Why it failed (error message)
       • Traces: Where it failed (which service)
```

## LogQL Query Patterns

### Basic Queries

```logql
# All saga logs
{namespace="sagaz"} | json

# Specific saga execution
{namespace="sagaz", saga_id="abc-123"} | json

# Error logs only
{namespace="sagaz", level="ERROR"} | json

# Specific saga type
{namespace="sagaz", saga_name="OrderProcessing"} | json
```

### Advanced Queries

```logql
# Timeline view (formatted)
{namespace="sagaz", saga_id="abc-123"} | json 
| line_format "{{.timestamp}} [{{.level}}] {{.step_name}} - {{.message}}"

# Count errors by saga type
sum by (saga_name) (count_over_time({namespace="sagaz", level="ERROR"} | json [1h]))

# Find slow steps
{namespace="sagaz"} | json | duration_ms > 1000

# Compensation failures (critical!)
{namespace="sagaz", level="CRITICAL"} | json | message =~ "(?i)compensation.*failed"
```

## Storage Requirements

### Loki Storage
- **Default**: 10Gi PVC
- **Retention**: 31 days
- **Estimation**: ~100-500MB per day (depends on log volume)
- **Recommendation**: Monitor usage and adjust PVC size

### Prometheus Storage
- **Default**: Managed by prometheus-operator
- **Retention**: Typically 15-30 days
- **Recommendation**: Use remote write for long-term storage

## Resource Requirements

| Component  | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| Loki      | 200m        | 1000m     | 512Mi          | 1Gi          |
| Promtail  | 50m         | 200m      | 128Mi          | 256Mi        |
| Prometheus| 500m        | 2000m     | 1Gi            | 2Gi          |
| Grafana   | 100m        | 500m      | 256Mi          | 512Mi        |

**Total for monitoring stack**: ~850m CPU, ~1.9Gi RAM (minimum)

## Benefits Summary

### Before (Metrics + Traces Only)
- ✓ Real-time metrics
- ✓ Distributed traces
- ✗ No centralized log search
- ✗ Manual pod log access
- ✗ No historical log retention
- ✗ Difficult to correlate logs with metrics

### After (Complete Observability)
- ✓ Real-time metrics
- ✓ Distributed traces
- ✓ Centralized log aggregation (NEW!)
- ✓ Powerful LogQL queries (NEW!)
- ✓ 31-day log retention (NEW!)
- ✓ Full correlation via saga_id (NEW!)
- ✓ Unified Grafana interface (NEW!)
- ✓ Timeline debugging (NEW!)

## Next Steps

1. **Deploy**: `kubectl apply -k sagaz/resources/k8s/monitoring/`
2. **Verify**: Check pods are running
3. **Explore**: Open Grafana, navigate to Explore → Loki
4. **Create alerts**: Set up Loki Ruler for log-based alerts
5. **Tune retention**: Adjust based on compliance/storage needs
6. **Scale**: Monitor resource usage, adjust limits as needed

## References

- Deployment: `sagaz/resources/k8s/monitoring/loki.yaml`
- Pipeline config: `sagaz/resources/k8s/monitoring/promtail.yaml`
- Dashboard: `sagaz/resources/k8s/monitoring/grafana-dashboard-logs.json`
- Quick start: `sagaz/resources/k8s/monitoring/LOKI_QUICK_REFERENCE.md`
- Full docs: `sagaz/resources/k8s/monitoring/README.md`
