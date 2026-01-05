#!/bin/bash
# PostgreSQL Primary Initialization Script
# 
# This script runs on the primary PostgreSQL instance during first boot.
# It configures replication user and permissions.

set -e

echo "Initializing PostgreSQL primary for replication..."

# Create replication user (if not exists)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create replication user
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = 'replicator') THEN
            CREATE ROLE replicator WITH REPLICATION PASSWORD 'replicator' LOGIN;
        END IF;
    END
    \$\$;

    -- Grant necessary permissions
    GRANT CONNECT ON DATABASE sagaz TO replicator;
    
    -- Allow replication connections in pg_hba.conf (done via docker run command)
    SELECT pg_reload_conf();
EOSQL

# Configure pg_hba.conf for replication
cat >> "$PGDATA/pg_hba.conf" <<-EOF
# Replication connections
host    replication     replicator      all                     trust
host    replication     postgres        all                     trust
host    all             all             all                     trust
EOF

# Reload configuration
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "SELECT pg_reload_conf();"

echo "Primary initialization complete!"
echo "Replication user 'replicator' created and configured."
