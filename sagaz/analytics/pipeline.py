"""
SagaAnalyticsPipeline — Bronze → Silver → Gold medallion promotion.

This class ingests raw saga records (Bronze), validates and normalises them
(Silver), then makes pre-aggregated Gold tables available for querying via
built-in DuckDB SQL.

It is intentionally **decoupled** from sagaz core: it is never imported
outside ``sagaz/analytics/`` and is only activated via the ``sagaz[analytics]``
optional extra.

Usage::

    from sagaz.analytics import SagaAnalyticsPipeline, SagaQueries

    pipeline = SagaAnalyticsPipeline()
    pipeline.load_from_records(saga_records, step_records)

    summary_rows = pipeline.query(SagaQueries.SAGA_SUMMARY)
    latency_rows = pipeline.query(SagaQueries.STEP_LATENCY)

    pipeline.close()

Or as a context manager::

    with SagaAnalyticsPipeline() as pipeline:
        pipeline.load_from_records(sagas, steps)
        rows = pipeline.query(SagaQueries.SAGA_SUMMARY)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

try:
    import duckdb
except ImportError as exc:  # pragma: no cover
    msg = "DuckDB is required for sagaz analytics. Install with: pip install sagaz[analytics]"
    raise ImportError(msg) from exc

try:
    import narwhals as nw
    from sqldim import TransformPipeline, col
except ImportError as exc:  # pragma: no cover
    msg = "sqldim and narwhals are required for sagaz analytics. Install with: pip install sagaz[analytics]"
    raise ImportError(msg) from exc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bronze transform pipelines
# ---------------------------------------------------------------------------

#: Normalises raw saga OLTP records before Silver upsert.
_SAGA_PIPELINE: TransformPipeline = TransformPipeline(
    transforms=[
        col("status").str.lowercase(),
        col("saga_name").fill_null("unknown"),
    ]
)

#: Normalises raw step-execution OLTP records before Silver insert.
_EXECUTION_PIPELINE: TransformPipeline = TransformPipeline(
    transforms=[
        col("outcome").str.lowercase(),
        col("saga_name").fill_null("unknown"),
        col("duration_ms").cast(float),
        col("attempt").cast(int),
    ]
)

# DuckDB DDL type maps for Bronze temp tables.
# duration_ms and attempt are ingested as VARCHAR so that string inputs from
# external serialisers (e.g. JSON) are accepted; the TransformPipeline casts
# them to the correct numeric types before Silver promotion.
_SAGA_SCHEMA: dict[str, str] = {
    "saga_id": "VARCHAR",
    "saga_name": "VARCHAR",
    "status": "VARCHAR",
    "created_at": "TIMESTAMP",
    "updated_at": "TIMESTAMP",
}

_EXECUTION_SCHEMA: dict[str, str] = {
    "saga_id": "VARCHAR",
    "saga_name": "VARCHAR",
    "step_name": "VARCHAR",
    "action": "VARCHAR",
    "outcome": "VARCHAR",
    "duration_ms": "VARCHAR",
    "attempt": "VARCHAR",
    "executed_at": "TIMESTAMP",
}


@dataclass
class PipelineStats:
    """Summary statistics produced after a pipeline run."""

    sagas_loaded: int = 0
    steps_loaded: int = 0
    facts_loaded: int = 0
    quality_errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.quality_errors) == 0


class SagaBronzeProcessor:
    """Bronze → Silver normalisation layer using sqldim ``TransformPipeline``.

    Uses the pipeline's DuckDB connection as the narwhals backend — no separate
    DataFrame library (polars / pandas) is required.

    Each ``process_*`` call:

    1. Inserts raw records into an ephemeral ``CREATE OR REPLACE TEMP TABLE``.
    2. Wraps the table as a narwhals ``LazyFrame`` (DuckDB relation backend).
    3. Runs the module-level ``TransformPipeline``; DuckDB executes the
       narwhals expressions natively (e.g. ``LOWER(status)``).
    4. Returns cleaned ``list[dict]``.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def process_sagas(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalise raw saga Bronze records (lowercase status, fill saga_name)."""
        return self._run(records, _SAGA_PIPELINE, _SAGA_SCHEMA, "_bronze_sagas")

    def process_executions(
        self, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Normalise step-execution Bronze records (lowercase outcome, cast types)."""
        return self._run(
            records, _EXECUTION_PIPELINE, _EXECUTION_SCHEMA, "_bronze_executions"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(
        self,
        records: list[dict[str, Any]],
        pipeline: TransformPipeline,
        schema: dict[str, str],
        tmp_name: str,
    ) -> list[dict[str, Any]]:
        if not records:
            return []

        cols_ddl = ", ".join(f'"{k}" {v}' for k, v in schema.items())
        self._conn.execute(
            f"CREATE OR REPLACE TEMP TABLE {tmp_name} ({cols_ddl})"
        )

        keys = list(schema.keys())
        placeholders = ", ".join("?" for _ in keys)
        self._conn.executemany(
            f"INSERT INTO {tmp_name} VALUES ({placeholders})",
            [tuple(r.get(k) for k in keys) for r in records],
        )

        rel = self._conn.table(tmp_name)
        result_rel = nw.to_native(
            pipeline.apply(nw.from_native(rel, eager_only=False))
        )
        cols_out = result_rel.columns
        return [dict(zip(cols_out, row)) for row in result_rel.fetchall()]


class SagaAnalyticsPipeline:
    """
    Bronze → Silver → Gold analytics pipeline backed by DuckDB.

    Parameters
    ----------
    duckdb_path:
        Path to a persistent DuckDB file.  Defaults to ``:memory:``.

    """

    def __init__(self, duckdb_path: str = ":memory:") -> None:
        self._conn = duckdb.connect(duckdb_path)
        self._bronze = SagaBronzeProcessor(self._conn)
        self._initialised = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> SagaAnalyticsPipeline:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        """Release the DuckDB connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        if self._initialised:
            return

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS dim_saga (
                saga_id    TEXT PRIMARY KEY,
                saga_name  TEXT NOT NULL,
                status     TEXT NOT NULL,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """)

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS dim_step (
                step_key   TEXT PRIMARY KEY,
                saga_name  TEXT NOT NULL,
                step_name  TEXT NOT NULL,
                action     TEXT
            )
        """)

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS fact_execution (
                id           INTEGER,
                saga_id      TEXT REFERENCES dim_saga(saga_id),
                step_key     TEXT REFERENCES dim_step(step_key),
                attempt      INTEGER DEFAULT 1,
                duration_ms  DOUBLE DEFAULT 0.0,
                outcome      TEXT NOT NULL,
                executed_at  TIMESTAMP
            )
        """)

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS fact_saga_lifecycle (
                saga_id            TEXT PRIMARY KEY REFERENCES dim_saga(saga_id),
                created_at         TIMESTAMP,
                started_at         TIMESTAMP,
                completed_at       TIMESTAMP,
                rolled_back_at     TIMESTAMP,
                total_duration_ms  DOUBLE DEFAULT 0.0,
                step_count         INTEGER DEFAULT 0,
                compensation_count INTEGER DEFAULT 0
            )
        """)

        self._initialised = True
        logger.debug("Analytics schema initialised")

    # ------------------------------------------------------------------
    # Bronze → Silver ingestion
    # ------------------------------------------------------------------

    def load_from_records(
        self,
        saga_records: list[dict[str, Any]],
        step_records: list[dict[str, Any]],
    ) -> PipelineStats:
        """
        Load raw OLTP records into Bronze and promote to Silver.

        Bronze normalisation is handled by :class:`SagaBronzeProcessor` via
        sqldim ``TransformPipeline`` expressions (DuckDB backend).  Silver
        validation then rejects any records that are still missing required
        fields after normalisation.

        Parameters
        ----------
        saga_records:
            List of dicts with keys: ``saga_id``, ``saga_name``, ``status``,
            optionally ``created_at``, ``updated_at``.
        step_records:
            List of dicts with keys: ``saga_id``, ``saga_name``, ``step_name``,
            ``outcome``, optionally ``action``, ``duration_ms``, ``attempt``,
            ``executed_at``.

        Returns
        -------
        PipelineStats
            Counts and quality-gate errors.
        """
        self._ensure_schema()
        stats = PipelineStats()

        # ---- Bronze → Silver: dim_saga (upsert) ----
        clean_sagas = self._bronze.process_sagas(saga_records)
        for rec in clean_sagas:
            err = self._validate_saga_record(rec)
            if err:
                stats.quality_errors.append(err)
                continue
            self._conn.execute(
                """
                INSERT OR REPLACE INTO dim_saga
                    (saga_id, saga_name, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    rec["saga_id"],
                    rec["saga_name"],
                    rec["status"],
                    rec.get("created_at"),
                    rec.get("updated_at"),
                ],
            )
            stats.sagas_loaded += 1

        # ---- Bronze → Silver: dim_step + fact_execution ----
        clean_steps = self._bronze.process_executions(step_records)
        for idx, rec in enumerate(clean_steps):
            err = self._validate_step_record(rec)
            if err:
                stats.quality_errors.append(err)
                continue

            saga_name = rec.get("saga_name") or "unknown"
            step_name = rec["step_name"]
            step_key = f"{saga_name}::{step_name}"

            # dim_step upsert
            self._conn.execute(
                """
                INSERT OR IGNORE INTO dim_step (step_key, saga_name, step_name, action)
                VALUES (?, ?, ?, ?)
                """,
                [step_key, saga_name, step_name, rec.get("action")],
            )
            stats.steps_loaded += 1

            # fact_execution insert
            self._conn.execute(
                """
                INSERT INTO fact_execution
                    (id, saga_id, step_key, attempt, duration_ms, outcome, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    idx,
                    rec["saga_id"],
                    step_key,
                    int(rec.get("attempt") or 1),
                    float(rec.get("duration_ms") or 0.0),
                    rec["outcome"],
                    rec.get("executed_at"),
                ],
            )
            stats.facts_loaded += 1

        # ---- Silver: fact_saga_lifecycle (accumulating snapshot) ----
        valid_sagas = [r for r in clean_sagas if not self._validate_saga_record(r)]
        valid_steps = [r for r in clean_steps if not self._validate_step_record(r)]
        for lifecycle_rec in self._build_lifecycle_records(valid_sagas, valid_steps):
            self._conn.execute(
                """
                INSERT OR REPLACE INTO fact_saga_lifecycle
                    (saga_id, created_at, started_at, completed_at,
                     rolled_back_at, total_duration_ms, step_count, compensation_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    lifecycle_rec["saga_id"],
                    lifecycle_rec["created_at"],
                    lifecycle_rec["started_at"],
                    lifecycle_rec["completed_at"],
                    lifecycle_rec["rolled_back_at"],
                    lifecycle_rec["total_duration_ms"],
                    lifecycle_rec["step_count"],
                    lifecycle_rec["compensation_count"],
                ],
            )

        logger.info(
            "Pipeline load: sagas=%d steps=%d facts=%d errors=%d",
            stats.sagas_loaded,
            stats.steps_loaded,
            stats.facts_loaded,
            len(stats.quality_errors),
        )
        return stats

    # ------------------------------------------------------------------
    # Gold: query
    # ------------------------------------------------------------------

    def query(self, sql: str) -> list[dict[str, Any]]:
        """
        Execute a Gold-layer DuckDB query and return rows as dicts.

        Parameters
        ----------
        sql:
            A SQL string (typically from ``SagaQueries``).

        Returns
        -------
        list[dict]
            Each dict maps column name → value.
        """
        self._ensure_schema()
        rel = self._conn.execute(sql)
        columns = [desc[0] for desc in rel.description]
        return [dict(zip(columns, row, strict=False)) for row in rel.fetchall()]

    # ------------------------------------------------------------------
    # Quality gates (Silver validation)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_saga_record(rec: dict[str, Any]) -> str | None:
        for key in ("saga_id", "saga_name", "status"):
            if not rec.get(key):
                return f"Saga record missing required field '{key}': {rec!r}"
        return None

    @staticmethod
    def _validate_step_record(rec: dict[str, Any]) -> str | None:
        for key in ("saga_id", "step_name", "outcome"):
            if not rec.get(key):
                return f"Step record missing required field '{key}': {rec!r}"
        duration = rec.get("duration_ms", 0)
        if isinstance(duration, (int, float)) and duration < 0:
            return f"Step record has negative duration_ms={duration}: {rec!r}"
        return None

    # ------------------------------------------------------------------
    # Lifecycle accumulation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_lifecycle_records(
        saga_records: list[dict[str, Any]],
        step_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Aggregate step events into ``FactSagaLifecycle`` accumulating snapshots.

        Each record represents one saga with milestone timestamps and
        aggregated metrics derived from its step executions.
        """
        saga_index = {r["saga_id"]: r for r in saga_records}
        step_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rec in step_records:
            step_groups[rec["saga_id"]].append(rec)

        lifecycle = []
        for saga_id, saga in saga_index.items():
            steps = step_groups.get(saga_id, [])
            exec_times = [s["executed_at"] for s in steps if s.get("executed_at")]

            status = saga.get("status", "")
            completed_at = saga.get("updated_at") if status == "completed" else None
            rolled_back_at = (
                saga.get("updated_at")
                if status in ("rolled_back", "compensating")
                else None
            )

            lifecycle.append(
                {
                    "saga_id": saga_id,
                    "created_at": saga.get("created_at"),
                    "started_at": min(exec_times) if exec_times else None,
                    "completed_at": completed_at,
                    "rolled_back_at": rolled_back_at,
                    "total_duration_ms": sum(
                        float(s.get("duration_ms") or 0) for s in steps
                    ),
                    "step_count": len(steps),
                    "compensation_count": sum(
                        1 for s in steps if s.get("outcome") == "compensated"
                    ),
                }
            )
        return lifecycle

