# Fluss + Iceberg Analytics Architecture

## Overview

This document describes the integration of **Apache Fluss** (streaming lakehouse) with **Apache Iceberg** (table format) to provide real-time and historical analytics for Sagaz saga executions.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Saga Application                                │
│    ┌─────────────┐    ┌─────────────────────────────────────────────────┐   │
│    │   Sagaz     │───▶│           SagaListener(s)                       │   │
│    │   Saga      │    │  ┌─────────────┐  ┌─────────────────────────┐   │   │
│    │  Executor   │    │  │   Outbox    │  │   Fluss Analytics       │   │   │
│    └─────────────┘    │  │  Listener   │  │      Listener           │   │   │
│                       │  └──────┬──────┘  └───────────┬─────────────┘   │   │
│                       └─────────┼─────────────────────┼─────────────────┘   │
└─────────────────────────────────┼─────────────────────┼─────────────────────┘
                                  │                     │
                                  ▼                     ▼
                          ┌───────────────┐     ┌───────────────┐
                          │  PostgreSQL   │     │    Apache     │
                          │  Outbox Table │     │    Fluss      │
                          └───────┬───────┘     │  (Real-time)  │
                                  │             └───────┬───────┘
                                  │ CDC                 │ Tiering
                                  ▼                     ▼
                          ┌───────────────┐     ┌───────────────┐
                          │   Debezium    │     │    Apache     │
                          │   Connector   │     │   Iceberg     │
                          └───────┬───────┘     │ (Historical)  │
                                  │             └───────┬───────┘
                                  ▼                     │
                          ┌───────────────┐             │
                          │    Apache     │             │
                          │    Kafka      │◀────────────┘
                          └───────┬───────┘
                                  │
                                  ▼
                          ┌───────────────────────────────────────┐
                          │         Query Engines                  │
                          │  ┌─────────┐ ┌─────────┐ ┌─────────┐  │
                          │  │  Trino  │ │  Spark  │ │StarRocks│  │
                          │  └─────────┘ └─────────┘ └─────────┘  │
                          └───────────────────────────────────────┘
```

## Components

### 1. Fluss Analytics Listener

A `SagaListener` implementation that publishes saga events directly to Fluss:

```python
from sagaz.listeners import SagaListener

