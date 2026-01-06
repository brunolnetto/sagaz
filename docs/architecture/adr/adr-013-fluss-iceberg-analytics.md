# ADR-013: Fluss + Iceberg Analytics Integration

## Status

**Proposed** | Date: 2026-01-05 | Priority: Low | Target: Future

## Dependencies

**Prerequisites**:
- ADR-021: Context Streaming (streaming data pipelines)
- ADR-025: Event Triggers (consume analytics events)

**Roadmap**: **Phase 5 (Future/Optional)** - Only for real-time analytics use cases

## Context

Sagaz provides saga orchestration with compensation support. As organizations scale their saga usage, they need:

1. **Real-time monitoring**: Sub-second visibility into running sagas
2. **Historical analytics**: Trends, patterns, and SLA compliance over time
3. **Operational insights**: Step bottlenecks, failure patterns, compensation frequency

Traditional approaches have limitations:

| Approach | Limitation |
|----------|------------|
| Application logs | Hard to query, no aggregations |
| Metrics only | Limited dimensionality, no drill-down |
| Data warehouse ETL | High latency (minutes to hours) |
| Streaming + Batch | Two systems, data duplication |

## Decision

We will integrate **Apache Fluss** as the streaming lakehouse storage layer, with automatic tiering to **Apache Iceberg** for historical analytics.

### Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Sagaz App  │────▶│   Fluss     │────▶│  Iceberg    │
│             │     │ (Real-time) │     │(Historical) │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                   │
                           ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐
                    │  Flink SQL  │     │Trino/Spark  │
                    │ (Streaming) │     │  (Batch)    │
                    └─────────────┘     └─────────────┘
```

### Key Components

1. **FlussAnalyticsListener**: A `SagaListener` that publishes saga lifecycle events to Fluss
2. **Fluss Table**: Stores saga events with columnar format (Apache Arrow)
3. **Iceberg Tiering**: Automatic migration of cold data to Iceberg
4. **Query Layer**: Flink for real-time, Trino/Spark for historical

### Why Fluss?

| Feature | Benefit |
|---------|---------|
| Sub-second latency | Real-time dashboards |
| Columnar storage (Arrow) | Efficient analytics queries |
| Changelog support | Track state changes |
| Flink integration | Native streaming support |
| Lakehouse tiering | Automatic Iceberg migration |

### Why Iceberg?

| Feature | Benefit |
|---------|---------|
| Open table format | Vendor-neutral, widely supported |
| Schema evolution | Handle schema changes gracefully |
| Time travel | Query historical snapshots |
| Partition evolution | Optimize queries over time |
| ACID transactions | Consistent reads during writes |

## Alternatives Considered

### Alternative 1: Direct Iceberg (No Fluss)

Write directly to Iceberg via Flink or Spark Streaming.

**Pros**:
- Simpler architecture
- Fewer components

**Cons**:
- Higher latency (seconds to minutes)
- No sub-second streaming queries
- Batch-oriented, not real-time

**Decision**: Rejected - need sub-second latency for monitoring.

### Alternative 2: Kafka + ClickHouse

Use Kafka for streaming and ClickHouse for OLAP.

**Pros**:
- Proven technology stack
- Very fast analytics

**Cons**:
- Two separate systems
- Data duplication
- More operational overhead
- ClickHouse is not a lakehouse (vendor lock-in)

**Decision**: Rejected - prefer unified architecture with open formats.

### Alternative 3: Apache Paimon

Use Paimon as the streaming lakehouse.

**Pros**:
- Similar capabilities to Fluss
- Strong Flink integration

**Cons**:
- Less mature for real-time queries
- Fluss is purpose-built for streaming analytics

**Decision**: Considered - Fluss chosen for sub-second streaming focus.

### Alternative 4: Databricks/Snowflake

Use managed cloud lakehouse.

**Pros**:
- Fully managed
- Enterprise support

**Cons**:
- Vendor lock-in
- High cost at scale
- Less control

**Decision**: Rejected - prefer open-source, self-hosted option.

## Consequences

### Positive

1. **Unified data model**: Single source of truth for saga events
2. **Sub-second monitoring**: Real-time operational dashboards
3. **Historical analytics**: Trend analysis, capacity planning
4. **Open formats**: Iceberg is vendor-neutral
5. **Cost efficient**: Hot/cold tiering optimizes storage costs
6. **Query flexibility**: Multiple query engines supported

### Negative

1. **Infrastructure complexity**: Requires Fluss cluster deployment
2. **Learning curve**: Teams need to learn Fluss/Iceberg
3. **Operational overhead**: More components to monitor
4. **Flink dependency**: Heavy integration with Flink ecosystem

### Mitigations

| Risk | Mitigation |
|------|------------|
| Complexity | Provide Kubernetes/Docker deployment templates |
| Learning curve | Documentation, examples, Grafana dashboards |
| Operational overhead | Prometheus metrics, alerting templates |
| Flink dependency | Fluss can work with other engines too |

## Implementation Plan

### Phase 1: Foundation (v2.1.0)
- [ ] Create `FlussAnalyticsListener`
- [ ] Define Fluss table schema
- [ ] Basic Iceberg tiering configuration
- [ ] Docker Compose setup for local development

### Phase 2: Dashboards (v2.1.0)
- [ ] Grafana dashboard templates
- [ ] Real-time saga monitoring panel
- [ ] Historical analytics panel
- [ ] Example Flink SQL queries

### Phase 3: Advanced (v2.2.0)
- [ ] Trino/Spark query examples
- [ ] Anomaly detection (ML integration)
- [ ] SLA compliance reporting
- [ ] Cost attribution

## Event Schema

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
    
    PRIMARY KEY (event_id) NOT ENFORCED
) WITH (
    'bucket.num' = '8',
    'tiered.storage.enabled' = 'true',
    'tiered.storage.format' = 'iceberg'
);
```

## References

- [Apache Fluss (Incubating)](https://fluss.apache.org/)
- [Apache Iceberg](https://iceberg.apache.org/)
- [Fluss Analytics Architecture](../fluss-analytics.md)
- [ADR-011: CDC Support](adr-011-cdc-support.md)
- [ADR-012: Synchronous Orchestration Model](adr-012-synchronous-orchestration-model.md)

## Decision Makers

- @brunolnetto (Maintainer)

## Changelog

| Date | Change |
|------|--------|
| 2024-12-27 | Initial proposal |
