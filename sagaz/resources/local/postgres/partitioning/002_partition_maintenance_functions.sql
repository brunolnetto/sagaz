-- ============================================================================
-- Migration: Partition Maintenance Functions
-- Description: Automated partition creation and cleanup functions
-- Version: 1.1.0
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. Function: Create Saga Executions Partition (Monthly)
-- ============================================================================

CREATE OR REPLACE FUNCTION create_saga_executions_partition(
    partition_date DATE
) RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    -- Calculate partition boundaries (first day of month to first day of next month)
    start_date := DATE_TRUNC('month', partition_date)::DATE;
    end_date := (DATE_TRUNC('month', partition_date) + INTERVAL '1 month')::DATE;
    
    -- Generate partition name: saga_executions_y2025m01
    partition_name := 'saga_executions_y' || TO_CHAR(start_date, 'YYYY') || 'm' || TO_CHAR(start_date, 'MM');
    
    -- Create partition if it doesn't exist
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF saga_executions 
         FOR VALUES FROM (%L) TO (%L)',
        partition_name,
        start_date,
        end_date
    );
    
    -- Record in metadata
    INSERT INTO partition_metadata (table_name, partition_name, partition_start, partition_end)
    VALUES ('saga_executions', partition_name, start_date, end_date)
    ON CONFLICT (table_name, partition_name) DO NOTHING;
    
    RETURN partition_name;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_saga_executions_partition IS 
    'Creates a monthly partition for saga_executions table';

-- ============================================================================
-- 2. Function: Create Saga Outbox Partition (Daily)
-- ============================================================================

CREATE OR REPLACE FUNCTION create_saga_outbox_partition(
    partition_date DATE
) RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    -- Calculate partition boundaries (single day)
    start_date := partition_date::DATE;
    end_date := (partition_date + INTERVAL '1 day')::DATE;
    
    -- Generate partition name: saga_outbox_y2025m01d15
    partition_name := 'saga_outbox_y' || TO_CHAR(start_date, 'YYYY') || 
                      'm' || TO_CHAR(start_date, 'MM') || 
                      'd' || TO_CHAR(start_date, 'DD');
    
    -- Create partition if it doesn't exist
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF saga_outbox 
         FOR VALUES FROM (%L) TO (%L)',
        partition_name,
        start_date,
        end_date
    );
    
    -- Record in metadata
    INSERT INTO partition_metadata (table_name, partition_name, partition_start, partition_end)
    VALUES ('saga_outbox', partition_name, start_date, end_date)
    ON CONFLICT (table_name, partition_name) DO NOTHING;
    
    RETURN partition_name;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_saga_outbox_partition IS 
    'Creates a daily partition for saga_outbox table';

-- ============================================================================
-- 3. Function: Create Saga Audit Log Partition (Monthly)
-- ============================================================================

CREATE OR REPLACE FUNCTION create_saga_audit_log_partition(
    partition_date DATE
) RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    start_date := DATE_TRUNC('month', partition_date)::DATE;
    end_date := (DATE_TRUNC('month', partition_date) + INTERVAL '1 month')::DATE;
    
    partition_name := 'saga_audit_log_y' || TO_CHAR(start_date, 'YYYY') || 'm' || TO_CHAR(start_date, 'MM');
    
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF saga_audit_log 
         FOR VALUES FROM (%L) TO (%L)',
        partition_name,
        start_date,
        end_date
    );
    
    INSERT INTO partition_metadata (table_name, partition_name, partition_start, partition_end)
    VALUES ('saga_audit_log', partition_name, start_date, end_date)
    ON CONFLICT (table_name, partition_name) DO NOTHING;
    
    RETURN partition_name;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_saga_audit_log_partition IS 
    'Creates a monthly partition for saga_audit_log table';

-- ============================================================================
-- 4. Function: Maintain All Partitions (Daily Cron Job)
-- ============================================================================

CREATE OR REPLACE FUNCTION maintain_all_partitions() 
RETURNS TABLE (
    action TEXT,
    table_name TEXT,
    partition_name TEXT,
    details TEXT
) AS $$
DECLARE
    current_date DATE := CURRENT_DATE;
    future_months INT := 3;  -- Create 3 months ahead
    future_days INT := 7;    -- Create 7 days ahead for daily partitions
    retention_months_executions INT := 12;  -- Keep 12 months of saga executions
    retention_days_outbox INT := 30;        -- Keep 30 days of outbox events
    partition_name_var TEXT;
    affected_rows BIGINT;
