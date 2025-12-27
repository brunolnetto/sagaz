#sagaz Roadmap

Active development roadmap for the sagaz saga pattern library.

## Current Version: 1.0.x

### ✅ Completed Features

| Feature | Version | Status |
|---------|---------|--------|
| Core Saga Pattern | 1.0.0 | ✅ Done |
| Transactional Outbox | 1.0.0 | ✅ Done |
| PostgreSQL Storage | 1.0.0 | ✅ Done |
| RabbitMQ Broker | 1.0.0 | ✅ Done |
| Kafka Broker | 1.0.0 | ✅ Done |
| Redis Broker | 1.0.1 | ✅ Done |
| Kubernetes Deployment | 1.0.0 | ✅ Done |
| Consumer Inbox (Idempotency) | 1.0.0 | ✅ Done |
| Compensation Graph | 1.0.0 | ✅ Done |
| Prometheus Metrics | 1.0.0 | ✅ Done |
| **Unified SagaConfig** | 1.0.3 | ✅ Done |
| **Environment Variable Config** | 1.0.3 | ✅ Done |
| **Mermaid Diagram Generation** | 1.0.3 | ✅ Done |
| **Connected Graph Validation** | 1.0.3 | ✅ Done |
| **Grafana Dashboard Templates** | 1.0.3 | ✅ Done |

---

## Planned Features

### v1.1.0 - Reliability & Observability

**Target**: January 2025 | **Effort**: 16-24 hours (1-2 weeks)

| Feature | Priority | Status | Docs |
|---------|----------|--------|------|
| **Dead Letter Queue Pattern** | High | 📋 Planned | [Docs](patterns/dead-letter-queue.md) |
| **AlertManager Rules Template** | High | 📋 Planned | [Template](monitoring/alertmanager-rules.yml) |
| Batch saga status updates | Low | 📋 Planned | - |

**Checklist**:
- [ ] Implement `DLQHandler` class
- [ ] Add `RetryPolicy` configuration to `SagaConfig`
- [ ] Create DLQ metrics (depth, age, rate)
- [ ] Test AlertManager rules with Prometheus
- [ ] Implement batch status update API
- [ ] Add DLQ CLI commands (`sagaz dlq replay`, `purge`)
- [ ] Write integration tests
- [ ] Update documentation

> ℹ️ **OpenTelemetry tracing** was completed in v1.0.0 (`TracingSagaListener`)

---

### v1.2.0 - Storage Options (Postponed)

| Feature | Priority | Status | Notes |
|---------|----------|--------|-------|
| MySQL storage backend | Low | ⏸️ Postponed | PostgreSQL/Redis covers most use cases |
| CockroachDB compatibility | Low | ⏸️ Postponed | Niche requirement |

---

### v2.0.0 - CDC (Change Data Capture)

**Target**: February 2025 | **Effort**: 26-40 hours (2-3 weeks)

| Feature | Priority | Status | ADR |
|---------|----------|--------|-----|
| **CDC Support (Debezium)** | High | 📋 Planned | [ADR-011](architecture/adr/adr-011-cdc-support.md) |
| CDC Worker implementation | High | 📋 Planned | ADR-011 |
| Native pg_logical support | Medium | 📋 Planned | ADR-011 |
| CDC Prometheus metrics | High | 📋 Planned | ADR-011 |
| CDC Grafana dashboards | High | 📋 Planned | ADR-011 |
| Migration tooling (polling → CDC) | Medium | 📋 Planned | ADR-011 |

**Target throughput**: 50,000+ events/sec

**Checklist**:
- [ ] Create Debezium connector configuration
- [ ] Implement `CDCWorker` class
- [ ] Add Kafka Connect Docker/K8s manifests
- [ ] Implement native `pg_logical` option
- [ ] Add CDC-specific Prometheus metrics
- [ ] Create CDC Grafana dashboard panels
- [ ] Write migration guide (polling → CDC)
- [ ] Performance benchmarks (target: 50k events/sec)
- [ ] Integration tests with Debezium
- [ ] Update documentation

---

### v2.1.0 - Analytics (Fluss + Iceberg)

**Target**: March 2025 | **Effort**: 32-48 hours (3-4 weeks)

