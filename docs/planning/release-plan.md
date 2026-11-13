# Scoped Release Plan — sagaz 2026

> **Last updated**: 2026-11-13
> **Current version**: 1.7.2
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
Wave 1b ─── v1.7.0 ──────── StateChart migration, Phase 1  (core/execution + snapshots/storage — ADR-040)
Wave 2  ─── v1.8.0 ──────── Analytics & chaos              (new sagaz[analytics] extra)
Wave 3  ─── v1.9.0 ──────── CLI v2 + CDC + tenancy         (service/infra expansion)
Wave 4  ─── v1.10.0 ─────── Event-driven choreography      (new execution model)
Wave 5  ─── v2.0.0 ──────── Core extensions                (saga.add_step wired — blocked)
Wave 6  ─── v2.1.0 ─────── Streaming & historical analytics (Fluss + Iceberg; post-core stabilization)
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

**Status**: Released 2026-11-10; GitHub tag/release and PyPI wheel + sdist are published
**Risk**: Medium — persistent storage, cross-backend data integrity, and outbox recovery
**Original feature merge order**: #62 → #63 → #60 (all three feature PRs are merged into `develop`)

| PR | Branch | Feature | Issue | Current status |
|----|--------|---------|-------|----------------|
| #62 | feature/sqlite-backend | SQLite storage + outbox backend | #46 | Merged; SQLite extra, legacy schema handling, and unit coverage present |
| #63 | feature/storage-data-transfer | Storage migration/transfer layer | #47 | Merged via PR #351; local unit/regression coverage passed; container integration evidence remains incomplete |
| #60 | feature/dead-letter-queue | Dead Letter Queue (DLQ) pattern | #44 | Merged via PR #350; RabbitMQ + SQLite lifecycle integration test passed locally |

**Validation record (2026-11-10)**:
- #62: SQLite Saga/Outbox unit coverage, legacy outbox schema backfill, and the optional `sagaz[sqlite]` extra are present.
- #63: [PR #351](https://github.com/brunolnetto/sagaz/pull/351) adds canonical serialization, schema upgrades, full-content validation/checksums, PostgreSQL archive transfer, and migration integrity safeguards. The local backend/migration unit batch reported 163 passed and 3 skipped. The skipped container-dependent tests mean live PostgreSQL/Redis migration behavior has not been fully verified in that run. Pause outbox workers during transfer/cutover.
- #60: [PR #350](https://github.com/brunolnetto/sagaz/pull/350) adds the SQLite + RabbitMQ DLQ lifecycle integration test. Local result: 1 passed. The corresponding GitHub integration job was skipped.
- CI: several GitHub Actions checks were blocked/failing, so this was not a fully green CI release. v1.6.0 was nevertheless published after explicit acceptance of the documented CI and container-integration limitations.
- **Outstanding validation**: run the PostgreSQL/Redis container-dependent migration tests before claiming full cross-backend integration coverage. Do not describe those paths as verified until they pass.


---

## Wave 1b — v1.7.0 "StateChart Migration — Phase 1"

**Target**: After v1.6.0 promotion; release timing subject to PR merge, full-suite CI, and package verification

**Risk**: Medium — execution lifecycle compatibility and persistent configuration schema evolution
**Scope**: ADR-040 Phase 1 only; no compound/parallel statechart execution

| Item | Scope | Acceptance / evidence |
|------|-------|-----------------------|
| Issue #188 | Migrate `SagaStateMachine` and `SagaStepStateMachine` to `StateChart` | Preserve flat Saga behavior and legacy runtime flags |
| State inspection | Expose serializable active configuration while preserving `current_state` compatibility | Real StateChart lifecycle assertions for pending → executing → completed |
| Snapshots | Persist configuration in Saga status and snapshot serialization | Historical snapshots without configuration fall back to `[status]` |
| Storage API | Add optional `configuration: list[str]` to `save_saga_state` | Existing callers remain compatible through `[status.value]` fallback |
| Backends | Preserve configuration in Memory, Redis, SQLite, and PostgreSQL | Backend round-trip, storage transfer, and legacy schema tests |
| Schema evolution | Idempotent SQLite and PostgreSQL upgrades | Existing rows retained and backfilled from scalar status |

**Validation record (local, 2026-11-10)**:
- Combined Phase 1 regression suite: **989 passed**.
- Focused StateChart + snapshot regression: **98 passed**.
- Ruff and `git diff --check`: passed.
- This is local validation evidence, not a claim that the GitHub Actions release workflow is green. The full release test suite and PR CI must still pass before publication.

