"""Replay log persistence for :class:`S3SnapshotStorage`."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sagaz.core.replay import ReplayResult


class _S3ReplayLogMixin:
    """Stores and lists replay logs under the ``replay/`` prefix."""

    bucket_name: str
    prefix: str
    storage_class: str
    enable_encryption: bool

    if TYPE_CHECKING:

        async def _get_s3_client(self) -> Any: ...

        def _replay_log_key(self, replay_id: UUID) -> str: ...

        def _serialize(self, data: dict[str, Any]) -> bytes: ...

        def _deserialize(self, data: bytes) -> dict[str, Any]: ...

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
