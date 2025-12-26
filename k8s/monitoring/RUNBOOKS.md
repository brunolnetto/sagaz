# Operational Runbooks -sagaz Saga Pattern

This directory contains operational runbooks for troubleshooting and resolving common issues with the sagaz saga orchestration system.

## Quick Links

- [Saga Issues](#saga-issues)
  - [High Failure Rate](#saga-high-failure-rate)
  - [Stuck Sagas](#saga-stuck-in-running-state)
  - [Compensation Failures](#compensation-failures)
  - [High Latency](#saga-high-latency)
  
- [Outbox Issues](#outbox-issues)
  - [Worker Down](#outbox-worker-down)
  - [High Lag](#outbox-high-lag)
  - [Dead Letter Queue](#dead-letter-queue)
  - [Publish Failures](#publish-failures)

- [General Procedures](#general-procedures)
  - [Scaling Workers](#scaling-workers)
  - [Emergency Stop](#emergency-stop)
  - [Data Recovery](#data-recovery)

---

## Saga Issues

### Saga High Failure Rate

**Alert:** `SagaHighFailureRate`  
**Severity:** Critical  
**Threshold:** >5% failure rate for 5 minutes

#### Symptoms
- Increased saga failures across multiple saga types
- Users reporting transaction failures
- Downstream service errors

#### Investigation Steps

1. **Check failure distribution:**
   ```bash
   # View failures by saga type
   kubectl logs -n sagaz -l app=saga-orchestrator --tail=1000 | grep "status=failed"
   
   # Query Prometheus
   sum by (saga_name) (rate(saga_executions_total{status="failed"}[5m]))
   ```

2. **Identify failing steps:**
   ```bash
   # Check step failures
   sum by (saga_name, step_name) (rate(saga_step_executions_total{status="failed"}[5m]))
   ```

3. **Review recent deployments:**
   ```bash
   kubectl rollout history deployment -n sagaz
   ```

4. **Check downstream service health:**
   ```bash
   # Check service endpoints
   kubectl get endpoints -n sagaz
   
   # Check service logs
   kubectl logs -n sagaz -l app=<failing-service>
   ```

#### Resolution Steps

**If specific saga type failing:**
1. Identify failing step from logs
2. Check downstream service health
3. Review service configuration
4. Consider circuit breaker activation

**If widespread failures:**
1. Check database connectivity
2. Verify network policies
3. Review resource constraints
4. Check for quota exhaustion

**Immediate Mitigation:**
```bash
# Pause saga execution for specific type (requires feature flag)
kubectl set env deployment/saga-orchestrator -n sagaz PAUSE_SAGA_<TYPE>=true

# Scale down if needed
kubectl scale deployment/saga-orchestrator -n sagaz --replicas=1
```

**Recovery:**
```bash
# Resume execution
kubectl set env deployment/saga-orchestrator -n sagaz PAUSE_SAGA_<TYPE>=false

# Scale back up
kubectl scale deployment/saga-orchestrator -n sagaz --replicas=3
```

#### Post-Incident
- Review logs and metrics
- Update saga timeout configurations
- Improve error handling in failing steps
- Add circuit breaker if not present

---

### Saga Stuck in Running State

**Alert:** `SagaStuckInRunning`  
**Severity:** Critical  
**Threshold:** Saga running >1 hour without completion

#### Symptoms
- Sagas not completing
- Resources locked indefinitely
- User transactions appear hung

#### Investigation Steps

1. **Identify stuck sagas:**
   ```bash
   # Query database
   kubectl exec -n sagaz postgresql-0 -- psql -U sagaz -c \
     "SELECT saga_id, saga_name, status, created_at, updated_at 
      FROM sagas 
      WHERE status = 'running' 
      AND updated_at < NOW() - INTERVAL '1 hour';"
   ```

2. **Check saga state:**
   ```bash
   # Get saga details
   kubectl exec -n sagaz postgresql-0 -- psql -U sagaz -c \
     "SELECT * FROM sagas WHERE saga_id = '<saga_id>';"
   
   # Get saga steps
   kubectl exec -n sagaz postgresql-0 -- psql -U sagaz -c \
     "SELECT * FROM saga_steps WHERE saga_id = '<saga_id>' ORDER BY step_order;"
   ```

3. **Review orchestrator logs:**
   ```bash
   kubectl logs -n sagaz -l app=saga-orchestrator | grep "<saga_id>"
   ```

#### Resolution Steps

**Manual saga completion:**
```sql
-- Connect to database
kubectl exec -it -n sagaz postgresql-0 -- psql -U sagaz

-- Update saga status
UPDATE sagas 
SET status = 'failed', 
    updated_at = NOW(),
    error_message = 'Manual intervention - timeout'
WHERE saga_id = '<saga_id>';

-- Trigger compensations if needed
UPDATE sagas 
SET should_compensate = true
WHERE saga_id = '<saga_id>';
```

**Restart orchestrator:**
```bash
kubectl rollout restart deployment/saga-orchestrator -n sagaz
```

**Increase timeouts (if pattern persists):**
```yaml
# Update configmap
kubectl edit configmap saga-config -n sagaz

# Add or update:
data:
  SAGA_STEP_TIMEOUT: "300"  # 5 minutes
  SAGA_OVERALL_TIMEOUT: "1800"  # 30 minutes
```

#### Prevention
- Implement step-level timeouts
- Add healthcheck endpoints to saga steps
- Use circuit breakers for downstream calls
- Configure appropriate retry policies

---

### Compensation Failures

**Alert:** `CompensationFailures`  
**Severity:** Critical  
**Threshold:** Any compensation failure

#### Symptoms
- Compensations failing to execute
- Inconsistent state across services
- Manual cleanup required

#### Investigation Steps

1. **Identify failed compensations:**
   ```bash
   # Check logs
   kubectl logs -n sagaz -l app=saga-orchestrator | grep "compensation.*failed"
   
   # Query metrics
   sum by (saga_name, step_name) (saga_compensations_total{status="failed"})
   ```

2. **Get saga details:**
   ```sql
   -- Failed compensations
   SELECT s.saga_id, s.saga_name, ss.step_name, ss.compensation_status, ss.error_message
   FROM sagas s
   JOIN saga_steps ss ON s.saga_id = ss.saga_id
   WHERE ss.compensation_status = 'failed';
   ```

3. **Check compensating service:**
   ```bash
   kubectl logs -n sagaz -l app=<service> --tail=100
   ```

#### Resolution Steps

**Retry compensation manually:**
```python
# Usingsagaz CLI or admin API
sage retry-compensation --saga-id <saga_id> --step <step_name>
```

**Manual cleanup (last resort):**
1. Document current state
2. Execute manual compensation actions
3. Update saga state in database:
   ```sql
   UPDATE saga_steps 
   SET compensation_status = 'completed',
       compensated_at = NOW()
   WHERE saga_id = '<saga_id>' AND step_name = '<step>';
   
   UPDATE sagas 
   SET status = 'rolled_back',
       updated_at = NOW()
   WHERE saga_id = '<saga_id>';
   ```

#### Critical Actions
- **DO NOT** mark as complete without verifying cleanup
- **ALWAYS** document manual interventions
- **IMMEDIATELY** investigate root cause

#### Prevention
- Ensure compensations are idempotent
- Add comprehensive error handling
- Test compensation logic thoroughly
- Implement compensation health checks

---

## Outbox Issues

### Outbox Worker Down

**Alert:** `OutboxWorkerDown`  
**Severity:** Critical  
**Threshold:** No workers running for 2 minutes

#### Symptoms
- No events being published
- Outbox table filling up
- Message lag increasing

#### Investigation Steps

1. **Check pod status:**
   ```bash
   kubectl get pods -n sagaz -l app=outbox-worker
   kubectl describe pods -n sagaz -l app=outbox-worker
   ```

2. **Check recent events:**
   ```bash
   kubectl get events -n sagaz --sort-by='.lastTimestamp' | grep outbox-worker
   ```

3. **Review logs:**
   ```bash
   kubectl logs -n sagaz -l app=outbox-worker --previous
   ```

#### Resolution Steps

**Immediate:**
```bash
# Force restart
kubectl rollout restart deployment/outbox-worker -n sagaz

# If pods are stuck
kubectl delete pods -n sagaz -l app=outbox-worker --force --grace-period=0
```

**If startup failures:**
```bash
# Check configmap
kubectl get configmap -n sagaz outbox-config -o yaml

# Check secrets
kubectl get secret -n sagazsagaz-secrets -o yaml

# Verify connectivity to broker
kubectl run -it --rm debug --image=nicolaka/netshoot -n sagaz -- bash
# Inside pod:
telnet kafka-service 9092
```

**Rollback if needed:**
```bash
kubectl rollout undo deployment/outbox-worker -n sagaz
```

#### Post-Resolution
- Monitor pending events: `outbox_pending_events_total`
- Verify publish rate recovers
- Review worker logs for errors
- Update deployment if configuration issue found

---

### Outbox High Lag

**Alert:** `OutboxHighLag`  
**Severity:** Critical  
**Threshold:** >10,000 pending events for 10 minutes

#### Symptoms
- Growing outbox table
- Delayed event delivery
- Increasing latency

#### Investigation Steps

1. **Check pending count:**
   ```sql
   SELECT state, COUNT(*) 
   FROM outbox_events 
   GROUP BY state;
   ```

2. **Check worker health:**
   ```bash
   kubectl top pods -n sagaz -l app=outbox-worker
   kubectl logs -n sagaz -l app=outbox-worker --tail=100
   ```

3. **Check broker health:**
   ```bash
   # For Kafka
   kubectl exec -n sagaz kafka-0 -- kafka-broker-api-versions \
     --bootstrap-server localhost:9092
   
   # For RabbitMQ
   kubectl exec -n sagaz rabbitmq-0 -- rabbitmqctl status
   ```

4. **Analyze event age:**
   ```sql
   SELECT 
     MIN(created_at) as oldest,
     MAX(created_at) as newest,
     COUNT(*) as total,
     AVG(EXTRACT(EPOCH FROM (NOW() - created_at))) as avg_age_seconds
   FROM outbox_events 
   WHERE state = 'pending';
   ```

#### Resolution Steps

**Scale workers horizontally:**
```bash
# Increase replicas
kubectl scale deployment/outbox-worker -n sagaz --replicas=5

# Verify scaling
kubectl get hpa -n sagaz
```

**Optimize batch size:**
```yaml
# Update configmap
kubectl edit configmap outbox-config -n sagaz

# Increase batch size
data:
  OUTBOX_BATCH_SIZE: "100"
  OUTBOX_POLL_INTERVAL: "1"
```

**Emergency: Direct publish (use with caution):**
```python
# Emergency script to publish oldest events
import asyncio
from sagaz.outbox.worker import OutboxWorker

async def emergency_publish():
    worker = OutboxWorker(...)
    await worker.process_batch(batch_size=500)

asyncio.run(emergency_publish())
```

**If broker is bottleneck:**
```bash
# Scale Kafka partitions
kubectl exec -n sagaz kafka-0 -- kafka-topics \
  --alter --topic saga-events \
  --partitions 10 \
  --bootstrap-server localhost:9092

# Scale RabbitMQ
kubectl scale statefulset/rabbitmq -n sagaz --replicas=3
```

#### Monitoring
```bash
# Watch metrics
watch -n 5 'kubectl exec -n sagaz postgresql-0 -- psql -U sagaz -c \
  "SELECT state, COUNT(*) FROM outbox_events GROUP BY state;"'
```

#### Prevention
- Configure HPA for workers
- Set up broker monitoring
- Implement backpressure mechanisms
- Regular load testing

---

### Dead Letter Queue

**Alert:** `OutboxDeadLetterQueue`  
**Severity:** Critical  
**Threshold:** >5 events in DLQ in 10 minutes

#### Symptoms
- Events moved to DLQ
- Repeated failures after max retries
- Data loss risk

#### Investigation Steps

1. **Query DLQ events:**
   ```sql
   SELECT 
     id,
     aggregate_id,
     event_type,
     state,
     retry_count,
     last_error,
     created_at
   FROM outbox_events 
   WHERE state = 'dead_letter'
   ORDER BY created_at DESC 
   LIMIT 50;
   ```

2. **Analyze failure patterns:**
   ```sql
   SELECT 
     event_type,
     COUNT(*) as count,
     last_error
   FROM outbox_events 
   WHERE state = 'dead_letter'
   GROUP BY event_type, last_error;
   ```

3. **Check broker logs:**
   ```bash
   kubectl logs -n sagaz -l app=kafka --tail=200 | grep -i error
   ```

#### Resolution Steps

**Analyze and fix root cause:**
1. Identify common error pattern
2. Fix configuration/code issue
3. Deploy fix

**Replay DLQ events:**
```sql
-- Move back to pending (after fixing root cause)
UPDATE outbox_events 
SET state = 'pending',
    retry_count = 0,
    last_error = NULL,
    next_retry_at = NOW()
WHERE state = 'dead_letter'
  AND event_type = '<fixed_event_type>';
```

**Manual processing:**
```python
# Script to manually process DLQ
from sagaz.outbox.storage import get_storage

async def process_dlq():
    storage = get_storage()
    dlq_events = await storage.get_dead_letter_events(limit=100)
    
    for event in dlq_events:
        try:
            # Process manually
            await broker.publish(event)
            await storage.mark_as_published(event.id)
        except Exception as e:
            log.error(f"Failed to process {event.id}: {e}")
```

**Create incident record:**
```bash
# Document DLQ events for audit
kubectl exec -n sagaz postgresql-0 -- psql -U sagaz -c \
  "COPY (SELECT * FROM outbox_events WHERE state = 'dead_letter') \
   TO '/tmp/dlq_$(date +%Y%m%d).csv' CSV HEADER;"
```

#### Prevention
- Implement better retry strategies
- Add circuit breakers
- Improve error handling
- Set up DLQ monitoring dashboard
- Regular DLQ review process

---

## General Procedures

### Scaling Workers

**When to scale:**
- High pending event count
- Worker CPU/memory usage >80%
- Publish latency increasing

**Horizontal scaling:**
```bash
# Manual scaling
kubectl scale deployment/outbox-worker -n sagaz --replicas=5

# Configure HPA
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: outbox-worker-hpa
  namespace:sagaz
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: outbox-worker
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Pods
    pods:
      metric:
        name: outbox_pending_events_total
      target:
        type: AverageValue
        averageValue: "1000"
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
EOF
```

**Vertical scaling:**
```yaml
# Update resources
kubectl patch deployment outbox-worker -n sagaz -p '
{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "outbox-worker",
          "resources": {
            "requests": {
              "cpu": "1000m",
              "memory": "1Gi"
            },
            "limits": {
              "cpu": "2000m",
              "memory": "2Gi"
            }
          }
        }]
      }
    }
  }
}'
```

### Emergency Stop

**When to use:**
- Cascading failures
- Data corruption detected
- Security incident

**Steps:**
```bash
# 1. Stop workers
kubectl scale deployment/outbox-worker -n sagaz --replicas=0

# 2. Stop orchestrator
kubectl scale deployment/saga-orchestrator -n sagaz --replicas=0

# 3. Verify no active processing
kubectl get pods -n sagaz

# 4. Document reason
echo "Emergency stop: $(date) - Reason: <reason>" >> /tmp/emergency_stop.log
```

**Recovery:**
```bash
# 1. Verify issue resolved
# 2. Restore orchestrator
kubectl scale deployment/saga-orchestrator -n sagaz --replicas=3

# 3. Restore workers gradually
kubectl scale deployment/outbox-worker -n sagaz --replicas=1
# Monitor for 5 minutes
kubectl scale deployment/outbox-worker -n sagaz --replicas=3
```

### Data Recovery

**Backup current state:**
```bash
# Backup database
kubectl exec -n sagaz postgresql-0 -- pg_dump -U sagazsagaz > backup_$(date +%Y%m%d_%H%M%S).sql

# Backup to S3
kubectl exec -n sagaz postgresql-0 -- pg_dump -U sagazsagaz | \
  aws s3 cp - s3://backups/sage/sage_$(date +%Y%m%d_%H%M%S).sql
```

**Recover from backup:**
```bash
# Restore database
cat backup_20231223_120000.sql | \
  kubectl exec -i -n sagaz postgresql-0 -- psql -U sagazsagaz
```

**Query stuck sagas:**
```sql
-- Find sagas to recover
SELECT saga_id, saga_name, status, created_at 
FROM sagas 
WHERE status IN ('running', 'pending')
  AND created_at < NOW() - INTERVAL '1 day';
```

---

## Contact and Escalation

**On-Call:** Check PagerDuty rotation  
**Slack Channel:** #sage-incidents  
**Team:** Platform Engineering  
**Documentation:** https://github.com/yourorg/sage/wiki

### Escalation Path
1. Level 1: On-call engineer (0-15 min)
2. Level 2: Team lead (15-30 min)  
3. Level 3: Engineering manager (30-60 min)
4. Level 4: VP Engineering (>60 min critical)
