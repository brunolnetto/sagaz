"""Per-saga snapshot index maintenance for :class:`S3SnapshotStorage`."""

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID


class _S3SagaIndexMixin:
    """Keeps the ``index/saga/<saga_id>.json`` object in sync with snapshots."""

    bucket_name: str

    if TYPE_CHECKING:

        async def _get_s3_client(self) -> Any: ...

        def _saga_index_key(self, saga_id: UUID) -> str: ...

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
            {
                "snapshot_id": str(snapshot_id),
                "created_at": created_at.isoformat(),
            }
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
