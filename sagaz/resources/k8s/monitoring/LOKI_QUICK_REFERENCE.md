# Loki/Promtail Quick Reference Guide

## Quick Commands

### Deployment

```bash
# Deploy complete stack
kubectl apply -k sagaz/resources/k8s/monitoring/

# Deploy individually
kubectl apply -f sagaz/resources/k8s/monitoring/loki.yaml
kubectl apply -f sagaz/resources/k8s/monitoring/promtail.yaml

# Verify deployment
kubectl get pods -n monitoring -l app=loki
kubectl get pods -n monitoring -l app=promtail
```

### Health Checks

```bash
# Check Loki
kubectl port-forward -n monitoring svc/loki 3100:3100
curl http://localhost:3100/ready
curl http://localhost:3100/metrics

# Check Promtail
kubectl logs -n monitoring -l app=promtail --tail=50
kubectl port-forward -n monitoring svc/promtail 9080:9080
curl http://localhost:9080/targets
```

### Access Grafana

```bash
# Port forward
kubectl port-forward -n monitoring svc/grafana 3000:3000

# Login: admin / changeme
# Navigate to: Explore → Select "Loki" datasource
```

## Essential LogQL Queries

### Find Saga Execution

```logql
# By saga ID
{namespace="sagaz", saga_id="abc-123"} | json

# By correlation ID
{namespace="sagaz", correlation_id="req-xyz-789"} | json

# By saga type
{namespace="sagaz", saga_name="OrderProcessing"} | json
```

### Error Investigation

```logql
# All errors
{namespace="sagaz", level="ERROR"} | json

# Errors for specific saga
{namespace="sagaz", level="ERROR"} | json | saga_name="PaymentProcessing"

# Critical compensation failures
{namespace="sagaz", level="CRITICAL"} | json | message =~ "(?i)compensation.*failed"
```

### Performance Analysis

```logql
# Slow steps (>1 second)
{namespace="sagaz"} | json | duration_ms > 1000

# Average duration by saga type
avg by (saga_name) (
  rate({namespace="sagaz"} | json | duration_ms > 0 | unwrap duration_ms [5m])
)
```

### Timeline View

```logql
# Complete saga execution flow
{namespace="sagaz", saga_id="abc-123"} | json 
| line_format "{{.timestamp}} [{{.level}}] {{.step_name}} - {{.message}}"
```

## Log Fields

The following fields are extracted as Loki labels for efficient filtering:

- **level** - Log level (INFO, WARNING, ERROR, CRITICAL)
- **saga_id** - Unique saga execution identifier
- **saga_name** - Saga type name
- **correlation_id** - Request correlation ID
- **step_name** - Current saga step name

Additional fields available in log content:
- timestamp, logger, message, module, function, line
- duration_ms, status, error_type, error_message, retry_count

## Dashboard Variables

The Logs Dashboard includes these filters:

- **datasource** - Select Loki datasource
- **saga_name** - Filter by saga type (multi-select)
- **saga_id** - Filter by saga execution ID
- **saga_id_timeline** - Text input for timeline view
- **correlation_id** - Filter by correlation ID
- **log_level** - Filter by log level (multi-select)

## Common Issues

### No logs appearing
```bash
# 1. Check Promtail is running
kubectl get daemonset -n monitoring promtail

# 2. Check logs are being scraped
kubectl logs -n monitoring -l app=promtail | grep -i "scrape"

# 3. Verify sagaz pods are logging JSON
kubectl logs -n sagaz -l app=saga-orchestrator --tail=5
```

### Labels not extracted
```bash
# Check Promtail pipeline configuration
kubectl get configmap -n monitoring promtail-config -o yaml

# View Promtail pipeline errors
kubectl logs -n monitoring -l app=promtail | grep -i "error"
```

### Slow queries
- Use label filters: `{level="ERROR"}` instead of regex
- Limit time range: Last 1h instead of Last 24h
- Add `| json` only once per query
- Use `| line_format` to reduce output

## Storage Management

### Check storage usage
```bash
kubectl exec -n monitoring loki-0 -- df -h /loki
```

### Adjust retention (edit loki.yaml)
```yaml
limits_config:
  retention_period: 168h  # Change to 7 days
```

### Force compaction
```bash
# Check compactor logs
kubectl logs -n monitoring loki-0 | grep -i compact
```

## Integration with Prometheus

Use `saga_id` or `correlation_id` to correlate logs with metrics:

1. Find error in logs: `{level="ERROR"}`
2. Extract `saga_id` from log entry
3. Query Prometheus: `saga_execution_total{saga_id="abc-123"}`

## Resources

- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [LogQL Language](https://grafana.com/docs/loki/latest/logql/)
- [Promtail Configuration](https://grafana.com/docs/loki/latest/clients/promtail/)
- Full documentation: `sagaz/resources/k8s/monitoring/README.md`
