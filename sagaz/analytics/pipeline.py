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
from dataclasses import dataclass, field
from typing import Any

try:
    import duckdb
except ImportError as exc:  # pragma: no cover
    msg = "DuckDB is required for sagaz analytics. Install with: pip install sagaz[analytics]"
    raise ImportError(msg) from exc

logger = logging.getLogger(__name__)


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

        # ---- Silver: dim_saga (upsert) ----
        for rec in saga_records:
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

        # ---- Silver: dim_step + fact_execution ----
        for idx, rec in enumerate(step_records):
            err = self._validate_step_record(rec)
            if err:
                stats.quality_errors.append(err)
                continue

            saga_name = rec.get("saga_name", "unknown")
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
                    int(rec.get("attempt", 1)),
                    float(rec.get("duration_ms", 0.0)),
                    rec["outcome"],
                    rec.get("executed_at"),
                ],
            )
            stats.facts_loaded += 1

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
