"""
Predefined Gold-layer DuckDB analytics queries for saga data.

All queries operate on DuckDB in-memory tables populated by
``SagaAnalyticsPipeline``:
  - ``dim_saga``       (from DimSaga records)
  - ``dim_step``       (from DimStep records)
  - ``fact_execution`` (from FactExecution records)

Usage::

    pipeline = SagaAnalyticsPipeline()
    pipeline.load_from_records(saga_records, step_records)
    summary = pipeline.query(SagaQueries.SAGA_SUMMARY)
"""

from __future__ import annotations


class SagaQueries:
    """Parameterised DuckDB SQL strings for Gold-layer analytics."""

    SAGA_SUMMARY = """
        SELECT
            ds.saga_name,
            COUNT(DISTINCT ds.saga_id)                                  AS total_sagas,
            COUNT(DISTINCT CASE WHEN ds.status = 'completed'
                                THEN ds.saga_id END)                    AS completed,
            COUNT(DISTINCT CASE WHEN ds.status = 'rolled_back'
                             OR  ds.status = 'compensating'
                                THEN ds.saga_id END)                    AS compensated,
            ROUND(
                100.0 * COUNT(DISTINCT CASE WHEN ds.status = 'rolled_back'
                                         OR ds.status = 'compensating'
                                            THEN ds.saga_id END)
                    / NULLIF(COUNT(DISTINCT ds.saga_id), 0), 2)        AS compensation_rate_pct,
            SUM(fe.duration_ms)                                         AS total_duration_ms,
            AVG(fe.duration_ms)                                         AS avg_step_duration_ms
        FROM dim_saga ds
        LEFT JOIN fact_execution fe ON ds.saga_id = fe.saga_id
        GROUP BY ds.saga_name
        ORDER BY total_sagas DESC
    """

    STEP_LATENCY = """
        SELECT
            dst.saga_name,
            dst.step_name,
            COUNT(*)                                                     AS executions,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP
                    (ORDER BY fe.duration_ms), 2)                       AS p50_ms,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP
                    (ORDER BY fe.duration_ms), 2)                       AS p95_ms,
            ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP
                    (ORDER BY fe.duration_ms), 2)                       AS p99_ms,
            ROUND(100.0 * SUM(CASE WHEN fe.outcome = 'failed'
                                   THEN 1 ELSE 0 END)
                        / COUNT(*), 2)                                   AS error_rate_pct
        FROM fact_execution fe
        JOIN dim_step dst ON fe.step_key = dst.step_key
        GROUP BY dst.saga_name, dst.step_name
        ORDER BY p99_ms DESC NULLS LAST
    """

    COMPENSATION_EVENTS = """
        SELECT
            dst.saga_name,
            dst.step_name,
            COUNT(*)       AS compensation_count,
            AVG(fe.duration_ms)  AS avg_compensation_ms
        FROM fact_execution fe
        JOIN dim_step dst ON fe.step_key = dst.step_key
        WHERE fe.outcome = 'compensated'
        GROUP BY dst.saga_name, dst.step_name
        ORDER BY compensation_count DESC
    """

    SAGA_LIFECYCLE_MILESTONES = """
        SELECT
            ds.saga_name,
            sl.saga_id,
            sl.created_at,
            sl.started_at,
            COALESCE(sl.completed_at, sl.rolled_back_at)               AS ended_at,
            ROUND(
                EXTRACT(EPOCH FROM (
                    COALESCE(sl.completed_at, sl.rolled_back_at) - sl.created_at
                )) * 1000, 2
            )                                                           AS lifecycle_ms,
            sl.total_duration_ms,
            sl.step_count,
            sl.compensation_count
        FROM fact_saga_lifecycle sl
        JOIN dim_saga ds ON sl.saga_id = ds.saga_id
        ORDER BY sl.created_at DESC NULLS LAST
    """
