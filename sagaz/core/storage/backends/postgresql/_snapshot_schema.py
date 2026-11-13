"""DDL for the PostgreSQL snapshot and replay-log tables."""

# SQL schema for snapshot tables (from ADR-024)
SNAPSHOT_TABLES_SQL = """
    -- Checkpoint snapshots for replay
    CREATE TABLE IF NOT EXISTS saga_snapshots (
        snapshot_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        saga_id          UUID NOT NULL,
        saga_name        VARCHAR(255) NOT NULL,
        step_name        VARCHAR(255) NOT NULL,
        step_index       INTEGER NOT NULL,

        -- State
        status           VARCHAR(50) NOT NULL,
        context          JSONB NOT NULL,
        completed_steps  JSONB NOT NULL,

        -- Metadata
        created_at       TIMESTAMPTZ DEFAULT NOW(),
        retention_until  TIMESTAMPTZ,

        -- Indexes
        CONSTRAINT idx_saga_snapshots_saga_id_step UNIQUE(saga_id, step_name, created_at)
    );

    CREATE INDEX IF NOT EXISTS idx_saga_snapshots_saga_id ON saga_snapshots(saga_id);
    CREATE INDEX IF NOT EXISTS idx_saga_snapshots_created_at ON saga_snapshots(created_at);
    CREATE INDEX IF NOT EXISTS idx_saga_snapshots_retention ON saga_snapshots(retention_until);

    -- Replay audit trail
    CREATE TABLE IF NOT EXISTS saga_replay_log (
        replay_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        original_saga_id UUID NOT NULL,
        new_saga_id      UUID NOT NULL,

        -- Replay parameters
        checkpoint_step  VARCHAR(255) NOT NULL,
        context_override JSONB,
        initiated_by     VARCHAR(255) NOT NULL,

        -- Results
        replay_status    VARCHAR(50) NOT NULL,
        error_message    TEXT,

        created_at       TIMESTAMPTZ DEFAULT NOW(),
        completed_at     TIMESTAMPTZ
    );

    CREATE INDEX IF NOT EXISTS idx_replay_log_original_saga ON saga_replay_log(original_saga_id);
    CREATE INDEX IF NOT EXISTS idx_replay_log_created_at ON saga_replay_log(created_at);
    """
