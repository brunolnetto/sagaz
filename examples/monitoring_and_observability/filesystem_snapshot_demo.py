"""
Filesystem Snapshot Storage Demo

Simple demonstration of FilesystemSnapshotStorage for local development.
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sagaz.core.replay import SagaSnapshot
from sagaz.core.storage.backends import FilesystemSnapshotStorage
from sagaz.core.types import SagaStatus


async def main():

    # Create storage
    storage = FilesystemSnapshotStorage(
        base_path="./demo-snapshots", enable_compression=False, pretty_json=True
    )

    # Create a sample snapshot
    saga_id = uuid4()
    snapshot = SagaSnapshot(
        snapshot_id=uuid4(),
        saga_id=saga_id,
        saga_name="order_processing",
        step_name="authorize_payment",
        step_index=1,
        status=SagaStatus.EXECUTING,
        context={"order_id": "ORD-123", "amount": 99.99, "currency": "USD"},
        completed_steps=["reserve_inventory"],
        created_at=datetime.now(UTC),
    )

    # Save snapshot
    await storage.save_snapshot(snapshot)

    # Retrieve it
    await storage.get_snapshot(snapshot.snapshot_id)

    # List all snapshots
    await storage.list_snapshots(saga_id)

    # Storage stats
    storage.get_storage_info()

    # Show file location
    snapshot_dir = storage.snapshots_dir / str(saga_id)
    for _f in snapshot_dir.glob("*.json"):
        pass


if __name__ == "__main__":
    asyncio.run(main())
