#sagaz Roadmap

Active development roadmap for thesagaz saga pattern library.

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

---

## Planned Features

### v1.1.0 - Performance & Observability

| Feature | Priority | Status | ADR |
|---------|----------|--------|-----|
| Batch status updates | High | 📋 Planned | - |
| OpenTelemetry tracing | Medium | ✅ Done | - |
| Grafana dashboard templates | Medium | 📋 Planned | - |

### v1.2.0 - Storage Options

| Feature | Priority | Status | ADR |
|---------|----------|--------|-----|
| MySQL storage backend | Medium | 📋 Planned | - |
| CockroachDB compatibility | Low | 📋 Planned | - |

### v2.0.0 - CDC (Change Data Capture)

| Feature | Priority | Status | ADR |
|---------|----------|--------|-----|
| **CDC Support (Debezium)** | High | 📋 Planned | [ADR-011](architecture/adr-011-cdc-support.md) |
| CDC Worker implementation | High | 📋 Planned | ADR-011 |
| Native pg_logical support | Medium | 📋 Planned | ADR-011 |
| CDC Prometheus metrics | High | 📋 Planned | ADR-011 |
| CDC Grafana dashboards | High | 📋 Planned | ADR-011 |
| Migration tooling (polling → CDC) | Medium | 📋 Planned | ADR-011 |

**Target throughput**: 50,000+ events/sec

---

## Feature Details

### CDC Support (v2.0.0)

**Goal**: Enable high-throughput event processing via Change Data Capture.

**Scope**:
- Debezium connector configuration
- CDC Worker that consumes from Kafka
- Native PostgreSQL logical replication option
- Prometheus metrics for CDC monitoring
- Grafana dashboard panels
- Migration guide from polling to CDC

**Design**: See [ADR-011: CDC Support](architecture/adr-011-cdc-support.md)

**Dependencies**:
- Kafka infrastructure
- Debezium / Kafka Connect
- Updated monitoring stack

**Estimated Effort**: ~26 hours (3-4 days)

---

## Future Considerations

| Feature | Notes |
|---------|-------|
| Event sourcing integration | Store saga state as events |
| Saga choreography mode | Event-driven sagas (vs orchestration) |
| Multi-region support | Cross-region saga coordination |
| Cloud-native CDC | AWS DMS, GCP Datastream, Azure |
| Schema registry | Avro/Protobuf event schemas |

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
| 1.0.1 | 2024-12 | Redis broker, documentation reorg |
| 1.0.0 | 2024-11 | Initial release |
