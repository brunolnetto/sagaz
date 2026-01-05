-- ============================================================================
-- Migration: Create Initial Partitions
-- Description: Create initial set of partitions for immediate use
-- Version: 1.1.0
-- ============================================================================

BEGIN;

\echo 'Creating initial partitions...'
\echo ''

-- ============================================================================
-- Run Maintenance Function to Create Initial Partitions
-- ============================================================================

-- This will create:
-- - saga_executions: current month + 3 future months
-- - saga_outbox: current day + 7 future days
-- - saga_audit_log: current month + 3 future months

SELECT 
    action,
    table_name,
    partition_name,
    details
FROM maintain_all_partitions();

\echo ''
\echo '✅ Initial partitions created successfully!'
\echo ''

-- ============================================================================
-- Display Partition Statistics
-- ============================================================================

\echo 'Current partition statistics:'
\echo ''

SELECT 
    table_name as "Table",
    partition_count as "Partitions",
    oldest_partition as "Oldest",
    newest_partition as "Newest",
    total_size_mb as "Size (MB)"
FROM get_partition_statistics();

\echo ''

-- ============================================================================
-- List All Created Partitions
-- ============================================================================

\echo 'All partitions:'
\echo ''

SELECT 
    table_name as "Table",
    partition_name as "Partition Name",
    TO_CHAR(partition_start, 'YYYY-MM-DD') as "Start Date",
    TO_CHAR(partition_end, 'YYYY-MM-DD') as "End Date",
    TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as "Created At"
FROM partition_metadata
ORDER BY table_name, partition_start;

\echo ''

COMMIT;

-- ============================================================================
-- Setup Automated Maintenance (Optional - for production)
-- ============================================================================

-- Uncomment the following to set up pg_cron for automated maintenance
-- Requires pg_cron extension (available in managed PostgreSQL services)

/*
-- Enable pg_cron extension
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Schedule daily partition maintenance at 2 AM
SELECT cron.schedule(
    'sagaz-partition-maintenance',
    '0 2 * * *',  -- Every day at 2 AM
    $$SELECT maintain_all_partitions();$$
);

-- Schedule weekly consumer inbox cleanup (Sunday at 3 AM)
SELECT cron.schedule(
    'sagaz-inbox-cleanup',
    '0 3 * * 0',  -- Every Sunday at 3 AM
    $$SELECT cleanup_consumer_inbox(90);$$  -- Keep 90 days
);
*/

-- ============================================================================
-- Verification & Next Steps
-- ============================================================================

\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '✅ PARTITIONING SETUP COMPLETE!'
\echo ''
\echo 'Summary:'
\echo '  ✓ Partitioned tables created'
\echo '  ✓ Maintenance functions installed'
\echo '  ✓ Initial partitions created'
\echo ''
\echo 'Next Steps:'
\echo '  1. Test partition insertion:'
\echo '     INSERT INTO saga_executions (saga_name, status)'
\echo '     VALUES (''test-saga'', ''SUCCESS'');'
\echo ''
\echo '  2. Verify partition is used:'
\echo '     EXPLAIN SELECT * FROM saga_executions WHERE created_at >= CURRENT_DATE;'
\echo ''
\echo '  3. Monitor partitions:'
\echo '     SELECT * FROM get_partition_statistics();'
\echo ''
\echo '  4. Manual maintenance (if needed):'
\echo '     SELECT * FROM maintain_all_partitions();'
\echo ''
\echo '  5. Connection Strings:'
\echo '     OLTP (writes): postgresql://postgres:postgres@pgbouncer-rw:6432/sagaz'
\echo '     OLAP (reads):  postgresql://postgres:postgres@pgbouncer-ro:6433/sagaz'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo ''
