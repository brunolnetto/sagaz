"""PostgreSQL snapshots keep the StateChart configuration (#517, ADR-040 §5)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sagaz.core.replay import SagaSnapshot
from sagaz.core.types import SagaStatus

asyncpg = pytest.importorskip("asyncpg")

from sagaz.core.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="postgres")]


@pytest.fixture
async def storage(postgres_container):
    url = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    store = PostgreSQLSnapshotStorage(connection_string=url, pool_min_size=1, pool_max_size=2)
    yield store
    await store.close()


def snapshot(configuration: list[str] | None) -> SagaSnapshot:
    return SagaSnapshot(
        snapshot_id=uuid4(),
        saga_id=uuid4(),
        saga_name="order",
        step_name="charge",
        step_index=1,
        status=SagaStatus.COMPENSATING,
        context={},
        completed_steps=["reserve"],
        created_at=datetime.now(UTC),
        retention_until=None,
        configuration=configuration,
    )


async def test_a_nested_configuration_round_trips(storage):
    nested = [
        "active",
        "lifecycle",
        "compensating",
        "steps",
        "step/reserve",
        "step/reserve/compensating",
    ]
    saved = snapshot(nested)
    await storage.save_snapshot(saved)
    loaded = await storage.get_snapshot(saved.snapshot_id)
    assert loaded.configuration == nested


async def test_older_rows_fall_back_to_the_status(storage):
    saved = snapshot(None)
    await storage.save_snapshot(saved)
    pool = await storage._get_pool()
    async with pool.acquire() as conn:  # a row written before configuration was kept
        await conn.execute(
            "UPDATE saga_snapshots SET configuration = NULL WHERE snapshot_id = $1",
            saved.snapshot_id,
        )
    loaded = await storage.get_snapshot(saved.snapshot_id)
    assert loaded.configuration == ["compensating"]