class FlussAnalyticsListener(SagaListener):
    """
    Publishes saga lifecycle events to Apache Fluss for real-time analytics.
    Events are automatically tiered to Iceberg for historical analysis.
    """
    
    def __init__(self, fluss_client: FlussClient, table_name: str = "saga_events"):
        self.fluss = fluss_client
        self.table = table_name
    
    async def on_saga_started(self, saga_id: str, saga_name: str, context: dict):
        await self._publish({
            "event_type": "saga_started",
            "saga_id": saga_id,
            "saga_name": saga_name,
            "timestamp": datetime.utcnow().isoformat(),
            "context_keys": list(context.keys()),
        })
    
    async def on_step_completed(
        self, saga_id: str, step_name: str, result: Any, duration_ms: int
    ):
        await self._publish({
            "event_type": "step_completed",
            "saga_id": saga_id,
            "step_name": step_name,
            "duration_ms": duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def on_step_failed(
        self, saga_id: str, step_name: str, error: Exception, duration_ms: int
    ):
        await self._publish({
            "event_type": "step_failed",
            "saga_id": saga_id,
            "step_name": step_name,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "duration_ms": duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def on_compensation_completed(
        self, saga_id: str, step_name: str, duration_ms: int
    ):
        await self._publish({
            "event_type": "compensation_completed",
            "saga_id": saga_id,
            "step_name": step_name,
            "duration_ms": duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def on_saga_completed(self, saga_id: str, total_duration_ms: int):
        await self._publish({
            "event_type": "saga_completed",
            "saga_id": saga_id,
            "total_duration_ms": total_duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def on_saga_rolled_back(self, saga_id: str, total_duration_ms: int):
        await self._publish({
            "event_type": "saga_rolled_back",
            "saga_id": saga_id,
            "total_duration_ms": total_duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def _publish(self, event: dict):
        await self.fluss.write(self.table, event)
```

### 2. Fluss Table Schema

```sql
CREATE TABLE saga_events (
    event_id        STRING,
    event_type      STRING,      -- saga_started, step_completed, step_failed, etc.
    saga_id         STRING,
    saga_name       STRING,
    step_name       STRING,
    duration_ms     BIGINT,
    total_duration_ms BIGINT,
    error_type      STRING,
    error_message   STRING,
    context_keys    ARRAY<STRING>,
    timestamp       TIMESTAMP,
    
    -- Partitioning for efficient queries
    PRIMARY KEY (event_id) NOT ENFORCED
) WITH (
    'bucket.num' = '8',
    'tiered.storage.enabled' = 'true',
    'tiered.storage.format' = 'iceberg',
    'tiered.storage.path' = 's3://analytics-bucket/saga-events/'
);
```

### 3. Iceberg Tiering Configuration

Fluss automatically tiers data to Iceberg based on:
- **Time-based**: Events older than X hours move to Iceberg
- **Size-based**: When Fluss partition exceeds size threshold

```yaml
# fluss-conf.yaml
tiered.storage:
  enabled: true
  format: iceberg
  iceberg:
    catalog: hive  # or rest, glue, nessie
    warehouse: s3://analytics-bucket/warehouse/
  retention:
    hot-data-hours: 24  # Keep 24h in Fluss for real-time
    cold-data-days: 365  # Keep 1 year in Iceberg
```

## Data Flow

### Real-time Path (< 1 second latency)

```
Saga Execution → FlussListener → Fluss → Dashboard/Alerts
```

Use cases:
- Live saga monitoring dashboard
- Real-time alerting on failures
- Current saga throughput metrics

### Historical Path (batch analytics)

```
Fluss → Auto-tier → Iceberg → Trino/Spark → Reports
```

Use cases:
- Saga duration trends over time
- Step failure rate analysis
- Compensation frequency by saga type
- SLA compliance reports

## Example Queries

### Real-time (Flink SQL on Fluss)

```sql
-- Current running sagas
SELECT saga_id, saga_name, timestamp
FROM saga_events
WHERE event_type = 'saga_started'
  AND saga_id NOT IN (
    SELECT saga_id FROM saga_events 
    WHERE event_type IN ('saga_completed', 'saga_rolled_back')
  );

-- Failure rate last 5 minutes
SELECT saga_name,
       COUNT(*) FILTER (WHERE event_type = 'step_failed') AS failures,
       COUNT(*) FILTER (WHERE event_type = 'step_completed') AS successes
FROM saga_events
WHERE timestamp > CURRENT_TIMESTAMP - INTERVAL '5' MINUTE
GROUP BY saga_name;
```

### Historical (Trino/Spark on Iceberg)

```sql
-- Average saga duration by type (last 30 days)
SELECT saga_name,
       AVG(total_duration_ms) AS avg_duration_ms,
       PERCENTILE(total_duration_ms, 0.95) AS p95_duration_ms,
       COUNT(*) AS total_sagas
FROM saga_events
WHERE event_type IN ('saga_completed', 'saga_rolled_back')
  AND timestamp > CURRENT_DATE - INTERVAL '30' DAY
GROUP BY saga_name;

-- Most frequently failing steps
SELECT step_name,
       COUNT(*) AS failure_count,
       COUNT(DISTINCT saga_id) AS affected_sagas
FROM saga_events
WHERE event_type = 'step_failed'
  AND timestamp > CURRENT_DATE - INTERVAL '7' DAY
GROUP BY step_name
ORDER BY failure_count DESC
LIMIT 10;

-- Compensation analysis
SELECT saga_name,
       step_name,
       AVG(duration_ms) AS avg_comp_duration_ms,
       COUNT(*) AS compensation_count
FROM saga_events
WHERE event_type = 'compensation_completed'
GROUP BY saga_name, step_name
ORDER BY compensation_count DESC;
```

## Dashboard Metrics

### Real-time Panel (Fluss)
- Active sagas count
- Sagas started/completed per minute
- Current failure rate
- Average step duration (sliding window)

### Historical Panel (Iceberg)
- Daily/weekly saga trends
- Step duration heatmaps
- Failure pattern analysis
- SLA compliance percentage

## Benefits

| Aspect | Benefit |
|--------|---------|
| **Unified Storage** | Single data copy for stream and batch |
| **Low Latency** | Sub-second for real-time dashboards |
| **Cost Efficient** | Hot data in Fluss, cold in Iceberg on object storage |
| **Query Flexibility** | Flink for streaming, Trino/Spark for batch |
| **Schema Evolution** | Iceberg handles schema changes gracefully |
| **Time Travel** | Query historical snapshots via Iceberg |

## Future Enhancements

1. **ML Integration**: Train anomaly detection models on saga patterns
2. **Predictive Alerts**: Predict saga failures before they happen
3. **Cost Attribution**: Track saga execution costs by team/service
4. **Capacity Planning**: Forecast saga volume trends

## Related Documents

- [ADR-012: Sagaz v1.0 Synchronous Orchestration](adr/012-synchronous-orchestration.md)
- [Distributed Saga Design v2.0](design/distributed-saga-v2.md)
- [Outbox Pattern Implementation](../brokers/README.md)
