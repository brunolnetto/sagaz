-- Sagaz: Fluss → Iceberg tiering job (Apache Flink SQL)
--
-- This job continuously reads from the real-time Fluss table
-- (sagaz.saga_events) and merges records into the long-term
-- Iceberg table (sagaz.saga_history) using upsert semantics.
--
-- Run with:
--   flink run -py jobs/fluss_to_iceberg.py
-- Or via Flink SQL CLI:
--   sql-client.sh -f jobs/fluss_to_iceberg.sql

-- -----------------------------------------------------------------------
-- 1. Fluss source catalog
-- -----------------------------------------------------------------------
CREATE CATALOG fluss_catalog WITH (
  'type'                          = 'fluss',
  'bootstrap.servers'             = '${FLUSS_BOOTSTRAP_SERVERS:localhost:9092}'
);

USE CATALOG fluss_catalog;

-- (Table must already exist in Fluss)
-- Schema: saga_id STRING, event_type STRING, duration_ms DOUBLE,
--         status STRING, step_name STRING, ts TIMESTAMP

-- -----------------------------------------------------------------------
-- 2. Iceberg sink catalog
-- -----------------------------------------------------------------------
CREATE CATALOG iceberg_catalog WITH (
  'type'                          = 'iceberg',
  'catalog-impl'                  = 'org.apache.iceberg.rest.RESTCatalog',
  'uri'                           = '${ICEBERG_CATALOG_URL:http://rest-catalog:8181}',
  'warehouse'                     = '${ICEBERG_WAREHOUSE:s3://sagaz-warehouse}'
);

-- -----------------------------------------------------------------------
-- 3. Create Iceberg destination table (idempotent)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iceberg_catalog.sagaz.saga_history (
  saga_id     STRING,
  saga_name   STRING,
  status      STRING,
  started_at  STRING,
  completed_at STRING,
  duration_ms  DOUBLE,
  step_count   INT,
  PRIMARY KEY (saga_id) NOT ENFORCED
) PARTITIONED BY (status)
WITH (
  'write.format.default' = 'parquet',
  'write.upsert.enabled'  = 'true'
);

-- -----------------------------------------------------------------------
-- 4. Continuous insert from Fluss → Iceberg
-- -----------------------------------------------------------------------
INSERT INTO iceberg_catalog.sagaz.saga_history
SELECT
  e.saga_id,
  ''                         AS saga_name,   -- enriched downstream
  e.status,
  MIN(e.ts)                  AS started_at,
  MAX(CASE WHEN e.event_type IN ('saga_completed','saga_failed','saga_rolled_back')
            THEN e.ts END)   AS completed_at,
  SUM(e.duration_ms)         AS duration_ms,
  COUNT(CASE WHEN e.event_type = 'step_executed' THEN 1 END) AS step_count
FROM fluss_catalog.sagaz.saga_events AS e
GROUP BY e.saga_id, e.status;
