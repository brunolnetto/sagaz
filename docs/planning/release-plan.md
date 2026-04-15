# Scoped Release Plan — sagaz 2026

> **Last updated**: 2026-04-08  
> **Current version**: 1.1.2  
> **Strategy**: Minimum-disruption, scoped releases. Each wave ships only additive/isolated features. Core-invasive changes are deferred to later waves.

---

## Guiding Principles

| Principle | Application |
|-----------|-------------|
| **No core churn early** | PRs that extend `Saga.__init__` or `Saga.add_step()` (e.g. #70, #72) ship last |
| **New modules are cheap** | Pure additive modules (new package dirs, new CLI commands) ship early and often |
| **Each wave stands alone** | Every release tag ships on `main` after its wave merges to `develop` |
| **Blocking issues resolve before their PR merges** | #102 gates #70; #104 gates #72 |
| **Docs and CI ship first** | Governance/compliance changes are lowest risk and highest signal |
| **Redis Streams as light-weight broker** | A `RedisStreamsEventBus` ships alongside choreography so distributed use requires only Redis — not Kafka or RabbitMQ |

---

## Wave Map

```
Wave 0  ─── v1.5.0 ──────── Governance & lightweight ops  (no core changes)
Wave 1  ─── v1.6.0 ──────── Storage extensions             (storage/ layer only)
Wave 1b ─── v1.7.0 ──────── SCXML state machine migration  (core/execution only — ADR-038)
Wave 2  ─── v1.8.0 ──────── Analytics & chaos              (new sagaz[analytics] extra)
Wave 3  ─── v1.9.0 ──────── CLI v2 + CDC + tenancy         (service/infra expansion)
Wave 4  ─── v1.10.0 ─────── Event-driven choreography      (new execution model)
Wave 5  ─── v2.0.0 ──────── Core extensions                (saga.add_step wired — blocked)
```

---

## Wave 0 — v1.5.0 "Governance & Lightweight Ops"

**Target**: April / May 2026  
**Risk**: Very low — no code touching the core `Saga` execution path  
**Merge order**: #82 → #61 → (docs overhaul PR)

| PR | Branch | Feature | Issue | Merge pre-req |
|----|--------|---------|-------|--------------|
| #82 | docs/release-dag | Release DAG + ADR status refresh | #83 | none |
| #61 | feature/alertmanager-rules | AlertManager rules template | #45 | none |
| docs/stale-content-cleanup | *(planned)* | Stale docs fix (versions, paths, ADR statuses) | — | none |

**Notes**:
- `#82` is docs-only; merge first so subsequent PRs include updated ADR references.
- `#61` ships YAML files only — zero Python risk.
- Docs overhaul PR (planned) fixes version numbers, `saga/` → `sagaz/` paths, ADR-019/025 status.

---

## Wave 1 — v1.6.0 "Storage Extensions"

**Target**: May 2026  
**Risk**: Low — extends `sagaz/storage/` and `sagaz/outbox/` only  
**Merge order**: #62 → #63 → #60 → feature/statechart-saga-state-management

| PR | Branch | Feature | Issue | Merge pre-req |
|----|--------|---------|-------|--------------|
| #62 | feature/sqlite-backend | SQLite storage + outbox backend | #46 | none |
| #63 | feature/storage-data-transfer | Storage migration/transfer layer | #47 | #62 (SQLite src/dst) |
| #60 | feature/dead-letter-queue | Dead Letter Queue (DLQ) pattern | #44 | none |
| *(new)* | feature/statechart-saga-state-management | StateChart migration + `configuration` storage field (ADR-038 Phase 1) | #188 | #62 (SQLite schema) |

**Gap watch** (from review report):
- #62: no unit tests — add before merge (see issue #105)
- #60: no fill-and-replay integration test — add before merge (see issue #106)
- ADR-038 Phase 1: verify `SagaSnapshot.create` accepts `configuration` kwarg; add round-trip tests for all 4 storage backends

---

## Wave 2 — v1.8.0 "Analytics & Chaos"

**Target**: May / June 2026  
**Risk**: Low — new `sagaz[analytics]` optional extra, chaos is opt-in  
**Merge order**: #79 → #74 → #71 → #67

| PR | Branch | Feature | Issue | Merge pre-req |
|----|--------|---------|-------|--------------|
| #79 | feature/chaos-engineering | ChaosMonkey injection (ADR-017) | #78 | none |
| #74 | feature/sqldim-analytics-pipeline | sqldim OLTP analytics pipeline | #73 | none |
| #71 | feature/visualization-ui | Saga visualization dashboard (ADR-035) | #58 | none |
| #67 | feature/fluss-iceberg-analytics | Fluss streaming + Iceberg tiering (ADR-013) | #51 | none |

**Gap watch**:
- #79: add real `Saga` E2E integration test through `ChaosMonkey` → compensation fires (see issue #111)
- #81: versioning deferred to Wave 3 (depends on schema validation closure — see issue #112)
- #71: add SSE endpoint smoke test; document CORS/auth policy (see issue #113)

---

## Wave 3 — v1.9.0 "CLI v2 + CDC + Tenancy + Versioning"

**Target**: June / July 2026  
**Risk**: Medium — CDC requires Docker/Kafka in integration tests; tenancy extends executor layer  
**Merge order**: #81 → #64 → #65 → #68 → #66

| PR | Branch | Feature | Issue | Merge pre-req |
|----|--------|---------|-------|--------------|
| #81 | feature/saga-versioning | Saga versioning & schema evolution (ADR-018) | #80 | issue #109 closed |
| #64 | feature/cli-local-dev | CLI v1.0 local dev commands | #48 | none |
| #65 | feature/cli-cloud-deploy | CLI v2.0 multi-cloud deploy | #49 | #64 |
| #68 | feature/multi-tenancy | Multi-tenancy support (ADR-020) | #54 | none |
| #66 | feature/cdc-debezium | CDC support via Debezium (ADR-011) | #50 | none |

**Gap watch**:
- #81: persistent registry (not just in-memory) — address before merge
- #68: no cross-tenant storage-level test — track post-merge
- #66: no real Postgres replication slot integration test (testcontainers) — track post-merge

---

## Wave 4 — v1.10.0 "Event-Driven Choreography"

**Target**: August / September 2026  
**Risk**: Medium — new execution model but fully isolated from `Saga` class  
**Merge order**: feature/redis-streams-eventbus → #69

| PR | Branch | Feature | Issue | Merge pre-req |
|----|--------|---------|-------|--------------|
| #115 | feature/redis-streams-eventbus | `RedisStreamsEventBus` — distributed choreography bus | #108 | none |
| #69 | feature/saga-choreography | Saga choreography engine (ADR-029) | #56 | #115 merged |

**Notes**:
- PR #115 (`feature/redis-streams-eventbus`) implements `RedisStreamsEventBus` using Redis Streams (XADD/XREADGROUP) — no Kafka or RabbitMQ needed.
- Once shipped, saga choreography works without heavy brokers — only `sagaz[redis]` extra is required.
- `#69` review gap (issue #114): add compensating event / choreographed rollback integration test.

---

## Wave 5 — v2.0.0 "Core Extensions" *(blocked)*

**Target**: October - December 2026  
**Risk**: High — wires new behaviour into `Saga.__init__` and `Saga.add_step()`  
**Merge order**: fix/event-sourcing-wiring → #70 → fix/region-affinity-wiring → #72

| PR / Branch | Feature | Issue | Merge pre-req |
|-------------|---------|-------|--------------|
| fix/event-sourcing-wiring *(planned)* | Wire `enable_event_sourcing=True` into `Saga.__init__` + execution hooks | #102 | none |
| #70 | feature/event-sourcing | Event sourcing module (ADR-033) | #57 | #102 closed |
| fix/region-affinity-wiring *(planned)* | Add `region=` to `SagaStep` and `Saga.add_step()` | #104 | none |
| #72 | feature/multi-region-coordination | Multi-region saga coordination (ADR-034) | #59 | #104 closed |

---

## Blocking Issues Tracker

| Issue | Blocks PR | Status | Summary |
|-------|-----------|--------|---------|
| #102 | #70 | 🔴 Open | `enable_event_sourcing=True` not wired into `Saga.__init__` |
| #104 | #72 | 🔴 Open | `region=` param absent from `Saga.add_step()` |

---

## Quality Gap Issues — "Should Fix Before Wave Merge"

| Issue | Affects PR / Wave | Summary |
|-------|-------------------|---------|
| #109 | #62 / Wave 1 | Add SQLite unit tests |
| #110 | #60 / Wave 1 | Add DLQ fill-and-replay integration test |
| #111 | #79 / Wave 2 | Add E2E chaos test: real Saga + ChaosMonkey → compensation fires |
| #112 | #81 / Wave 3 | Add runtime schema validation + persistent registry to saga versioning |
| #113 | #71 / Wave 2 | Add SSE smoke test; document CORS/auth policy for viz UI |
| #114 | #69 / Wave 4 | Add compensating-event integration test for choreographed rollback |
| #108 | #115 / Wave 4 | ✅ Closed — Redis Streams EventBus adapter (PR #115) |

---

## Cross-Cutting Items

| Item | Description | When |
|------|-------------|------|
| `@pytest.mark.parametrize` | All 16 code PRs lack parametrize coverage — global quality follow-up | Post Wave 3 |
| Durable event store | Event sourcing v2 (PostgreSQL/SQLite backend) | Wave 5 follow-up |
| Broker adapters for #66, #69 | Kafka/RabbitMQ integration beyond in-memory | Post Wave 4 |
| Auth/CORS policy | FastAPI viz server (#71) | Wave 2 / pre-release |

---

## Dependency Graph

```
#82 (docs)         ──────────────────────────────────────────► Wave 0
#61 (alertmgr)     ──────────────────────────────────────────► Wave 0
                                                               
#62 (sqlite)       ──────────────────────────────────────────► Wave 1
#60 (dlq)          ──────────────────────────────────────────► Wave 1
#63 (storage-tx)   after #62 ──────────────────────────────► Wave 1
                                                               
#79 (chaos)        ──────────────────────────────────────────► Wave 2
#67 (fluss)        ──────────────────────────────────────────► Wave 2
#74 (sqldim)       ──────────────────────────────────────────► Wave 2
#71 (viz)          ──────────────────────────────────────────► Wave 2
                                                               
#64 (cli-local)    ──────────────────────────────────────────► Wave 3
#81 (versioning)   needs #109 closed ──────────────────────► Wave 3
#65 (cli-cloud)    after #64 ─────────────────────────────── Wave 3
#68 (tenancy)      ──────────────────────────────────────────► Wave 3
#66 (cdc)          ──────────────────────────────────────────► Wave 3
                                                               
redis-streams-bus  ──────────────────────────────────────────► Wave 4 (new)
#69 (choreography) after redis-streams-bus ─────────────────► Wave 4
                                                               
fix/#102           ──────────────────────────────────────────► Wave 5
#70 (event-src)    after fix/#102 ──────────────────────────► Wave 5
fix/#104           ──────────────────────────────────────────► Wave 5
#72 (multi-region) after fix/#104 ──────────────────────────► Wave 5
```

---

## Version Map (target)

| Version | Wave | Quarter | Notes |
|---------|------|---------|-------|
| v1.5.0  | 0    | Q2 2026 | Governance & ops |
| v1.6.0  | 1    | Q2 2026 | Storage extensions |
| v2.0.0  | 2    | Q2/Q3 2026 | Analytics & chaos |
| v2.1.0  | 3    | Q3 2026 | CLI + CDC + tenancy |
| v2.2.0  | 4    | Q3 2026 | Choreography + Redis Streams |
| v2.3.0  | 5    | Q4 2026 | Core extensions |

---

## Related Documents

- [docs/planning/release-review-next.md](release-review-next.md) — CI/ADR compliance report for all 17 PRs
- [docs/ROADMAP.md](../ROADMAP.md) — Strategic timeline and feature backlog
- [docs/architecture/adr/README.md](../architecture/adr/README.md) — ADR index
