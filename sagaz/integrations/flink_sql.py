"""Saga analytics in Flink SQL over the exported saga log (ADR-013, #483).

The reports read the table the Fluss exporter writes, ``saga_log_event``, and
nothing else: every transaction's status is in its lifecycle events.

- **Orchestrated sagas:** ``SagaStarted``, ``CompensationStarted``,
  ``SagaCompleted``, ``SagaRolledBack`` and ``SagaFailed``.
- **Choreographed transactions:** the tracker's ``TransactionStatusChanged``.

Run them in batch (``SET 'execution.runtime-mode' = 'batch'``) over the
Iceberg table, ``iceberg.sagaz.saga_log_event``. It is behind the log by the
table's freshness (``sagaz analytics export --freshness``). The ranking and
windows they use need batch mode; in streaming, Flink only supports Top-N
rankings and windows on a watermarked time attribute. :data:`FLOW_SUMMARY` has the semantics of the embedded pipeline's
``SagaQueries.FLOW_SUMMARY`` (ADR-043), so the two agree on the same log::

    sagaz analytics flink-sql flow-summary --table iceberg.sagaz.saga_log_event

Flink 1.20 has no ``PERCENTILE``: p50 and p95 interpolate linearly between the
ranked durations, as ``PERCENTILE_CONT`` does.
"""

from __future__ import annotations

_STATUS = """
    CASE
        WHEN `kind` <> 'lifecycle' THEN CAST(NULL AS STRING)
        WHEN `event_type` = 'SagaStarted' THEN 'executing'
        WHEN `event_type` = 'CompensationStarted' THEN 'compensating'
        WHEN `event_type` = 'SagaCompleted' THEN 'completed'
        WHEN `event_type` = 'SagaRolledBack' THEN 'compensated'
        WHEN `event_type` = 'SagaFailed' THEN 'failed'
        WHEN `event_type` = 'TransactionStatusChanged' THEN JSON_VALUE(`payload`, '$.status')
    END"""


def _percentile(p: float) -> str:
    """Linear interpolation over rows ranked ``rn`` of ``n`` (PERCENTILE_CONT)."""
    low = f"(CAST(FLOOR((n - 1) * {p}) AS BIGINT) + 1)"
    frac = f"((n - 1) * {p} - FLOOR((n - 1) * {p}))"
    at_low = f"MAX(CASE WHEN rn = {low} THEN duration_ms END)"
    at_next = f"MAX(CASE WHEN rn = {low} + 1 THEN duration_ms END)"
    return f"ROUND({at_low} + MAX({frac}) * (COALESCE({at_next}, {at_low}) - {at_low}), 2)"


FLOW_SUMMARY = f"""
WITH events AS (
    SELECT `tenant_id`, `transaction_id`, `coordination`, `flow`, `kind`, `sequence`,
           `occurred_at_ms`, {_STATUS.strip()} AS status
    FROM {{table}}
),
latest AS (  -- each transaction's last status
    SELECT `tenant_id`, `transaction_id`, status, `occurred_at_ms` AS status_ms
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY `tenant_id`, `transaction_id` ORDER BY `sequence` DESC) AS rn
        FROM events WHERE status IS NOT NULL
    ) WHERE rn = 1
),
transactions AS (
    SELECT `tenant_id`, `transaction_id`,
           MAX(`coordination`) AS coordination, MAX(`flow`) AS flow,
           MIN(`occurred_at_ms`) AS first_ms,
           MIN(CASE WHEN `kind` <> 'lifecycle' THEN `occurred_at_ms` END) AS first_event_ms,
           MAX(CASE WHEN `kind` <> 'lifecycle' THEN `occurred_at_ms` END) AS last_event_ms
    FROM events GROUP BY `tenant_id`, `transaction_id`
),
flows AS (
    SELECT t.coordination, t.flow, COALESCE(l.status, 'executing') AS status,
           CASE  -- the embedded pipeline's durations
               WHEN t.coordination = 'choreographed'
                    AND COALESCE(l.status, 'executing') IN ('completed', 'compensated', 'failed')
                   THEN CAST(t.last_event_ms - t.first_event_ms AS DOUBLE)
               WHEN t.coordination = 'orchestrated' AND l.status IN ('completed', 'compensated')
                   THEN CAST(l.status_ms - t.first_ms AS DOUBLE)
           END AS duration_ms
    FROM transactions t
    LEFT JOIN latest l ON l.`tenant_id` = t.`tenant_id` AND l.`transaction_id` = t.`transaction_id`
),
counts AS (
    SELECT coordination, flow,
           COUNT(*) AS transactions,
           COUNT(*) FILTER (WHERE status = 'completed') AS completed,
           COUNT(*) FILTER (WHERE status = 'compensated') AS compensated,
           COUNT(*) FILTER (WHERE status = 'failed') AS failed,
           COUNT(*) FILTER (WHERE status IN ('executing', 'compensating')) AS in_flight,
           ROUND(100.0 * COUNT(*) FILTER (WHERE status IN ('compensated', 'failed'))
               / NULLIF(COUNT(*) FILTER (
                   WHERE status IN ('completed', 'compensated', 'failed')), 0), 2)
               AS compensation_rate_pct
    FROM flows GROUP BY coordination, flow
),
ranked AS (
    SELECT coordination, flow, duration_ms,
           ROW_NUMBER() OVER (PARTITION BY coordination, flow ORDER BY duration_ms) AS rn,
           COUNT(*) OVER (PARTITION BY coordination, flow) AS n
    FROM flows WHERE duration_ms IS NOT NULL
),
percentiles AS (
    SELECT coordination, flow,
           {_percentile(0.5)} AS p50_duration_ms,
           {_percentile(0.95)} AS p95_duration_ms
    FROM ranked GROUP BY coordination, flow
)
SELECT c.coordination, c.flow, c.transactions, c.completed, c.compensated, c.failed,
       c.in_flight, c.compensation_rate_pct, p.p50_duration_ms, p.p95_duration_ms
FROM counts c
LEFT JOIN percentiles p ON p.coordination = c.coordination AND p.flow = c.flow
ORDER BY c.transactions DESC, c.coordination, c.flow
"""

THROUGHPUT = """
SELECT `coordination`, `flow`,
       window_start, window_end,
       COUNT(DISTINCT `transaction_id`) AS transactions,
       COUNT(*) AS events,
       COUNT(*) FILTER (WHERE `kind` = 'compensate') AS compensations_requested
FROM TABLE(TUMBLE(TABLE {table}, DESCRIPTOR(`occurred_at`), INTERVAL '1' MINUTE))
GROUP BY `coordination`, `flow`, window_start, window_end
"""

#: Report name -> Flink SQL with a ``{table}`` placeholder.
REPORTS: dict[str, str] = {
    "flow-summary": FLOW_SUMMARY,
    "throughput": THROUGHPUT,
}


def report(name: str, table: str = "iceberg.sagaz.saga_log_event") -> str:
    """The Flink SQL of report *name* over *table* (``catalog.database.table``)."""
    try:
        sql = REPORTS[name]
    except KeyError:
        msg = f"Unknown report {name!r}: one of {', '.join(sorted(REPORTS))}"
        raise ValueError(msg) from None
    return sql.replace("{table}", table).strip() + "\n"