**Explicit exclusions**:
- StateChart Phase 2 compound/parallel execution (#190; historical implementation PR #191) remains deferred and is not a v1.7.0 dependency.
- ChaosMonkey and chaos-pattern demonstrations belong to the v1.8.0 Analytics & Chaos scope, not v1.7.0.
- Do not close the v1.7.0 milestone until the StateChart Phase 1 implementation is merged to `develop`, promoted to `main`, and release gates are verified.


---

## Wave 2 — v1.8.0 "Analytics & Chaos"

**Target**: After v1.7.0; schedule to be confirmed
**Risk**: Low — new `sagaz[analytics]` optional extra, chaos is opt-in
**Merge order**: #79 → #74 → #71 → (#254 ∥ #258) → #257

| PR | Branch | Feature | Issue | Merge pre-req |
|----|--------|---------|-------|--------------|
| #79 | feature/chaos-engineering | ChaosMonkey injection (ADR-017) | #78 | none — rebase against `main` required; CI is fully red |
| #74 | feature/sqldim-analytics-pipeline | sqldim OLTP analytics pipeline | #73 | none — rebase required; CI is fully red |
| #71 | feature/visualization-ui-clean | Saga visualization dashboard (ADR-035) | #58 | none — lint/sec/CodeQL ✅; unit tests not yet wired in CI |
| #254 | feature/otel-tracing-demo | Demo: observability otel_tracing | #248 | #74 merged (sqldim is the referenced feature) |
| #258 | feature/optimization-guide-demo | Demo: performance optimization_guide | #252 | #71 merged (visualization is the referenced feature) |
| #257 | feature/chaos-patterns-demo | Demo: reliability chaos_patterns | #251 | #79 merged — explicitly blocked until ChaosMonkey is in `main` |

**Scope decision (2026-11-12 → updated 2026-11-13)**:
- Issue #51 and PR #67 are intentionally excluded from v1.8.0 and have been moved to **v2.1.0 (Wave 6)** (GitHub milestone #18).
- Demo PRs #254, #257, #258 and their linked issues #248, #251, #252 remain in v1.8.0 as they are demonstration modules for Wave 2 features.

**CI status (2026-11-13)**:
- #79: all CI checks failing — branch must be rebased and CI fixed before merge.
- #74: all CI checks failing — branch must be rebased and CI fixed before merge.
- #71: CI unavailable; gates reproduced locally (ruff, format, mypy, radon strict, bandit, commitlint, unit matrix 3.11/3.12/3.13 with `--cov-fail-under=95`).
- #254, #258: all CI checks passing — ready for review and merge.
- #257: all CI checks passing — merge after #79 lands.

**Gap watch**:
- #79: add real `Saga` E2E integration test through `ChaosMonkey` → compensation fires (see issue #111)
- #81: versioning deferred to Wave 3 (depends on schema validation closure — see issue #112)
- #71: issue #58/#113 acceptance criteria implemented (run list, run detail, per-run SSE, runtime diagram, metrics summary, 5-view HTML, `sagaz[monitor]` alias, `docs/monitoring/visualization-ui.md` incl. CORS/auth policy). Mermaid is fetched lazily by the monitor, SHA-384 verified and cached on disk (not bundled, no browser CDN). Branch pushed as `feature/visualization-ui-clean`; PR #71 head is still `feature/visualization-ui` and must be retargeted. Open: `.coveragerc` uses `concurrency = multiprocessing` without `thread`, so TestClient-handled code is under-reported repo-wide.

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

## Wave 6 — v2.1.0 "Streaming & Historical Analytics"

**GitHub milestone**: [#18](https://github.com/brunolnetto/sagaz/milestone/18)
**Target**: After Wave 5 (v2.0.0) has shipped and the core extensions have stabilized; no calendar date committed
**Risk**: High — streaming delivery, failure recovery, and historical table tiering require end-to-end reliability evidence
**Scope**: Issue #51 — Fluss streaming analytics + Apache Iceberg historical tiering (ADR-013)
**Merge order**: #67

| PR | Branch | Feature | Issue | Entry condition |
|----|--------|---------|-------|-----------------|
| #67 | feature/fluss-iceberg-analytics | Fluss streaming + Iceberg tiering | #51 | Rebase/rework against current `main`; complete all acceptance gates below |

**Release gates**:
- Fluss lifecycle events are delivered and verified under a real integration test (including the 1,000-Saga / 1-second acceptance target).
- Fluss-to-Iceberg tiering completes end to end, with a query verifying the expected historical row count.
- Buffer/flush failures cannot silently lose events; async paths do not perform blocking network I/O on the event loop.
- Local Fluss + MinIO services, the tiering job, Grafana dashboard, and the monitoring guide are delivered and exercised.
- The two monitoring modules meet the issue's 90%+ coverage target.

**Planning note**: PR #67 is an implementation starting point, not a release-ready commitment. Its current branch must be reconciled with `main` and re-reviewed against the reliability and integration gates before it is admitted to the wave.

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
#74 (sqldim)       ──────────────────────────────────────────► Wave 2
#71 (viz)          ──────────────────────────────────────────► Wave 2
#254 (otel demo)   after #74 ──────────────────────────────► Wave 2
#258 (perf demo)   after #71 ──────────────────────────────► Wave 2
#257 (chaos demo)  after #79 ──────────────────────────────► Wave 2

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

#67/#51 (Fluss+Iceberg) ─ after Wave 5 stabilization ───────► Wave 6 (v2.1.0)
```

---

## Version Map

> **Reconciled 2026-11-13.** The authoritative mapping is the Wave Map above. The stale alternative table (which assigned v2.0.0–v2.3.0 to Waves 2–5) has been removed. Wave 6 is now assigned **v2.1.0** — it follows Wave 5 (v2.0.0) and is registered as GitHub milestone #18.

| Version | Wave | Title | Status |
|---------|------|-------|--------|
| v1.5.0  | 0    | Governance & Lightweight Ops | Released |
| v1.6.0  | 1    | Storage Extensions | Released |
| v1.7.0  | 1b   | StateChart Migration Phase 1 | Released |
| v1.8.0  | 2    | Analytics & Chaos | In progress |
| v1.9.0  | 3    | CLI v2 + CDC + Tenancy | Planned |
| v1.10.0 | 4    | Event-Driven Choreography | Planned |
| v2.0.0  | 5    | Core Extensions | Blocked |
| v2.1.0  | 6    | Streaming & Historical Analytics | Deferred (post-Wave 5) |

---

## Related Documents

- [docs/planning/release-review-next.md](release-review-next.md) — CI/ADR compliance report for all 17 PRs
- [docs/ROADMAP.md](../ROADMAP.md) — Strategic timeline and feature backlog
- [docs/architecture/adr/README.md](../architecture/adr/README.md) — ADR index
