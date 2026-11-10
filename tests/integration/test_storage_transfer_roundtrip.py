"""SQLite → PostgreSQL migration round-trip and idempotency coverage."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_sqlite_to_postgresql_migration_preserves_saga_and_outbox_records(
    postgres_container,
    tmp_path,
) -> None:
    """Migrate complete Saga and Outbox state, verify checksums, then rerun safely."""
    pytest.importorskip("aiosqlite")
    pytest.importorskip("asyncpg")

    from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
    from sagaz.core.storage.manager import StorageManager
    from sagaz.core.types import SagaStatus
    from sagaz.storage.migration import SagaStorageMigrator

    postgres_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://",
        "postgresql://",
    )
    sqlite_path = tmp_path / "source.sqlite"
    sqlite_url = f"sqlite:///{sqlite_path}"

    saga_id = "migration-saga-001"
    event = OutboxEvent(
        event_id=str(uuid4()),
        saga_id=saga_id,
        event_type="OrderFailed",
        payload={"order_id": "order-001", "reason": "payment_declined"},
        aggregate_type="order",
        aggregate_id="order-001",
        headers={"trace_id": "trace-001", "tenant_id": "tenant-a"},
        status=OutboxStatus.DEAD_LETTER,
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        claimed_at=datetime(2026, 1, 2, 3, 5, 5, tzinfo=UTC),
        worker_id="worker-7",
        retry_count=4,
        last_error="broker unavailable",
        routing_key="orders.failed",
        partition_key="tenant-a",
        dead_letter_at=datetime(2026, 1, 2, 3, 6, 5, tzinfo=UTC),
        dead_letter_reason="max_retries_exceeded",
        error_type="BrokerPublishError",
        error_classification="transient",
        error_fingerprint="sha256:abc123",
        replay_count=2,
    )

    async with StorageManager(url=sqlite_url) as source:
        await source.saga.save_saga_state(
            saga_id=saga_id,
            saga_name="OrderSaga",
            status=SagaStatus.ROLLED_BACK,
            steps=[],
            context={"order_id": "order-001", "customer_id": "customer-01"},
            metadata={"schema_version": 2, "origin": "sqlite"},
        )
        await source.outbox.insert(event)

        async with StorageManager(url=postgres_url) as destination:
            migrator = SagaStorageMigrator(source, destination)

            first_run = await migrator.migrate(batch_size=1, on_error="abort")
            assert first_run.success is True
            assert first_run.sagas_transferred == 1
            assert first_run.events_transferred == 1

            verification = await migrator.verify()
            assert verification.ok is True
            assert verification.source_sagas == verification.dest_sagas == 1
            assert verification.source_events == verification.dest_events == 1
            assert verification.source_saga_checksum == verification.dest_saga_checksum
            assert verification.source_event_checksum == verification.dest_event_checksum

            migrated_saga = await destination.saga.load_saga_state(saga_id)
            assert migrated_saga is not None
            assert migrated_saga["status"] == SagaStatus.ROLLED_BACK.value
            assert migrated_saga["context"] == {
                "order_id": "order-001",
                "customer_id": "customer-01",
            }
            assert migrated_saga["metadata"] == {
                "schema_version": 2,
                "origin": "sqlite",
            }

            migrated_event = await destination.outbox.get_by_id(event.event_id)
            assert migrated_event is not None
            assert migrated_event.to_dict() == event.to_dict()

            # A retry after an interrupted migration must converge on the same
            # destination state, not fail on duplicate IDs or add duplicate events.
            second_run = await migrator.migrate(batch_size=1, on_error="abort")
            assert second_run.success is True
            assert await destination.saga.count() == 1
            assert await destination.outbox.count() == 1

            second_verification = await migrator.verify()
            assert second_verification.ok is True
            assert (
                second_verification.source_event_checksum == second_verification.dest_event_checksum
            )

            # Destination has advanced since the source snapshot was taken.
            sent = await destination.outbox.update_status(
                event.event_id,
                OutboxStatus.SENT,
            )
            assert sent.status == OutboxStatus.SENT
            assert sent.sent_at is not None

            stale_retry = await migrator.migrate(
                batch_size=1,
                on_error="skip",
            )

            assert stale_retry.success is False
            assert stale_retry.events_transferred == 0
            assert stale_retry.events_skipped == 1

            preserved = await destination.outbox.get_by_id(event.event_id)
            assert preserved is not None
            assert preserved.status == OutboxStatus.SENT
            assert preserved.sent_at == sent.sent_at

            # Move the destination event into the archive to verify that
            # migration lookup and validation include archived records.
            pool = destination.outbox._pool
            assert pool is not None

            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO saga_outbox_archive
                        SELECT * FROM saga_outbox
                        WHERE event_id = $1
                        """,
                        event.event_id,
                    )
                    await conn.execute(
                        "DELETE FROM saga_outbox WHERE event_id = $1",
                        event.event_id,
                    )

            archived_retry = await migrator.migrate(
                batch_size=1,
                on_error="skip",
            )

            assert archived_retry.success is False
            assert archived_retry.events_transferred == 0
            assert archived_retry.events_skipped == 1

            archived = await destination.outbox.get_by_id(event.event_id)
            assert archived is not None
            assert archived.status == OutboxStatus.SENT
            assert archived.sent_at == sent.sent_at