| Feature | Priority | Status | Design |
|---------|----------|--------|--------|
| **Fluss Analytics Listener** | High | 📋 Planned | [Design](architecture/fluss-analytics.md) |
| Iceberg tiering integration | High | 📋 Planned | [Design](architecture/fluss-analytics.md) |
| Real-time saga dashboards | Medium | 📋 Planned | - |
| Historical saga analytics | Medium | 📋 Planned | - |
| Trino/Spark query examples | Low | 📋 Planned | - |

**Goal**: Real-time + historical analytics for saga executions.

**Checklist**:
- [ ] Create `FlussClient` wrapper
- [ ] Implement `FlussAnalyticsListener`
- [ ] Define Fluss table schema
- [ ] Configure Iceberg tiering
- [ ] Create Docker Compose for local Fluss setup
- [ ] Build real-time Grafana dashboard
- [ ] Write Flink SQL query examples
- [ ] Write Trino query examples
- [ ] Write Spark query examples
- [ ] Performance testing
- [ ] Update documentation

**Architecture**:
```
Saga → FlussListener → Fluss (real-time) → Iceberg (historical)
                           ↓                      ↓
                     Dashboard              Long-term
                     (sub-second)           analytics
```

---

### v2.2.0 - Event Enrichment & Multi-Sink

**Target**: April 2025 | **Effort**: 16-24 hours (1-2 weeks)

| Feature | Priority | Status | Docs |
|---------|----------|--------|------|
| **Event Enrichment Pipeline** | Medium | 📋 Planned | - |
| Multi-Sink Fan-out | Low | ✅ Supported | [Pattern](patterns/multi-sink-fanout.md) |
| Flink transformation examples | Low | 📋 Planned | - |
| Kafka Streams integration | Low | 📋 Planned | - |

**Goal**: Transform, enrich, and route saga events to multiple destinations.

**Checklist**:
- [ ] Create `EnrichmentListener` base class
- [ ] Implement context enrichment helpers
- [ ] Create Flink job examples (filtering, aggregation)
- [ ] Create Kafka Streams examples
- [ ] Document enrichment patterns
- [ ] Add enrichment configuration to `SagaConfig`
- [ ] Write integration tests
- [ ] Update documentation

---

## Timeline Summary

```
2025 Development Schedule
═══════════════════════════════════════════════════════════════════
       Jan          Feb          Mar          Apr
═══════════════════════════════════════════════════════════════════
   ┌─────────┐  ┌───────────┐  ┌────────────┐  ┌─────────┐
   │ v1.1.0  │  │  v2.0.0   │  │  v2.1.0    │  │ v2.2.0  │
   │ DLQ &   │  │  CDC      │  │  Fluss +   │  │ Enrich  │
   │ Alerts  │  │ Debezium  │  │  Iceberg   │  │ & Sinks │
   └─────────┘  └───────────┘  └────────────┘  └─────────┘
      1-2 wks      2-3 wks        3-4 wks       1-2 wks
═══════════════════════════════════════════════════════════════════
   Total: ~90-136 hours | ~3 months @ 15-20 hrs/week
```

---

## Future Considerations (Community Interest)

| Feature | Notes | Status |
|---------|-------|--------|
| Event sourcing integration | Store saga state as events | 💡 Ideas |
| Saga choreography mode | Event-driven sagas (vs orchestration) | 💡 Ideas |
| Multi-region support | Cross-region saga coordination | 💡 Ideas |
| Cloud-native CDC | AWS DMS, GCP Datastream, Azure | 💡 Ideas |
| Schema registry | Avro/Protobuf event schemas | 💡 Ideas |
| Saga visualization UI | Dashboard for saga monitoring | 💡 Ideas |

---

## Contributing

To propose a new feature:
1. Open a GitHub issue with the feature request
2. If significant, create an ADR in `docs/architecture/`
3. Submit a PR referencing the issue/ADR

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 1.0.3 | 2024-12 | Unified SagaConfig, env var config, test perf |
| 1.0.2 | 2024-12 | CI improvements, Codecov, code quality fixes |
| 1.0.1 | 2024-12 | Redis broker, documentation reorg |
| 1.0.0 | 2024-11 | Initial release |
