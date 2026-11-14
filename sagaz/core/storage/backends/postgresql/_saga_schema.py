"""DDL for the PostgreSQL saga storage tables.

Tenancy (ADR-020): both tables carry ``tenant_id`` with row-level security
(:func:`tenant_isolation_sql`), sagas are keyed by ``(tenant_id, saga_id)`` and
steps reference that key, so two tenants may use the same saga id.

The script is idempotent and upgrades databases from older versions in place:
existing rows become the ``'default'`` tenant's, the ``saga_id`` primary key is
replaced by ``(tenant_id, saga_id)`` and the step constraints follow. It runs
as one transaction (a multi-statement simple query) under an advisory lock, in
the system scope (``app.tenant_id = '*'`` for that transaction only), so the
backfills see every tenant's rows.
"""

from sagaz.core.storage.backends.postgresql._tenancy import tenant_isolation_sql

_PREAMBLE = """
    SELECT pg_advisory_xact_lock(hashtext('sagaz_saga_schema'));
    SELECT set_config('app.tenant_id', '*', true);
"""

_SAGAS_TABLE = """
    CREATE TABLE IF NOT EXISTS sagas (
        tenant_id TEXT NOT NULL DEFAULT 'default',
        saga_id VARCHAR(255) NOT NULL,
        saga_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL,
        context JSONB,
        metadata JSONB,
        configuration JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        PRIMARY KEY (tenant_id, saga_id)
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
"""

# Databases created before tenancy have PRIMARY KEY (saga_id), referenced by
# saga_steps: drop those step foreign keys, then re-key sagas by tenant.
_SAGAS_TENANT_KEY = """
    DO $$
    DECLARE
        pk_name TEXT;
        pk_has_tenant BOOLEAN;
        fk RECORD;
    BEGIN
        SELECT c.conname,
               EXISTS (SELECT 1 FROM pg_attribute a
                       WHERE a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                         AND a.attname = 'tenant_id')
          INTO pk_name, pk_has_tenant
          FROM pg_constraint c
         WHERE c.conrelid = 'sagas'::regclass AND c.contype = 'p';
        IF pk_name IS NOT NULL AND NOT pk_has_tenant THEN
            IF to_regclass('saga_steps') IS NOT NULL THEN
                FOR fk IN SELECT conname FROM pg_constraint
                          WHERE conrelid = 'saga_steps'::regclass AND contype = 'f'
                            AND confrelid = 'sagas'::regclass LOOP
                    EXECUTE format('ALTER TABLE saga_steps DROP CONSTRAINT %I', fk.conname);
                END LOOP;
            END IF;
            EXECUTE format('ALTER TABLE sagas DROP CONSTRAINT %I', pk_name);
            ALTER TABLE sagas ADD PRIMARY KEY (tenant_id, saga_id);
        END IF;
    END $$;
"""

_STEPS_TABLE = """
    CREATE TABLE IF NOT EXISTS saga_steps (
        id SERIAL PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        saga_id VARCHAR(255),
        step_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL,
        result JSONB,
        error TEXT,
        executed_at TIMESTAMP WITH TIME ZONE,
        compensated_at TIMESTAMP WITH TIME ZONE,
        retry_count INTEGER DEFAULT 0,
        duration_ms DOUBLE PRECISION,
        CONSTRAINT saga_steps_tenant_saga_fkey FOREIGN KEY (tenant_id, saga_id)
            REFERENCES sagas(tenant_id, saga_id) ON DELETE CASCADE,
        CONSTRAINT saga_steps_tenant_step_key UNIQUE (tenant_id, saga_id, step_name)
    );

    -- Idempotent upgrade: step latency for analytics (sagaz[analytics]).
    ALTER TABLE saga_steps ADD COLUMN IF NOT EXISTS duration_ms DOUBLE PRECISION;
"""

# Pre-tenancy steps: swap UNIQUE (saga_id, step_name) and the saga_id foreign
# key for their tenant-aware versions (runs after tenant_id was added).
_STEPS_TENANT_KEYS = """
    DO $$
    DECLARE
        con RECORD;
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conrelid = 'saga_steps'::regclass
                         AND conname = 'saga_steps_tenant_saga_fkey') THEN
            FOR con IN SELECT conname FROM pg_constraint
                       WHERE conrelid = 'saga_steps'::regclass
                         AND (contype = 'u' OR (contype = 'f' AND confrelid = 'sagas'::regclass))
            LOOP
                EXECUTE format('ALTER TABLE saga_steps DROP CONSTRAINT %I', con.conname);
            END LOOP;
            ALTER TABLE saga_steps
                ADD CONSTRAINT saga_steps_tenant_step_key UNIQUE (tenant_id, saga_id, step_name);
            ALTER TABLE saga_steps
                ADD CONSTRAINT saga_steps_tenant_saga_fkey FOREIGN KEY (tenant_id, saga_id)
                REFERENCES sagas(tenant_id, saga_id) ON DELETE CASCADE;
        END IF;
    END $$;
"""

_INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_sagas_status ON sagas(status);
    CREATE INDEX IF NOT EXISTS idx_sagas_name ON sagas(saga_name);
    CREATE INDEX IF NOT EXISTS idx_sagas_created_at ON sagas(created_at);
    CREATE INDEX IF NOT EXISTS idx_sagas_saga_id ON sagas(saga_id);
    CREATE INDEX IF NOT EXISTS idx_saga_steps_saga_id ON saga_steps(saga_id);
    CREATE INDEX IF NOT EXISTS idx_saga_steps_status ON saga_steps(status);
"""

# SQL schema for saga tables
SAGA_TABLES_SQL = (
    _PREAMBLE
    + _SAGAS_TABLE
    + tenant_isolation_sql("sagas")
    + _SAGAS_TENANT_KEY
    + _STEPS_TABLE
    + tenant_isolation_sql("saga_steps")
    + _STEPS_TENANT_KEYS
    + _INDEXES
)
