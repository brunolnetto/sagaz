# ============================================
# FILE: sagaz/storage/backends/s3/snapshot.py
# ============================================

"""
S3 Snapshot Storage

AWS S3-based storage for saga snapshots with automatic compression,
encryption, lifecycle management, and scalable object storage.

Requires: pip install aioboto3 zstandard
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.replay import ReplayResult, SagaSnapshot, SnapshotNotFoundError
from sagaz.storage.interfaces.snapshot import SnapshotStorage

try:
    import aioboto3

    AIOBOTO3_AVAILABLE = True
except ImportError:
    AIOBOTO3_AVAILABLE = False  # pragma: no cover
    aioboto3 = None  # pragma: no cover

try:
    import zstandard as zstd

    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False  # pragma: no cover
    zstd = None  # pragma: no cover


class S3SnapshotStorage(SnapshotStorage):
    """
    AWS S3 implementation of snapshot storage

    Uses S3 for scalable, durable snapshot storage with optional
    compression, encryption, and lifecycle policies.

    Example:
        >>> storage = S3SnapshotStorage(
        ...     bucket_name="my-saga-snapshots",
        ...     region_name="us-east-1"
        ... )
        >>> async with storage:
        ...     await storage.save_snapshot(snapshot)
    """

    def __init__(
        self,
        bucket_name: str,
        region_name: str = "us-east-1",
        prefix: str = "snapshots/",
        enable_compression: bool = True,
        compression_level: int = 3,  # zstd compression level (1-22)
        enable_encryption: bool = True,  # Server-side encryption (SSE-S3)
        storage_class: str = "STANDARD",  # or "STANDARD_IA", "GLACIER", etc.
        **s3_kwargs,
    ):
        if not AIOBOTO3_AVAILABLE:
            msg = "aioboto3"
            raise MissingDependencyError(msg, "S3 snapshot storage backend")

        if enable_compression and not ZSTD_AVAILABLE:
            msg = "zstandard"
            raise MissingDependencyError(
                msg, "Snapshot compression (install with: pip install zstandard)"
            )

        self.bucket_name = bucket_name
        self.region_name = region_name
        self.prefix = prefix
        self.enable_compression = enable_compression and ZSTD_AVAILABLE
        self.compression_level = compression_level
        self.enable_encryption = enable_encryption
        self.storage_class = storage_class
        self.s3_kwargs = s3_kwargs
        self._session = None
        self._s3_client = None
        self._lock = asyncio.Lock()
        self._compressor = (
            zstd.ZstdCompressor(level=compression_level) if self.enable_compression else None
        )
        self._decompressor = zstd.ZstdDecompressor() if self.enable_compression else None

    async def _get_s3_client(self):
        """Get S3 client, creating if necessary"""
        if self._s3_client is None:
            try:
                self._session = aioboto3.Session()
                self._s3_client = await self._session.client(
                    "s3", region_name=self.region_name, **self.s3_kwargs
                ).__aenter__()
            except Exception as e:
                msg = f"Failed to create S3 client: {e}"
                raise ConnectionError(msg)

        return self._s3_client

    def _snapshot_key(self, snapshot_id: UUID) -> str:
        """Generate S3 key for snapshot"""
        return (
            f"{self.prefix}snapshot/{snapshot_id}.json.zst"
            if self.enable_compression
            else f"{self.prefix}snapshot/{snapshot_id}.json"
        )

    def _saga_index_key(self, saga_id: UUID) -> str:
        """Generate S3 key for saga index"""
        return f"{self.prefix}index/saga/{saga_id}.json"

    def _replay_log_key(self, replay_id: UUID) -> str:
        """Generate S3 key for replay log"""
        return f"{self.prefix}replay/{replay_id}.json"

    def _serialize(self, data: dict[str, Any]) -> bytes:
        """Serialize and optionally compress data"""
        json_bytes = json.dumps(data, default=str).encode("utf-8")

        if self.enable_compression and self._compressor:
            return self._compressor.compress(json_bytes)

        return json_bytes

    def _deserialize(self, data: bytes) -> dict[str, Any]:
        """Decompress and deserialize data"""
        if self.enable_compression and self._decompressor:
            json_bytes = self._decompressor.decompress(data)
        else:
            json_bytes = data

        return json.loads(json_bytes.decode("utf-8"))

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """Save snapshot to S3"""
        s3 = await self._get_s3_client()

        # Serialize snapshot
        snapshot_data = snapshot.to_dict()
        serialized = self._serialize(snapshot_data)

        # Prepare S3 put parameters
        put_params = {
            "Bucket": self.bucket_name,
            "Key": self._snapshot_key(snapshot.snapshot_id),
            "Body": serialized,
            "StorageClass": self.storage_class,
            "Metadata": {
                "saga_id": str(snapshot.saga_id),
                "saga_name": snapshot.saga_name,
                "step_name": snapshot.step_name,
                "created_at": snapshot.created_at.isoformat(),
            },
        }

        # Add server-side encryption
        if self.enable_encryption:
            put_params["ServerSideEncryption"] = "AES256"

        # Set lifecycle expiration
        if snapshot.retention_until:
            put_params["Expires"] = snapshot.retention_until

        # Upload to S3
        await s3.put_object(**put_params)

        # Update saga index (list of snapshots for this saga)
        await self._update_saga_index(snapshot.saga_id, snapshot.snapshot_id, snapshot.created_at)

    async def _update_saga_index(
        self, saga_id: UUID, snapshot_id: UUID, created_at: datetime
    ) -> None:
        """Update saga index with new snapshot"""
        s3 = await self._get_s3_client()
        index_key = self._saga_index_key(saga_id)

        # Get existing index
        try:
            response = await s3.get_object(Bucket=self.bucket_name, Key=index_key)
            body = await response["Body"].read()
            index_data = json.loads(body.decode("utf-8"))
        except s3.exceptions.NoSuchKey:  # type: ignore[attr-defined]
            index_data = {"saga_id": str(saga_id), "snapshots": []}

        # Add new snapshot
        index_data["snapshots"].append(
            {"snapshot_id": str(snapshot_id), "created_at": created_at.isoformat()}
        )

        # Sort by created_at DESC
        index_data["snapshots"].sort(key=lambda x: x["created_at"], reverse=True)

        # Keep only last 1000 entries in index
        index_data["snapshots"] = index_data["snapshots"][:1000]

        # Save index
        await s3.put_object(
            Bucket=self.bucket_name,
            Key=index_key,
            Body=json.dumps(index_data).encode("utf-8"),
            ContentType="application/json",
        )

    async def get_snapshot(self, snapshot_id: UUID) -> SagaSnapshot | None:
        """Retrieve snapshot by ID"""
        s3 = await self._get_s3_client()

        try:
            response = await s3.get_object(
                Bucket=self.bucket_name, Key=self._snapshot_key(snapshot_id)
            )
            body = await response["Body"].read()
            snapshot_dict = self._deserialize(body)
            return SagaSnapshot.from_dict(snapshot_dict)
        except s3.exceptions.NoSuchKey:  # type: ignore[attr-defined]
            return None

    async def get_latest_snapshot(
        self, saga_id: UUID, before_step: str | None = None
    ) -> SagaSnapshot | None:
        """Get most recent snapshot for saga"""
        s3 = await self._get_s3_client()

        # Get saga index
        try:
            response = await s3.get_object(
                Bucket=self.bucket_name, Key=self._saga_index_key(saga_id)
            )
            body = await response["Body"].read()
            index_data = json.loads(body.decode("utf-8"))
        except s3.exceptions.NoSuchKey:  # type: ignore[attr-defined]
            return None

        # Find matching snapshot
        for entry in index_data.get("snapshots", []):
            snapshot_id = UUID(entry["snapshot_id"])
            snapshot = await self.get_snapshot(snapshot_id)

            if snapshot is None:
                continue

            # Filter by before_step if provided
            if before_step is None or snapshot.step_name == before_step:
                return snapshot

        return None

    async def get_snapshot_at_time(self, saga_id: UUID, timestamp: datetime) -> SagaSnapshot | None:
        """Get snapshot at or before given timestamp"""
        s3 = await self._get_s3_client()

        # Get saga index
        try:
            response = await s3.get_object(
                Bucket=self.bucket_name, Key=self._saga_index_key(saga_id)
            )
            body = await response["Body"].read()
            index_data = json.loads(body.decode("utf-8"))
        except s3.exceptions.NoSuchKey:  # type: ignore[attr-defined]
            return None

        # Find snapshot at or before timestamp
        target_snapshot = None
        for entry in index_data.get("snapshots", []):
            entry_time = datetime.fromisoformat(entry["created_at"])
            if entry_time <= timestamp:
                snapshot_id = UUID(entry["snapshot_id"])
                target_snapshot = await self.get_snapshot(snapshot_id)
                break

        return target_snapshot

    async def list_snapshots(self, saga_id: UUID, limit: int = 100) -> list[SagaSnapshot]:
        """List all snapshots for saga"""
        s3 = await self._get_s3_client()

        # Get saga index
        try:
            response = await s3.get_object(
                Bucket=self.bucket_name, Key=self._saga_index_key(saga_id)
            )
            body = await response["Body"].read()
            index_data = json.loads(body.decode("utf-8"))
        except s3.exceptions.NoSuchKey:  # type: ignore[attr-defined]
            return []

        # Fetch snapshots
        snapshots = []
        for entry in index_data.get("snapshots", [])[:limit]:
            snapshot_id = UUID(entry["snapshot_id"])
            snapshot = await self.get_snapshot(snapshot_id)
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    async def delete_snapshot(self, snapshot_id: UUID) -> bool:
        """Delete snapshot"""
        s3 = await self._get_s3_client()

        # Get snapshot to find saga_id
        snapshot = await self.get_snapshot(snapshot_id)
        if snapshot is None:
            return False

        # Delete snapshot
        try:
            await s3.delete_object(Bucket=self.bucket_name, Key=self._snapshot_key(snapshot_id))

            # Remove from saga index
            await self._remove_from_saga_index(snapshot.saga_id, snapshot_id)

            return True
        except Exception:
            return False

    async def _remove_from_saga_index(self, saga_id: UUID, snapshot_id: UUID) -> None:
        """Remove snapshot from saga index"""
        s3 = await self._get_s3_client()
        index_key = self._saga_index_key(saga_id)

        try:
            response = await s3.get_object(Bucket=self.bucket_name, Key=index_key)
            body = await response["Body"].read()
            index_data = json.loads(body.decode("utf-8"))

            # Remove snapshot
            index_data["snapshots"] = [
                entry
                for entry in index_data["snapshots"]
                if entry["snapshot_id"] != str(snapshot_id)
            ]

            # Save index
            await s3.put_object(
                Bucket=self.bucket_name,
                Key=index_key,
                Body=json.dumps(index_data).encode("utf-8"),
                ContentType="application/json",
            )
        except s3.exceptions.NoSuchKey:  # type: ignore[attr-defined]
            pass

    async def delete_expired_snapshots(self) -> int:
        """
        Delete expired snapshots

        Note: S3 lifecycle policies are recommended for automatic expiration.
        This method provides manual cleanup.
        """
        s3 = await self._get_s3_client()
        now = datetime.now(UTC)
        deleted_count = 0

        # List all snapshot objects
        paginator = s3.get_paginator("list_objects_v2")
        async for page in paginator.paginate(
            Bucket=self.bucket_name, Prefix=f"{self.prefix}snapshot/"
        ):
            for obj in page.get("Contents", []):
                # Get object metadata
                try:
                    response = await s3.head_object(Bucket=self.bucket_name, Key=obj["Key"])
                    expires = response.get("Expires")

                    if expires and expires < now:
                        # Extract snapshot_id from key
                        key_parts = obj["Key"].split("/")
                        snapshot_id_str = (
                            key_parts[-1].replace(".json.zst", "").replace(".json", "")
                        )
                        snapshot_id = UUID(snapshot_id_str)

                        # Delete snapshot
                        if await self.delete_snapshot(snapshot_id):
                            deleted_count += 1
                except Exception:
                    continue

        return deleted_count

    async def save_replay_log(self, replay_result: ReplayResult) -> None:
        """Save replay log"""
        s3 = await self._get_s3_client()

        # Serialize replay log
        replay_data = replay_result.to_dict()
        serialized = self._serialize(replay_data)

        # Upload to S3
        put_params = {
            "Bucket": self.bucket_name,
            "Key": self._replay_log_key(replay_result.replay_id),
            "Body": serialized,
            "StorageClass": self.storage_class,
            "Metadata": {
                "original_saga_id": str(replay_result.original_saga_id),
                "created_at": replay_result.created_at.isoformat(),
            },
        }

        if self.enable_encryption:
            put_params["ServerSideEncryption"] = "AES256"

        await s3.put_object(**put_params)

    async def get_replay_log(self, replay_id: UUID) -> dict[str, Any] | None:
        """Get replay log entry"""
        s3 = await self._get_s3_client()

        try:
            response = await s3.get_object(
                Bucket=self.bucket_name, Key=self._replay_log_key(replay_id)
            )
            body = await response["Body"].read()
            return self._deserialize(body)
        except s3.exceptions.NoSuchKey:  # type: ignore[attr-defined]
            return None

    async def list_replays(self, original_saga_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
        """List replays for original saga"""
        s3 = await self._get_s3_client()

        replays = []

        # List replay objects
        paginator = s3.get_paginator("list_objects_v2")
        async for page in paginator.paginate(
            Bucket=self.bucket_name, Prefix=f"{self.prefix}replay/"
        ):
            for obj in page.get("Contents", []):
                # Get replay log
                try:
                    response = await s3.get_object(Bucket=self.bucket_name, Key=obj["Key"])
                    body = await response["Body"].read()
                    replay_data = self._deserialize(body)

                    # Filter by original_saga_id
                    if UUID(replay_data["original_saga_id"]) == original_saga_id:
                        replays.append(replay_data)

                        if len(replays) >= limit:
                            break
                except Exception:
                    continue

            if len(replays) >= limit:
                break

        # Sort by created_at DESC
        replays.sort(key=lambda r: r["created_at"], reverse=True)

        return replays[:limit]

    async def close(self) -> None:
        """Close S3 client"""
        if self._s3_client:
            await self._s3_client.__aexit__(None, None, None)
            self._s3_client = None
            self._session = None

    async def __aenter__(self):
        """Context manager entry"""
        await self._get_s3_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.close()
