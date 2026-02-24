"""
Filesystem Snapshot Storage Demo

Simple demonstration of FilesystemSnapshotStorage for local development.
"""

import asyncio
from pathlib import Path
from datetime import UTC, datetime
from uuid import uuid4

from sagaz.core.replay import SagaSnapshot
from sagaz.core.types import SagaStatus
from sagaz.storage.backends import FilesystemSnapshotStorage


async def main():
    print("=" * 60)
    print("Filesystem Snapshot Storage Demo")
    print("=" * 60)
    
    # Create storage
    storage = FilesystemSnapshotStorage(
        base_path="./demo-snapshots",
        enable_compression=False,
        pretty_json=True
    )
    
    print(f"\n✓ Storage created at: {storage.base_path.absolute()}")
    
    # Create a sample snapshot
    saga_id = uuid4()
    snapshot = SagaSnapshot(
        snapshot_id=uuid4(),
        saga_id=saga_id,
        saga_name="order_processing",
        step_name="authorize_payment",
        step_index=1,
        status=SagaStatus.EXECUTING,
        context={
            "order_id": "ORD-123",
            "amount": 99.99,
            "currency": "USD"
        },
        completed_steps=["reserve_inventory"],
        created_at=datetime.now(UTC),
    )
    
    # Save snapshot
    await storage.save_snapshot(snapshot)
    print(f"✓ Saved snapshot: {snapshot.snapshot_id}")
    
    # Retrieve it
    retrieved = await storage.get_snapshot(snapshot.snapshot_id)
    print(f"✓ Retrieved snapshot for saga: {retrieved.saga_name}")
    
    # List all snapshots
    snapshots = await storage.list_snapshots(saga_id)
    print(f"✓ Total snapshots for saga: {len(snapshots)}")
    
    # Storage stats
    info = storage.get_storage_info()
    print(f"\nStorage Statistics:")
    print(f"  - Total sagas: {info['total_sagas']}")
    print(f"  - Total snapshots: {info['total_snapshots']}")
    print(f"  - Storage size: {info['total_size_mb']} MB")
    
    # Show file location
    snapshot_dir = storage.snapshots_dir / str(saga_id)
    print(f"\n📁 Snapshot files:")
    for f in snapshot_dir.glob("*.json"):
        print(f"   {f.name}")
    
    print(f"\n✅ Demo complete!")
    print(f"💡 Inspect snapshots with: cat {snapshot_dir}/*.json | jq '.'")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
