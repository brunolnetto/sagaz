"""Bronze layer: raw OLTP record normalisation with sqldim ``TransformPipeline``."""

from __future__ import annotations

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

    def process_executions(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalise step-execution Bronze records (lowercase outcome, cast types)."""
        return self._run(records, _EXECUTION_PIPELINE, _EXECUTION_SCHEMA, "_bronze_executions")

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

        # tmp_name and schema are module constants (never user input); record
        # values are bound through ``?`` placeholders below.
        cols_ddl = ", ".join(f'"{k}" {v}' for k, v in schema.items())
        self._conn.execute(f"CREATE OR REPLACE TEMP TABLE {tmp_name} ({cols_ddl})")  # nosec B608

        keys = list(schema.keys())
        placeholders = ", ".join("?" for _ in keys)
        self._conn.executemany(
            f"INSERT INTO {tmp_name} VALUES ({placeholders})",  # nosec B608
            [tuple(r.get(k) for k in keys) for r in records],
        )

        rel = self._conn.table(tmp_name)
        result_rel = nw.to_native(pipeline.apply(nw.from_native(rel, eager_only=False)))
        cols_out = result_rel.columns
        return [dict(zip(cols_out, row, strict=False)) for row in result_rel.fetchall()]
