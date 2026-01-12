# CDC (Change Data Capture) Implementation

**Status**: Planned for Q2 2026  
**Priority**: Medium (only when throughput >5K events/sec needed)

---

## Overview

Design documents for implementing Change Data Capture (CDC) support to achieve 10x throughput improvement (5K → 50K+ events/sec) with seamless CLI integration.

---

## Documents

### Core Design
- **[ADR-011: CDC Support](../adr/adr-011-cdc-support.md)** - Full architectural decision record (1300+ lines)
  - PostgreSQL logical replication setup
  - Debezium integration (Kafka, Redis, RabbitMQ sinks)
  - Unified worker design with mode toggle
  - CLI integration (`sagaz init`, `sagaz extend`)
  - Migration strategy and monitoring

### Implementation Guides
- **[Unified Worker Summary](CDC_UNIFIED_WORKER_SUMMARY.md)** - Worker implementation details
  - `WorkerMode` enum (POLLING | CDC)
  - Extending `OutboxWorker` class
  - Environment variables
  - Performance comparison

- **[CLI Integration](CDC_CLI_INTEGRATION.md)** - CLI commands and workflows
  - `sagaz init --outbox-mode=cdc`
  - `sagaz extend --enable-outbox-cdc --hybrid`
  - `sagaz validate` and `sagaz status`
  - Generated file structures
  - Interactive wizard

- **[Design Comparison](CDC_DESIGN_COMPARISON.md)** - Why unified worker vs separate classes
  - Code comparison
  - Deployment comparison
  - Testing comparison
  - Benefits summary

---

## Quick Links

### For Developers
- Implementation effort: **68 hours (8.5 days)**
- Target: **Q2 2026**
- Files to modify:
  - `sagaz/outbox/types.py` - Add `WorkerMode` enum
  - `sagaz/outbox/worker.py` - Extend with CDC support
  - `sagaz/cli/` - Add CDC commands

### For Users
- Zero-config CDC: `sagaz init --outbox-mode=cdc --outbox-broker=kafka`
- Safe migration: `sagaz extend --enable-outbox-cdc --hybrid`
- Performance: 10x throughput (50K+ events/sec)
- No breaking changes: Polling mode remains default

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| ✅ **Unified worker** | Single `OutboxWorker` class with mode toggle, not separate `CDCOutboxWorker` |
| ✅ **CLI integration** | Turnkey setup via `sagaz init`, not manual configuration |
| ✅ **Hybrid mode** | Run polling + CDC in parallel for safe migration |
| ✅ **Backward compatible** | Polling mode default, CDC is opt-in |
| ✅ **Template-driven** | Jinja2 templates for Debezium configs |

---

## When to Use CDC

**Use polling mode (default) when:**
- Throughput < 5K events/sec
- Simple infrastructure preferred
- Don't want to manage Debezium

**Upgrade to CDC mode when:**
- Throughput > 5K events/sec
- Need <50ms latency
- Have Debezium expertise
- Want to reduce database load

---

## Performance Comparison

| Metric | Polling | CDC | Improvement |
|--------|---------|-----|-------------|
| Throughput | 1-5K/sec | 50-100K/sec | **10x** |
| Latency | 100-1000ms | 10-50ms | **20x** |
| DB queries | Constant polling | None | **100%** |
| Infrastructure | Simple | + Debezium | Moderate |

---

## Migration Example

```bash
# Current setup: polling mode
$ sagaz status
Outbox Mode:       Polling
Workers:           3
Throughput:        2,000 events/sec

# Enable CDC in hybrid mode (safe migration)
$ sagaz extend --enable-outbox-cdc --outbox-broker=kafka --hybrid

✓ Backed up configuration
✓ Added Debezium to docker-compose.yml
✓ Generated debezium/kafka.properties

# Start Debezium
$ docker-compose up -d debezium-server

# Monitor hybrid mode
$ sagaz status
Outbox Mode:       Hybrid (polling + CDC)
Workers:           3 polling, 5 CDC
CDC Throughput:    16,000 events/sec
Polling:           2,000 events/sec

# Cutover to CDC-only when ready
$ sagaz extend --remove-polling

✓ Scaled down polling workers

$ sagaz status
Outbox Mode:       CDC (Kafka)
Workers:           5 CDC
Throughput:        48,000 events/sec
```

---

## Dependencies

### Prerequisites
- PostgreSQL 12+ with `wal_level=logical`
- Debezium Server 2.4+
- Message broker (Kafka / Redis / RabbitMQ)

### Sagaz Requirements
- ADR-016: Unified Storage Layer (completed)
- CLI scaffolding from Q1 2026 roadmap

---

## Implementation Phases

1. **Worker Extension** (28 hours)
   - Add `WorkerMode` enum
   - Extend `OutboxWorker` with CDC mode
   - CDC message parsing
   - Tests

2. **CLI Integration** (32 hours)
   - `sagaz init --outbox-mode`
   - `sagaz extend --enable-outbox-cdc`
   - `sagaz validate` CDC checks
   - Interactive wizard

3. **Templates & Docs** (8 hours)
   - Debezium configuration templates
   - Docker Compose templates
   - Migration guide
   - Video tutorial

**Total**: 68 hours (~8.5 days)

---

## See Also

- [Roadmap](../../ROADMAP.md) - Q2 2026 implementation timeline
- [ADR-012: Synchronous Orchestration](../adr/adr-012-synchronous-orchestration-model.md) - Current architecture
- [Outbox Pattern Docs](../../../patterns/outbox/) - Base implementation
