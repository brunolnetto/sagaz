# Monitoring Quick Reference

## 🚨 Critical Alerts

| Alert | Threshold | Action |
|-------|-----------|--------|
| `OutboxWorkerDown` | All workers down for 2m | Restart workers immediately |
| `OutboxHighLag` | >10k pending events for 10m | Scale workers, check broker |
| `OutboxDeadLetterQueue` | >5 events to DLQ in 10m | Investigate failures, replay events |
| `SagaHighFailureRate` | >5% failures for 5m | Check downstream services |
| `CompensationFailures` | Any compensation fails | Manual intervention required |
| `SagaStuckInRunning` | Saga running >1h | Check logs, consider manual completion |

## 📊 Key Metrics to Watch

### Outbox Health
```promql
# Queue depth
outbox_pending_events_total

# Success rate
sum(rate(outbox_published_events_total[5m])) / 
(sum(rate(outbox_published_events_total[5m])) + sum(rate(outbox_failed_events_total[5m])))

# Latency p95
histogram_quantile(0.95, rate(outbox_publish_duration_seconds_bucket[5m]))
```

### Saga Health
```promql
# Success rate
sum(rate(saga_executions_total{status="completed"}[5m])) / 
sum(rate(saga_executions_total[5m]))

# Active sagas
sum(saga_status_gauge{status="running"})

# Rollback rate
sum(rate(saga_executions_total{status="rolled_back"}[5m]))
```

## 🔧 Quick Actions

### Scale Workers
```bash
# Immediate scale up
kubectl scale deployment/outbox-worker -n sagaz --replicas=10

# Check status
kubectl get hpa -n sagaz outbox-worker-hpa
```

### Check Queue Depth
```sql
SELECT state, COUNT(*) FROM outbox_events GROUP BY state;
```

### View Worker Logs
```bash
kubectl logs -f -n sagaz -l app=outbox-worker --tail=100
```

### Check Dead Letter Queue
```sql
SELECT id, event_type, last_error, created_at 
FROM outbox_events 
WHERE state = 'dead_letter' 
ORDER BY created_at DESC 
LIMIT 20;
```

### Emergency Stop
```bash
# Stop workers
kubectl scale deployment/outbox-worker -n sagaz --replicas=0

# Stop orchestrator
kubectl scale deployment/saga-orchestrator -n sagaz --replicas=0
```

### Restart Services
```bash
# Rolling restart workers
kubectl rollout restart deployment/outbox-worker -n sagaz

# Rolling restart orchestrator
kubectl rollout restart deployment/saga-orchestrator -n sagaz
```

## 📈 Grafana Dashboards

### Saga Orchestration Dashboard
- URL: `/d/saga-orchestration`
- Key Panels: Success Rate, Active Sagas, Execution Duration, Failed Steps

### Outbox Pattern Dashboard
- URL: `/d/outbox-pattern`
- Key Panels: Pending Events, Publish Rate, DLQ, Worker Health, Latency

## 🔍 Investigation Commands

### Find Stuck Sagas
```sql
SELECT saga_id, saga_name, status, created_at, updated_at
FROM sagas 
WHERE status = 'running' 
  AND updated_at < NOW() - INTERVAL '1 hour';
```

### Find High-Retry Events
```sql
SELECT id, event_type, retry_count, last_error
FROM outbox_events 
WHERE retry_count > 5 
  AND state != 'dead_letter'
ORDER BY retry_count DESC;
```

### Check Worker Resource Usage
```bash
kubectl top pods -n sagaz -l app=outbox-worker
```

### View Recent Errors
```bash
kubectl logs -n sagaz -l app=outbox-worker --since=10m | grep -i error
```

## 🔔 Alert Routing

| Severity | Destination | Response Time |
|----------|-------------|---------------|
| Critical | PagerDuty | Immediate |
| Warning | Slack #sage-warnings | 30 minutes |
| Info | Slack #sage-info | Best effort |

## 📞 Escalation

1. **Level 1**: On-call engineer (0-15 min)
2. **Level 2**: Team lead (15-30 min)
3. **Level 3**: Engineering manager (30-60 min)

Slack: #sage-incidents

## 📚 Full Documentation

- **Setup**: `k8s/monitoring/README.md`
- **Runbooks**: `k8s/monitoring/RUNBOOKS.md`
- **Summary**: `k8s/monitoring/IMPLEMENTATION_SUMMARY.md`
