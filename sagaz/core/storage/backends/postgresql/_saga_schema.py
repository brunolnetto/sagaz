"""DDL for the PostgreSQL saga storage tables."""

# SQL schema for saga tables
SAGA_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS sagas (
        saga_id VARCHAR(255) PRIMARY KEY,
        saga_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL,
        context JSONB,
        metadata JSONB,
        configuration JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    -- Idempotent upgrade for databases created before StateChart configuration.
    ALTER TABLE sagas ADD COLUMN IF NOT EXISTS configuration JSONB;
    UPDATE sagas
    SET configuration = jsonb_build_array(status)
    WHERE configuration IS NULL OR configuration = '[]'::jsonb;
    ALTER TABLE sagas
        ALTER COLUMN configuration SET DEFAULT '[]'::jsonb;
    ALTER TABLE sagas
        ALTER COLUMN configuration SET NOT NULL;

    CREATE TABLE IF NOT EXISTS saga_steps (
        id SERIAL PRIMARY KEY,
        saga_id VARCHAR(255) REFERENCES sagas(saga_id) ON DELETE CASCADE,
        step_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL,
        result JSONB,
        error TEXT,
        executed_at TIMESTAMP WITH TIME ZONE,
        compensated_at TIMESTAMP WITH TIME ZONE,
        retry_count INTEGER DEFAULT 0,
        duration_ms DOUBLE PRECISION,
        UNIQUE(saga_id, step_name)
    );

    -- Idempotent upgrade: step latency for analytics (sagaz[analytics]).
    ALTER TABLE saga_steps ADD COLUMN IF NOT EXISTS duration_ms DOUBLE PRECISION;

    CREATE INDEX IF NOT EXISTS idx_sagas_status ON sagas(status);
    CREATE INDEX IF NOT EXISTS idx_sagas_name ON sagas(saga_name);
    CREATE INDEX IF NOT EXISTS idx_sagas_created_at ON sagas(created_at);
    CREATE INDEX IF NOT EXISTS idx_saga_steps_saga_id ON saga_steps(saga_id);
    CREATE INDEX IF NOT EXISTS idx_saga_steps_status ON saga_steps(status);
    """
