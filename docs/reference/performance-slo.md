# Performance SLO Baseline

**Last measured**: 2026-04-11  
**Test suite**: `pytest tests/` — 2628 tests, 100 % coverage  
**Hardware**: CI runner (8 vCPU, 16 GB RAM), Python 3.14

---

## Purpose

This document captures the **measured performance envelope** of the Sagaz saga
execution engine.  Numbers here serve three purposes:

1. **Regression detection** — a future release that degrades latency by more
   than 2× in any SLO tier should require explicit sign-off before merging.
2. **Capacity planning** — operators can size infrastructure based on the
   per-step overhead imposed by the framework rather than business logic.
3. **Competitive positioning** — allows direct comparison with other
   distributed-transaction frameworks under equivalent conditions.

> All numbers below are **framework overhead only** — they exclude
> application-level I/O (database writes, HTTP calls, etc.).

---

## SLO Tiers

| Tier | Scope | p50 target | p95 target | Measurement method |
|------|-------|-----------|-----------|-------------------|
| **T1 — Step execution** | Single step, in-memory | < 5 ms | < 25 ms | Unit test suite |
| **T2 — Compensation** | Single compensation, in-memory | < 5 ms | < 120 ms | Unit test suite |
| **T3 — Parallel batch (DAG)** | 3-step parallel batch | < 10 ms | < 650 ms | Unit test suite |
| **T4 — Outbox dispatch** | Single event, in-memory broker | < 5 ms | < 15 ms | Unit test suite |
| **T5 — Storage (PostgreSQL)** | Read/write cycle, loopback | < 100 ms | < 1 500 ms | Integration test suite |
| **T6 — Sustained throughput** | 100 sagas, sequential | < 15 s total | — | Integration test suite |

---

## Measured Baselines (April 2026)

### T1 — Saga Step Execution (in-memory, no I/O)

| Metric | Value |
|--------|-------|
| Sample size | 2 478 unit tests |
| Mean latency | 20 ms |
| p50 latency | **2.7 ms** |
| p95 latency | 55 ms |
| p99 latency | 510 ms |
| Max observed | 2 585 ms _(sustained-load outlier)_ |

> p99 and max are dominated by a single `test_sustained_load` test (10 s) that
> validates framework behaviour under back-pressure.  Exclude that test for
> steady-state step overhead: p99 ≈ 55 ms.

### T2 — Compensation Execution (in-memory)

| Metric | Value |
|--------|-------|
| Sample size | 149 compensation test cases |
| Mean latency | 29 ms |
| p50 latency | **1.6 ms** |
| p95 latency | 107 ms |
| Max observed | 1 556 ms |

> Higher p95 than step execution reflects tests that exercise multi-step
> cascading compensation chains.

### T3 — Parallel DAG Batch (in-memory)

| Metric | Value |
|--------|-------|
| Sample size | 19 DAG test cases |
| Mean latency | 37 ms |
| p50 latency | **2.3 ms** |
| p95 latency | 615 ms |
| Max observed | 615 ms |

> p95 reflects tests that include all three `ParallelFailureStrategy` paths
> (`FAIL_FAST`, `WAIT_ALL`, `FAIL_FAST_WITH_GRACE`) with simulated failures.

### T4 — Outbox Event Dispatch (in-memory broker)

| Metric | Value |
|--------|-------|
| Sample size | 540 outbox test cases |
| Mean latency | 10 ms |
| p50 latency | **3.1 ms** |
| p95 latency | 13.6 ms |
| Max observed | 1 010 ms |

### T5 — Storage Backend Latency (Docker / loopback network)

| Backend | p50 | p95 | Max |
|---------|-----|-----|-----|
| In-memory | < 1 ms | < 2 ms | < 10 ms |
| SQLite (file) | < 2 ms | < 5 ms | < 20 ms _(estimate)_ |
| Redis (loopback) | ~20 ms | ~120 ms | 3 260 ms _(TTL TTL-expiry test)_ |
| PostgreSQL (loopback) | ~20 ms | ~1 225 ms | 10 008 ms _(cleanup + vacuum)_ |

> Redis and PostgreSQL numbers are measured against Docker containers via
> `testcontainers`; add ~1–3 ms for network hop in real deployments.

### T6 — Sustained Load

`test_sustained_load` runs 100 sequential sagas end-to-end against the
in-process orchestrator:

| Metric | Value |
|--------|-------|
| Total wall time | ≈ 10 s |
| Per-saga overhead | ≈ 100 ms |
| Memory increase | monitored for growth (none expected) |

---

## How to Reproduce

```bash
# Full suite with timings
pytest tests/ \
  --json-report --json-report-file=report.json \
  --cov=sagaz --cov-report=json \
  --durations=50 -q

# Parse baselines
python3 - <<'EOF'
import json
data = json.load(open("report.json"))
tests = data["tests"]
unit = [t for t in tests if "unit" in t["nodeid"]]
durs = sorted([t["call"]["duration"]*1000 for t in unit if t.get("call")])
n = len(durs)
print(f"p50={durs[n//2]:.1f}ms  p95={durs[int(n*.95)]:.1f}ms  max={max(durs):.0f}ms")
EOF
```

---

## Regression Policy

A PR that regresses any SLO tier **by more than 2×** (i.e., doubles the p95)
must include:

1. A justification comment in the PR description explaining the trade-off.
2. An update to the relevant row in this document.
3. Sign-off from one additional reviewer.

For regressions of less than 2× no special process is required, but the
baseline table should still be updated alongside the PR.

---

## Roadmap Targets

| Version | Target improvement |
|---------|--------------------|
| v2.0 | p95 step execution < 20 ms (currently 55 ms) |
| v2.1 | Storage p95 PostgreSQL < 500 ms (currently 1 225 ms) |
| v2.2 | Parallel DAG p95 < 200 ms (currently 615 ms) |

These targets align with the CDC and Fluss/Iceberg analytics features in the
Q2–Q3 2026 roadmap which demand sub-500 ms end-to-end latency for streaming
pipelines.

---

## Related Documents

- [Benchmarking Guide](../guides/benchmarking.md) — how to run in-cluster benchmarks
- [ADR-012: Synchronous Orchestration Model](../architecture/adr/adr-012-synchronous-orchestration-model.md)
- [ADR-016: Unified Storage Layer](../architecture/adr/adr-016-unified-storage-layer.md)