BEGIN
    -- ========================================================================
    -- CREATE FUTURE PARTITIONS
    -- ========================================================================
    
    -- Create saga_executions partitions (current + 3 future months)
    FOR i IN 0..future_months LOOP
        partition_name_var := create_saga_executions_partition(current_date + (i || ' months')::INTERVAL);
        RETURN QUERY SELECT 
            'CREATE'::TEXT,
            'saga_executions'::TEXT,
            partition_name_var,
            format('Created partition for %s', TO_CHAR(current_date + (i || ' months')::INTERVAL, 'YYYY-MM'))::TEXT;
    END LOOP;
    
    -- Create saga_outbox partitions (current + 7 future days)
    FOR i IN 0..future_days LOOP
        partition_name_var := create_saga_outbox_partition(current_date + i);
        RETURN QUERY SELECT 
            'CREATE'::TEXT,
            'saga_outbox'::TEXT,
            partition_name_var,
            format('Created partition for %s', TO_CHAR(current_date + i, 'YYYY-MM-DD'))::TEXT;
    END LOOP;
    
    -- Create saga_audit_log partitions (current + 3 future months)
    FOR i IN 0..future_months LOOP
        partition_name_var := create_saga_audit_log_partition(current_date + (i || ' months')::INTERVAL);
        RETURN QUERY SELECT 
            'CREATE'::TEXT,
            'saga_audit_log'::TEXT,
            partition_name_var,
            format('Created partition for %s', TO_CHAR(current_date + (i || ' months')::INTERVAL, 'YYYY-MM'))::TEXT;
    END LOOP;
    
    -- ========================================================================
    -- DROP OLD PARTITIONS (CLEANUP)
    -- ========================================================================
    
    -- Drop old saga_executions partitions (older than retention period)
    FOR partition_name_var IN 
        SELECT pm.partition_name 
        FROM partition_metadata pm
        WHERE pm.table_name = 'saga_executions'
          AND pm.partition_end < (current_date - (retention_months_executions || ' months')::INTERVAL)
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', partition_name_var);
        DELETE FROM partition_metadata WHERE partition_name = partition_name_var;
        
        RETURN QUERY SELECT 
            'DROP'::TEXT,
            'saga_executions'::TEXT,
            partition_name_var,
            format('Dropped old partition (retention: %s months)', retention_months_executions)::TEXT;
    END LOOP;
    
    -- Drop old saga_outbox partitions (older than retention period)
    FOR partition_name_var IN 
        SELECT pm.partition_name 
        FROM partition_metadata pm
        WHERE pm.table_name = 'saga_outbox'
          AND pm.partition_end < (current_date - retention_days_outbox)
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', partition_name_var);
        DELETE FROM partition_metadata WHERE partition_name = partition_name_var;
        
        RETURN QUERY SELECT 
            'DROP'::TEXT,
            'saga_outbox'::TEXT,
            partition_name_var,
            format('Dropped old partition (retention: %s days)', retention_days_outbox)::TEXT;
    END LOOP;
    
    -- ========================================================================
    -- VACUUM ANALYZE PARTITIONS
    -- ========================================================================
    
    -- Analyze recent partitions for query planner
    FOR partition_name_var IN 
        SELECT pm.partition_name 
        FROM partition_metadata pm
        WHERE pm.table_name IN ('saga_executions', 'saga_outbox')
          AND pm.partition_start >= (current_date - INTERVAL '7 days')
    LOOP
        EXECUTE format('ANALYZE %I', partition_name_var);
        
        RETURN QUERY SELECT 
            'ANALYZE'::TEXT,
            'saga_executions'::TEXT,
            partition_name_var,
            'Analyzed recent partition for query optimization'::TEXT;
    END LOOP;
    
    RETURN;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION maintain_all_partitions IS 
    'Maintains all partitions: creates future ones, drops old ones, analyzes recent ones';

-- ============================================================================
-- 5. Function: Get Partition Statistics
-- ============================================================================

CREATE OR REPLACE FUNCTION get_partition_statistics()
RETURNS TABLE (
    table_name TEXT,
    partition_count BIGINT,
    oldest_partition DATE,
    newest_partition DATE,
    total_size_mb NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        pm.table_name,
        COUNT(*)::BIGINT as partition_count,
        MIN(pm.partition_start)::DATE as oldest_partition,
        MAX(pm.partition_end)::DATE as newest_partition,
        ROUND(SUM(pg_total_relation_size(pm.partition_name::regclass)) / 1024.0 / 1024.0, 2) as total_size_mb
    FROM partition_metadata pm
    GROUP BY pm.table_name
    ORDER BY pm.table_name;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_partition_statistics IS 
    'Returns statistics about current partitions for monitoring';

-- ============================================================================
-- 6. Function: Cleanup Consumer Inbox (Retention Policy)
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_consumer_inbox(
    retention_days INT DEFAULT 90
) RETURNS BIGINT AS $$
DECLARE
    deleted_count BIGINT;
BEGIN
    DELETE FROM consumer_inbox
    WHERE processed_at < (CURRENT_TIMESTAMP - (retention_days || ' days')::INTERVAL);
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_consumer_inbox IS 
    'Deletes old processed events from consumer_inbox (default: 90 days)';

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

\echo '✅ Partition maintenance functions created successfully!'
\echo ''
\echo 'Functions created:'
\echo '  - create_saga_executions_partition(date)'
\echo '  - create_saga_outbox_partition(date)'
\echo '  - create_saga_audit_log_partition(date)'
\echo '  - maintain_all_partitions() -> table of actions'
\echo '  - get_partition_statistics() -> table of stats'
\echo '  - cleanup_consumer_inbox(days) -> count'
\echo ''
\echo 'Next: Run 003_initial_partitions.sql'
