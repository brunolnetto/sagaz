"""PostgreSQL schema-upgrade coverage for StateChart configuration."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_existing_postgresql_saga_table_is_upgraded_with_configuration() -> None:
    asyncpg = pytest.importorskip("asyncpg")
    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    with PostgresContainer("postgres:16") as postgres:
        dsn = postgres.get_connection_url().replace(
            "postgresql+psycopg2://",
            "postgresql://",
        )
        connection = await asyncpg.connect(dsn)
        try:
            # Simulate the schema shipped before StateChart configuration was added.
            await connection.execute(
                """
                CREATE TABLE sagas (
                    saga_id VARCHAR(255) PRIMARY KEY,
                    saga_name VARCHAR(255) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    context JSONB,
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
            await connection.execute(
                """
                INSERT INTO sagas (saga_id, saga_name, status, context, metadata)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                """,
                "legacy-saga",
                "LegacySaga",
                "executing",
                '{"order_id":"order-123"}',
                "{}",
            )
        finally:
            await connection.close()

        storage = PostgreSQLSagaStorage(dsn)
        async with storage:
            loaded = await storage.load_saga_state("legacy-saga")

        assert loaded is not None
        assert loaded["configuration"] == ["executing"]
        assert loaded["context"] == {"order_id": "order-123"}
