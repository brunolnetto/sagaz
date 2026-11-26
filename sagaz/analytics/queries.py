"""
Predefined Gold-layer DuckDB analytics queries for saga data.

All queries operate on DuckDB in-memory tables populated by
``SagaAnalyticsPipeline``:
  - ``dim_saga``       (from DimSaga records)
  - ``dim_step``       (from DimStep records)
  - ``fact_execution`` (from FactExecution records)
  - ``fact_choreography_transaction``, ``fact_choreography_event`` and
    ``fact_choreography_compensation`` (choreographed sagas, #459)

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

    # ------------------------------------------------------------------
    # Choreographed sagas (#459): from the choreography fact tables
    # ------------------------------------------------------------------

    CHOREOGRAPHY_SUMMARY = """
        SELECT
            flow,
            COUNT(*)                                                    AS transactions,
            COUNT(*) FILTER (WHERE status = 'completed')                AS completed,
            COUNT(*) FILTER (WHERE status = 'rolled_back')              AS rolled_back,
            COUNT(*) FILTER (WHERE status = 'rolled_back')              AS compensated,  -- old name, until 3.0
            COUNT(*) FILTER (WHERE status = 'failed')                   AS failed,
            COUNT(*) FILTER (WHERE status IN ('executing', 'compensating')) AS in_flight,
            ROUND(100.0 * COUNT(*) FILTER (WHERE status IN ('rolled_back', 'failed'))
                / NULLIF(COUNT(*) FILTER (WHERE status IN ('completed', 'rolled_back', 'failed')), 0),
                2)                                                      AS compensation_rate_pct,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms), 2) AS p50_duration_ms,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms), 2) AS p95_duration_ms,
            ROUND(AVG(participant_count), 2)                            AS avg_participants
        FROM fact_choreography_transaction
        GROUP BY flow
        ORDER BY transactions DESC, flow
    """

    CHOREOGRAPHY_PARTICIPANTS = """
        WITH emitted AS (
            SELECT participant,
                   COUNT(*)                                             AS events_emitted,
                   COUNT(DISTINCT tenant_id || '/' || correlation_id)   AS transactions
            FROM fact_choreography_event
            WHERE kind = 'business' AND participant IS NOT NULL
            GROUP BY participant
        ),
        caused AS (
            SELECT failed_participant AS participant, COUNT(*) AS failures_caused
            FROM fact_choreography_transaction
            WHERE failed_participant IS NOT NULL
            GROUP BY failed_participant
        ),
        undid AS (
            SELECT participant,
                   SUM(undone) AS actions_undone,
                   SUM(failed) AS compensation_failures
            FROM fact_choreography_compensation
            GROUP BY participant
        )
        SELECT
            participant,
            COALESCE(events_emitted, 0)          AS events_emitted,
            COALESCE(transactions, 0)            AS transactions,
            COALESCE(failures_caused, 0)         AS failures_caused,
            COALESCE(actions_undone, 0)          AS actions_undone,
            COALESCE(compensation_failures, 0)   AS compensation_failures
        FROM emitted
        FULL OUTER JOIN caused USING (participant)
        FULL OUTER JOIN undid USING (participant)
        ORDER BY failures_caused DESC, compensation_failures DESC, participant
    """

    CHOREOGRAPHY_HOP_LATENCY = """
        SELECT
            participant,
            event_type,
            COUNT(*)                                                    AS hops,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY hop_ms), 2) AS p50_ms,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY hop_ms), 2) AS p95_ms,
            ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY hop_ms), 2) AS p99_ms
        FROM fact_choreography_event
        WHERE kind = 'business' AND hop_ms IS NOT NULL
        GROUP BY participant, event_type
        ORDER BY p99_ms DESC NULLS LAST, participant, event_type
    """

    CHOREOGRAPHY_FAILURES = """
        SELECT
            flow,
            failed_participant                              AS participant,
            failed_event_type,
            failure_reason                                  AS reason,
            COUNT(*)                                        AS transactions,
            COUNT(*) FILTER (WHERE status = 'failed')       AS left_inconsistent
        FROM fact_choreography_transaction
        WHERE failed_participant IS NOT NULL
        GROUP BY flow, failed_participant, failed_event_type, failure_reason
        ORDER BY transactions DESC, flow, participant
    """

    # ------------------------------------------------------------------
    # Both coordination styles (ADR-041 phase 4, #467)
    # ------------------------------------------------------------------

    FLOW_SUMMARY = """
        WITH flows AS (
            SELECT 'orchestrated'                                       AS coordination,
                   ds.saga_name                                         AS flow,
                   ds.status                                            AS status,
                   EXTRACT(EPOCH FROM (
                       COALESCE(sl.completed_at, sl.rolled_back_at) - ds.created_at
                   )) * 1000                                            AS duration_ms
            FROM dim_saga ds
            LEFT JOIN fact_saga_lifecycle sl ON sl.saga_id = ds.saga_id
            UNION ALL
            SELECT 'choreographed', flow, status, duration_ms
            FROM fact_choreography_transaction
        )
        SELECT
            coordination,
            flow,
            COUNT(*)                                                    AS transactions,
            COUNT(*) FILTER (WHERE status = 'completed')                AS completed,
            COUNT(*) FILTER (WHERE status = 'rolled_back')              AS rolled_back,
            COUNT(*) FILTER (WHERE status = 'rolled_back')              AS compensated,  -- old name, until 3.0
            COUNT(*) FILTER (WHERE status = 'failed')                   AS failed,
            COUNT(*) FILTER (WHERE status IN ('executing', 'compensating')) AS in_flight,
            ROUND(100.0 * COUNT(*) FILTER (WHERE status IN ('rolled_back', 'failed'))
                / NULLIF(COUNT(*) FILTER (WHERE status IN ('completed', 'rolled_back', 'failed')), 0),
                2)                                                      AS compensation_rate_pct,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms), 2) AS p50_duration_ms,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms), 2) AS p95_duration_ms
        FROM flows
        GROUP BY coordination, flow
        ORDER BY transactions DESC, coordination, flow
    """
