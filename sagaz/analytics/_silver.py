"""Silver layer: DuckDB star-schema DDL and validated record loaders."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sagaz.analytics._lifecycle import (
    build_lifecycle_records,
    build_single_lifecycle_record,
)
from sagaz.analytics._quality import (
    PipelineStats,
    validate_saga_record,
    validate_step_record,
)

if TYPE_CHECKING:
    import duckdb

# Log under the public pipeline module name, as before the split.
logger = logging.getLogger("sagaz.analytics.pipeline")


class _SilverLoaderMixin:
    """Schema initialisation and Silver loaders for :class:`SagaAnalyticsPipeline`."""

    _conn: duckdb.DuckDBPyConnection
    _initialised: bool
    _next_fact_id: int

    _validate_saga_record = staticmethod(validate_saga_record)
    _validate_step_record = staticmethod(validate_step_record)
    _build_lifecycle_records = staticmethod(build_lifecycle_records)
    _build_single_lifecycle_record = staticmethod(build_single_lifecycle_record)

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
                duration_ms  DOUBLE,
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

    def _load_saga_records(
        self,
        stats: PipelineStats,
        clean_sagas: list[dict[str, Any]],
    ) -> None:
        """Insert validated saga records into ``dim_saga``."""
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

    def _load_step_records(
        self,
        stats: PipelineStats,
        clean_steps: list[dict[str, Any]],
    ) -> None:
        """Insert validated step records into ``dim_step`` and ``fact_execution``."""
        for rec in clean_steps:
            err = self._validate_step_record(rec)
            if err:
                stats.quality_errors.append(err)
                continue
            saga_name = rec.get("saga_name") or "unknown"
            step_name = rec["step_name"]
            step_key = f"{saga_name}::{step_name}"
            self._conn.execute(
                """
                INSERT OR IGNORE INTO dim_step (step_key, saga_name, step_name, action)
                VALUES (?, ?, ?, ?)
                """,
                [step_key, saga_name, step_name, rec.get("action")],
            )
            stats.steps_loaded += 1
            self._conn.execute(
                """
                INSERT INTO fact_execution
                    (id, saga_id, step_key, attempt, duration_ms, outcome, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    self._next_fact_id,
                    rec["saga_id"],
                    step_key,
                    int(rec.get("attempt") or 1),
                    # Unknown duration stays NULL so it cannot drag percentiles to 0.
                    None if rec.get("duration_ms") is None else float(rec["duration_ms"]),
                    rec["outcome"],
                    rec.get("executed_at"),
                ],
            )
            self._next_fact_id += 1
            stats.facts_loaded += 1

    def _load_lifecycle_records(
        self,
        clean_sagas: list[dict[str, Any]],
        clean_steps: list[dict[str, Any]],
    ) -> None:
        """Build and insert ``fact_saga_lifecycle`` accumulating snapshots."""
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

    def _reset(self) -> None:
        """Drop previously loaded Silver rows (children before parents)."""
        self._ensure_schema()
        for table in ("fact_execution", "fact_saga_lifecycle", "dim_step", "dim_saga"):
            self._conn.execute(f"DELETE FROM {table}")  # nosec B608 - fixed table names
        self._next_fact_id = 0
