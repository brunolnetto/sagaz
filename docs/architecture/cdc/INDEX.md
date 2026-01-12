# CDC Implementation - Document Index

**Location**: `docs/architecture/cdc/`  
**Status**: Design complete, implementation planned for Q2 2026

---

## Quick Navigation

### 📋 Primary Documents

1. **[README.md](README.md)** - Start here for overview
2. **[ADR-011: CDC Support](../adr/adr-011-cdc-support.md)** - Full architectural decision record
3. **[Unified Worker Summary](CDC_UNIFIED_WORKER_SUMMARY.md)** - Worker implementation
4. **[CLI Integration](CDC_CLI_INTEGRATION.md)** - CLI commands and workflows
5. **[CLI Naming Convention](CLI_NAMING_CONVENTION.md)** - Why `--outbox-mode`, not `--cdc-mode`
6. **[Design Comparison](CDC_DESIGN_COMPARISON.md)** - Design rationale

---

## By Role

### For Product Managers
**Goal**: Understand business value and timeline

- Start: [README.md](README.md) - Overview and performance metrics
- Key sections:
  - When to use CDC (throughput thresholds)
  - Performance comparison table
  - Migration example (zero downtime)
  - Implementation timeline: Q2 2026, 68 hours

### For Architects
**Goal**: Understand design decisions and tradeoffs

- Start: [ADR-011](../adr/adr-011-cdc-support.md) - Full ADR
- Key sections:
  - Unified worker vs separate classes: [Design Comparison](CDC_DESIGN_COMPARISON.md)
  - Broker selection matrix (Kafka vs Redis vs RabbitMQ)
  - Migration path (hybrid mode)
  - Risk mitigation

### For Backend Developers
**Goal**: Implement the unified worker

- Start: [Unified Worker Summary](CDC_UNIFIED_WORKER_SUMMARY.md)
- Key sections:
  - Code changes needed (~28 hours)
  - `WorkerMode` enum implementation
  - `_run_cdc_loop()` method
  - CDC message parsing
- Files to modify:
  - `sagaz/outbox/types.py`
  - `sagaz/outbox/worker.py`

### For DevOps Engineers
**Goal**: Setup infrastructure and deployment

- Start: [ADR-011 - Deployment Options](../adr/adr-011-cdc-support.md#deployment-options)
- Key sections:
  - Debezium Server configuration
  - Docker Compose templates
  - Kubernetes manifests
  - Monitoring metrics (Prometheus)

### For CLI/Frontend Developers
**Goal**: Implement CLI commands

- Start: [CLI Integration](CDC_CLI_INTEGRATION.md)
- Key sections:
  - `sagaz init --outbox-mode=cdc` (~32 hours)
  - `sagaz extend --enable-outbox-cdc`
  - `sagaz validate` and `sagaz status`
  - Template rendering (Jinja2)
- Files to create:
  - `sagaz/cli/init.py`
  - `sagaz/cli/extend.py`
  - `sagaz/templates/init/cdc/`

### For QA/Test Engineers
**Goal**: Understand testing strategy

- Start: [Unified Worker Summary - Testing](CDC_UNIFIED_WORKER_SUMMARY.md#testing-comparison)
- Key sections:
  - Parameterized tests for both modes
  - Integration test scenarios
  - Performance benchmarks
  - Migration testing (hybrid mode)

---

## By Task

### "I want to understand CDC at a high level"
→ [README.md](README.md) (10 min read)

### "I need to make an implementation decision"
→ [ADR-011](../adr/adr-011-cdc-support.md) (30 min read)

### "I'm implementing the worker"
→ [Unified Worker Summary](CDC_UNIFIED_WORKER_SUMMARY.md) (15 min read)

### "I'm implementing the CLI"
→ [CLI Integration](CDC_CLI_INTEGRATION.md) (20 min read)

### "I need to justify the unified design"
→ [Design Comparison](CDC_DESIGN_COMPARISON.md) (10 min read)

### "I need to estimate effort"
→ All docs have effort estimates:
- Worker: 28 hours
- CLI: 32 hours
- Templates: 8 hours
- **Total: 68 hours (8.5 days)**

---

## Document Relationships

```
README.md (overview)
    │
    ├──► ADR-011 (full design)
    │       ├──► Unified Worker Summary (implementation)
    │       ├──► CLI Integration (commands)
    │       └──► Design Comparison (rationale)
    │
    └──► When to use CDC
         Performance metrics
         Migration example
```

---

## Key Decisions Summary

| Decision | Document | Rationale |
|----------|----------|-----------|
| Unified worker (not separate) | [Design Comparison](CDC_DESIGN_COMPARISON.md) | Zero code duplication, same tests |
| CLI integration | [CLI Integration](CDC_CLI_INTEGRATION.md) | Turnkey setup, safe migration |
| Hybrid mode support | [ADR-011](../adr/adr-011-cdc-support.md) | Zero downtime migration |
| Backward compatible | [Unified Worker](CDC_UNIFIED_WORKER_SUMMARY.md) | Polling default, CDC opt-in |

---

## Implementation Checklist

### Phase 1: Worker (28h)
- [ ] Add `WorkerMode` enum to `types.py`
- [ ] Extend `OutboxWorker.__init__` with mode parameter
- [ ] Implement `_run_cdc_loop()` method
- [ ] Add CDC message parsing (`_parse_cdc_event`)
- [ ] Update `OutboxConfig` with CDC fields
- [ ] Unit tests for both modes
- [ ] Integration tests (Kafka, Redis, RabbitMQ)

### Phase 2: CLI (32h)
- [ ] `sagaz init --outbox-mode` flag
- [ ] `sagaz extend --enable-outbox-cdc` command
- [ ] `sagaz validate` CDC health checks
- [ ] `sagaz status` CDC metrics display
- [ ] Interactive wizard for CDC setup
- [ ] `.sagaz-config.yml` tracking
- [ ] Jinja2 templates (Debezium configs)
- [ ] CLI integration tests

### Phase 3: Documentation (8h)
- [ ] Migration guide (docs/guides/cdc-migration.md)
- [ ] CLI reference (docs/cli/cdc-commands.md)
- [ ] Video tutorial
- [ ] Blog post
- [ ] Troubleshooting guide

---

## External References

- [PostgreSQL Logical Replication](https://www.postgresql.org/docs/current/logical-replication.html)
- [Debezium Documentation](https://debezium.io/documentation/)
- [Debezium Outbox Pattern](https://debezium.io/documentation/reference/transformations/outbox-event-router.html)
- [Roadmap](../../ROADMAP.md) - Q2 2026 timeline

---

## Questions?

- **Architecture**: See [ADR-011](../adr/adr-011-cdc-support.md)
- **Implementation**: See [Unified Worker Summary](CDC_UNIFIED_WORKER_SUMMARY.md)
- **CLI**: See [CLI Integration](CDC_CLI_INTEGRATION.md)
- **Comparison**: See [Design Comparison](CDC_DESIGN_COMPARISON.md)

---

**Last Updated**: 2026-01-12  
**Status**: Design complete, ready for Q2 2026 implementation  
**Estimated Effort**: 68 hours (8.5 days)
