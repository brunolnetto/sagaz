"""
SagaAnalyticsPipeline — Bronze → Silver → Gold medallion promotion.

This class ingests raw saga records (Bronze), validates and normalises them
(Silver), then makes pre-aggregated Gold tables available for querying via
built-in DuckDB SQL.

It is intentionally **decoupled** from sagaz core: it is never imported
outside ``sagaz/analytics/`` and is only activated via the ``sagaz[analytics]``
optional extra.

Usage — straight from saga storage (the OLTP side is read-only)::

    pipeline = SagaAnalyticsPipeline(storage)      # saga storage or StorageManager
    stats = await pipeline.run()                   # Bronze → Silver → Gold
    latency_rows = pipeline.query(SagaQueries.STEP_LATENCY)

Or from records you already have::

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
from typing import Any

try:
    import duckdb
except ImportError as exc:  # pragma: no cover
    msg = "DuckDB is required for sagaz analytics. Install with: pip install sagaz[analytics]"
    raise ImportError(msg) from exc

from sagaz.analytics._bronze import SagaBronzeProcessor
from sagaz.analytics._quality import SAGA_STATUSES, STEP_OUTCOMES, PipelineStats
from sagaz.analytics._silver import _SilverLoaderMixin
from sagaz.analytics.sources import bronze_records_from_storage

__all__ = [
    "SAGA_STATUSES",
    "STEP_OUTCOMES",
    "PipelineStats",
    "SagaAnalyticsPipeline",
    "SagaBronzeProcessor",
]

logger = logging.getLogger(__name__)


class SagaAnalyticsPipeline(_SilverLoaderMixin):
    """
    Bronze → Silver → Gold analytics pipeline backed by DuckDB.

    Parameters
    ----------
    duckdb_path:
        Path to a persistent DuckDB file.  Defaults to ``:memory:``.

    """

    def __init__(self, storage: Any | None = None, *, duckdb_path: str = ":memory:") -> None:
        self._storage = storage
        self._conn = duckdb.connect(duckdb_path)
        self._bronze = SagaBronzeProcessor(self._conn)
        self._initialised = False
        self._next_fact_id = 0

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

        clean_sagas = self._bronze.process_sagas(saga_records)
        clean_steps = self._bronze.process_executions(step_records)

        self._load_saga_records(stats, clean_sagas)
        self._load_step_records(stats, clean_steps)
        self._load_lifecycle_records(clean_sagas, clean_steps)

        logger.info(
            "Pipeline load: sagas=%d steps=%d facts=%d errors=%d",
            stats.sagas_loaded,
            stats.steps_loaded,
            stats.facts_loaded,
            len(stats.quality_errors),
        )
        return stats

    # ------------------------------------------------------------------
    # Storage → Gold
    # ------------------------------------------------------------------

    async def run(self) -> PipelineStats:
        """Rebuild Silver and Gold from the saga storage given to the constructor.

        Reads every saga (with its steps) from ``storage.export_all()`` — the
        OLTP side is never written — and replaces previously loaded data, so
        calling ``run()`` again refreshes the analytics with the latest state.
        """
        if self._storage is None:
            msg = "run() needs a saga storage: SagaAnalyticsPipeline(storage)"
            raise ValueError(msg)
        sagas, steps = await bronze_records_from_storage(self._storage)
        self._reset()
        return self.load_from_records(sagas, steps)

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
