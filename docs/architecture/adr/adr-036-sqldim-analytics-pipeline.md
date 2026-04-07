# ADR-036: sqldim-Powered Analytics Pipeline for Saga OLTP & Visualization

## Status

**In Progress** | Date: 2026-04-07 | Priority: Medium | Target: v2.2.0

**Implementation Status:**
- ⚪ Phase 1: Saga Star Schema (Not Started)
- ⚪ Phase 2: sqldim DGM Query Layer (Not Started)
- ⚪ Phase 3: Medallion Promotion + Quality Gates (Not Started)
- ⚪ Phase 4: Visualization UI integration (Not Started)

## Dependencies

**Prerequisites**:
- ADR-016: Unified Storage Layer (provides PostgreSQL saga tables as the Bronze source)
- ADR-046 (SQLite backend, #46): Unlocks local/embedded analytic sink

**Synergies** (optional, not required):
- ADR-035: Visualization UI (ADR-036 provides the query layer the UI reads)
- ADR-033: Event Sourcing (event log becomes an enriched fact table)
- ADR-011: CDC Support (DebeziumSource reuses sqldim's existing `DebeziumSource`)

**External library**: `sqldim >= 0.1.1` (PyPI) — star schemas, DGM query algebra, medallion layers, data contracts.

**Roadmap**: **Phase 4 (2026 Q2–Q3, v2.2.0)**

## Context

Sagaz stores saga execution state in PostgreSQL (or SQLite). Currently this data is only accessible via direct SQL or storage backends. Two gaps exist:

1. **No analytics layer**: answering questions like "what percentage of sagas compensate?", "which step has the highest p99 latency?", "which user cohort triggers the most rollbacks?" requires custom SQL against the raw OLTP tables — brittle, non-reusable, and hard to expose in a dashboard.

2. **Visualization UI (#58, ADR-035) needs a query backend**: a static Mermaid graph already exists; a live dashboard needs aggregated, contract-governed, time-series-ready data.

`sqldim` reaches maturity (`0.1.1`, on PyPI) with all the pieces needed:
- `DimensionModel` / `FactModel` for defining a saga star schema once
- `DGMQuery` / `QuestionAlgebra` for composing min-CTE analytics queries
- `MedallionRegistry` + `QualityGate` for Bronze→Silver→Gold promotion
- `DebeziumSource` for CDC integration (re-uses ADR-011 path)
- `PostgreSQLSource` / `DuckDBSink` for OLTP → in-process analytics

## Decision

Introduce an **opt-in** `sagaz[analytics]` extra that wires `sqldim` to the saga OLTP database.
The integration is **decoupled**: sagaz's core never imports sqldim; the pipeline lives in `sagaz/analytics/`.

### Star Schema (Bronze → Silver → Gold)

```
BRONZE (raw OLTP read-replica or snapshot)
  saga_runs_raw         ← dim: saga_id, saga_type, status, created_at
  saga_steps_raw        ← fact: step_name, action, duration_ms, attempt, outcome
  saga_compensations_raw← fact: step_name, compensation_result, duration_ms

SILVER (typed, keyed, validated)
  dim_saga (SCD1)       ← unique saga lifecycles with surrogate key
  dim_step (SCD1)       ← unique step definitions per saga type
  fact_execution        ← step-grain execution events (duration, status, attempt)
  fact_compensation     ← compensation events (paired to fact_execution via lag join)

GOLD (business metrics)  ← derived via DGMQuery / QuestionAlgebra
  agg_saga_summary      ← per-saga: total_steps, compensated_steps, wall_ms
  agg_step_latency      ← per-step: p50/p95/p99 duration, error_rate
  agg_cohort_rollback   ← per-user cohort: rollback rate (optional, requires user dim)
```

### Query Layer

All Gold aggregations are emitted as parameterised `DGMQuery` objects, composed with `QuestionAlgebra`. This means:
- Minimised CTE chains (semiring optimisation)
- Zero ORM overhead — pure DuckDB
- Queries are Python objects that can be serialised and fed to the UI backend (ADR-035)

### Visualization tie-in (ADR-035)

The FastAPI service defined in ADR-035 will expose:
```
GET /api/v1/analytics/saga-summary        ← agg_saga_summary
GET /api/v1/analytics/step-latency        ← agg_step_latency
GET /api/v1/analytics/live                ← SSE feed from Bronze writes
```

The `SagaAnalyticsPipeline` class drives the full Bronze→Gold promotion on-demand (pull) or on a configurable interval (push). The Visualization dashboard reads exclusively from the Gold layer.

### CDC path (when ADR-011 is available)

When `sagaz[analytics,cdc]` is installed, the Bronze layer can be populated via `DebeziumSource` (sqldim's existing CDC consumer) instead of periodic snapshots, giving sub-second latency for the live dashboard.

## Coupling Firewall

| Rule | Detail |
|------|--------|
| `sqldim` is never imported in `sagaz/core/` or `sagaz/sagaz/` | guarded by `TYPE_CHECKING` + lazy import in `sagaz/analytics/` |
| No sagaz ABCs inherit from sqldim classes | sqldim models are independent from `SagaStorage` |
| `sagaz[analytics]` extra is optional in `pyproject.toml` | core installs work without DuckDB/sqldim |
| No schema coupling | Bronze reads from existing OLTP columns; schema changes don't break analytics (additive only) |

## Consequences

**Positive:**
- Rich analytics without new infrastructure (DuckDB runs in-process)
- Data quality gates catch stale or malformed saga data before promotion
- Visualization UI gets a clean, queryable Gold layer — no raw SQL in the UI layer
- CDC path reuses sqldim's `DebeziumSource` — ADR-011 implementation cost drops
- `QuestionAlgebra` queries can be exported as test fixtures (deterministic SQL aids CI)

**Negative / Risks:**
- Extra dependency (`sqldim`, `duckdb`) increases install footprint (~30 MB)
- Medallion promotion adds latency between OLTP write and dashboard visibility (mitigated by CDC path)
- sqldim API stability: pinned to `sqldim >= 0.1.1, < 0.2` in `pyproject.toml`

## Implementation Phases

### Phase 1: Bronze read layer (approx. 2 days)

- `sagaz/analytics/__init__.py`
- `sagaz/analytics/schema.py` — `DimSaga`, `DimStep`, `FactExecution`, `FactCompensation` as `sqldim.DimensionModel` / `FactModel`
- `sagaz/analytics/sources.py` — `PostgreSQLSource` adapter reading from `sagaz` OLTP tables
- Unit tests with DuckDB in-memory + fixed saga fixture data

### Phase 2: Silver/Gold promotion (approx. 2 days)

- `sagaz/analytics/pipeline.py` — `SagaAnalyticsPipeline(storage, sink)` class
- `MedallionRegistry` registration + `QualityGate` contracts (null checks, duration > 0, status enum)
- `DGMQuery` definitions for `agg_saga_summary`, `agg_step_latency`
- Integration tests: run pipeline against testcontainer PostgreSQL, verify Gold row counts

### Phase 3: API integration with ADR-035 Visualization UI (approx. 1 day)

- `sagaz/visualization/api.py` — extend with `/api/v1/analytics/*` endpoints reading from Gold DuckDB
- SSE endpoint reads from Bronze write stream (polling interval configurable, default 5 s)
- `sagaz[monitor,analytics]` combined extra in `pyproject.toml`

### Phase 4: CDC fast path (optional, depends on ADR-011)

- Swap `PostgreSQLSource` for `sqldim.DebeziumSource` when CDC is enabled
- Bronze promotion becomes event-driven instead of scheduled

## Scope Notes

- **OLTP database is read-only**: sqldim never writes to the saga PostgreSQL database
- **DuckDB is ephemeral by default**: Gold layer lives in `:memory:` unless user sets `analytics.duckdb_path` in config
- **Embedded by default**: no Fluss, no Iceberg, no Kafka required for basic analytics. Those are opt-in via `sagaz[analytics,cdc]`
