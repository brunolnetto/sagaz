# Next Release — Feature PR Review Report

> Generated: 2026-04-08  
> Scope: ADR compliance · CI · Lint · Radon complexity · Coverage gaps  
> Base branch: `develop`

---

## Summary

| Category | Result |
|---|---|
| Total PRs reviewed | 17 (PRs #60–#74, #79, #81, #82) |
| CI failures | **0** across all 17 PRs ✅ |
| Ruff lint errors | **0** across all 17 PRs ✅ |
| Radon CI gate violations (grade C+) | **0** across all 17 PRs ✅ |
| Radon watch items (grade B) | Concentrated in `sagaz/cli/app.py` — pre-existing infra ⚠️ |
| High-risk branches for merge | PR #70, PR #72 (features not wired to core `Saga` class) |

---

## CI Status

All 17 PRs: **0 CI failures** ✅

| PR | Branch | CI |
|---|---|---|
| #60 | feature/dead-letter-queue | ✅ |
| #61 | feature/alertmanager-rules | ✅ |
| #62 | feature/sqlite-backend | ✅ |
| #63 | feature/storage-data-transfer | ✅ |
| #64 | feature/cli-local-dev | ✅ |
| #65 | feature/cli-cloud-deploy | ✅ |
| #66 | feature/cdc-debezium | ✅ |
| #67 | feature/fluss-iceberg-analytics | ✅ |
| #68 | feature/multi-tenancy | ✅ |
| #69 | feature/saga-choreography | ✅ |
| #70 | feature/event-sourcing | ✅ |
| #71 | feature/visualization-ui | ✅ |
| #72 | feature/multi-region-coordination | ✅ |
| #74 | feature/sqldim-analytics-pipeline | ✅ |
| #79 | feature/chaos-engineering | ✅ |
| #81 | feature/saga-versioning | ✅ |
| #82 | docs/release-dag | ✅ |

---

## Radon Complexity

> CI gate uses `--min C`. Grade-B functions are acceptable but worth monitoring.

| PR | Branch | B-grade count | Source |
|---|---|---|---|
| #60 | dead-letter-queue | 13 | `sagaz/cli/app.py` (cumulative CLI — pre-existing) |
| #70 | event-sourcing | 12 | `sagaz/cli/app.py` + `SagaSummaryProjection` |
| #63 | storage-data-transfer | 9 | `sagaz/cli/app.py` |
| #72 | multi-region-coordination | 10+ | `sagaz/cli/app.py` + `MultiRegionCoordinator.dispatch_step` |
| #68 | multi-tenancy | 1 | `TenantAwareSagaExecutor._validate_tenant` |
| #69 | saga-choreography | 0 | ✅ |
| #79 | chaos-engineering | 0 | ✅ |
| #81 | saga-versioning | 0 | ✅ |

`sagaz/cli/app.py` score is cumulative across CLI-adding branches. No new algorithmic complexity violations found.

---

## ADR Compliance Review

### PR #79 — `feature/chaos-engineering` → ADR-017

| Component | Status |
|---|---|
| `ChaosMonkey`, `DisabledChaosMonkey`, `ChaosReport` | ✅ |
| Failure / timeout / latency injection | ✅ |
| Per-step targeting, `is_active` property | ✅ |
| E2E: real Saga run → compensation fires on injected failure | ⚠️ Missing |
| Seeded reproducibility test | ⚠️ Missing |

**Verdict**: Core API complete. Add one integration test (real `Saga` + `ChaosMonkey` → compensation).

---

### PR #81 — `feature/saga-versioning` → ADR-018

| Component | Status |
|---|---|
| `SagaVersion`, `VersionRegistry`, migration strategies | ✅ |
| `VersionResolver`, `SagaVersionedMixin`, custom exceptions | ✅ |
| Runtime context schema validation | ⚠️ Not implemented |
| Persistent registry (storage-backed) | ⚠️ In-memory only |
| Live-saga migration integration test | ⚠️ Missing |

**Verdict**: Versioning primitives solid. Three ADR gaps: schema validation, persistent registry, live-migration test.

---

### PR #68 — `feature/multi-tenancy` → ADR-020

| Component | Status |
|---|---|
| `TenantContext`, tiers, quotas, enforcement levels | ✅ |
| `TenantRegistry` CRUD, `TenantAwareSagaExecutor` | ✅ |
| Cross-tenant isolation, feature flags, immutable context | ✅ |
| Storage-level SQL schema partitioning | ⚠️ Deferred — logical isolation only |
| Cross-tenant data-leakage test from storage | ⚠️ Missing |

---

### PR #69 — `feature/saga-choreography` → ADR-029

| Component | Status |
|---|---|
| `ChoreographedSaga`, `@on_event`, wildcard, `EventBus`, engine | ✅ |
| Event history, handler exception isolation, E2E chain | ✅ |
| Compensating events / choreographed rollback | ⚠️ No test |
| Broker adapter (Kafka / RabbitMQ) | ⚠️ In-memory bus only |

---

### PR #70 — `feature/event-sourcing` → ADR-033

| Component | Status |
|---|---|
| `SagaEvent` hierarchy (8 types), frozen events | ✅ |
| `InMemoryEventStore`, snapshot threshold, projection | ✅ |
| CLI `event-log` command (text + JSON) | ✅ |
| `enable_event_sourcing=True` wired into `Saga` execution | ⛔ **Not implemented** |
| PostgreSQL durable store | ⚠️ In-memory only |

**Risk ⚠️**: Event sourcing is a standalone module — not connected to `Saga` execution. Tracked in issue #102.

---

### PR #72 — `feature/multi-region-coordination` → ADR-034

| Component | Status |
|---|---|
| `Region`, `RegionRegistry`, `RegionHealth`, `VectorClock` | ✅ |
| Conflict resolution (LWW, FWW, Manual), failover, health probe | ✅ |
| CLI `region list` / `region failover` | ✅ |
| `Saga.add_step(region=...)` per-step affinity | ⛔ **Not implemented** |
| Cross-region broker routing (real) | ⚠️ Mock executor only |

**Risk ⚠️**: Per-step region affinity is the ADR's primary API surface and is missing. Tracked in issue #104.

---

## Per-Branch Audit Table

| PR | Branch | New files | Tests | Key gaps |
|---|---|---|---|---|
| #60 | dead-letter-queue | 6 | 34 | No fill-and-replay integration test |
| #61 | alertmanager-rules | 0 (YAML) | 14 | No PromQL syntax validation |
| #62 | sqlite-backend | 0 | 11 | No SQLite unit tests |
| #63 | storage-data-transfer | 2 | 20 | No real-backend integration test |
| #64 | cli-local-dev | 1 | 11 | No `show_compensation=False` test |
| #65 | cli-cloud-deploy | 1 | 18 | Helm/Terraform output not validated |
| #66 | cdc-debezium | 4 | 19 | No real Postgres replication slot test |
| #67 | fluss-iceberg-analytics | 2 | 27 | Missing `on_step_compensated` hook test |
| #68 | multi-tenancy | 2 | 65 | No storage-level isolation |
| #69 | saga-choreography | 5 | 29 | No compensation via events |
| #70 | event-sourcing | 5 | 35 | **Feature not wired to core** → issue #102 |
| #71 | visualization-ui | 2 | 16 | SSE endpoint untested; no auth/CORS |
| #72 | multi-region-coordination | 3 | 32 | **`add_step(region=)` missing** → issue #104 |
| #74 | sqldim-analytics-pipeline | 4 | 23 | No empty saga_id edge case |
| #79 | chaos-engineering | 4 | 31 | No real Saga E2E through ChaosMonkey |
| #81 | saga-versioning | 8 | 47 | No schema validation; registry in-memory |
| #82 | docs/release-dag | docs only | — | ✅ |

---

## Cross-Cutting Gaps

| Gap | Branches |
|---|---|
| No `@pytest.mark.parametrize` usage | All 16 code PRs |
| Durable (non-memory) backend not implemented | #70, #81 |
| Broker/network integration missing | #66, #69, #72 |
| Feature not wired into core `Saga` class | **#70** (event sourcing), **#72** (region affinity) |
| No auth/security tests for new HTTP endpoints | #71 (FastAPI visualization server) |

---

## Action Items

### Blocking (create follow-up PRs before main release)

| Issue | PR | Action |
|---|---|---|
| #102 | #70 | Wire `enable_event_sourcing` into `Saga.__init__` and execution path |
| #104 | #72 | Implement `region=` param in `Saga.add_step()` |

### Should-fix (quality)

- **#79**: Add integration test — real `Saga` run through `ChaosMonkey` → compensation fires
- **#81**: Add runtime schema validation test
- **#71**: Add SSE smoke test; document CORS/auth policy

### Nice-to-have (post-merge)

- Add `@pytest.mark.parametrize` globally (candidate for a global quality follow-up issue)
- Broker adapters for #66 and #69 (tracked in respective ADRs as future work)

---

## PR #100 — Maintenance Workflow

- **Status**: Merged ✅ (squash, closes #99)
- `ci/auto-label-prs` branch → `develop`
- Dependency auto-labeling (Dependabot/Renovate) + branch-prefix type labels now active
