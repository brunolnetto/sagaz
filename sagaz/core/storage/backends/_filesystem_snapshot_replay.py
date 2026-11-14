"""Replay log persistence for :class:`FilesystemSnapshotStorage`."""

from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sagaz.core.replay import ReplayResult


class _FilesystemReplayLogMixin:
    """Stores replay logs as ``replays/{replay_id}.json`` files."""

    replays_dir: Path

    if TYPE_CHECKING:

        def _get_replay_path(self, replay_id: UUID) -> Path: ...

        async def _write_json(self, path: Path, data: dict[str, Any]) -> None: ...

        async def _read_json(self, path: Path) -> dict[str, Any]: ...

    async def save_replay_log(self, replay_result: ReplayResult) -> None:
        """Save replay log"""
        replay_path = self._get_replay_path(replay_result.replay_id)
        await self._write_json(replay_path, replay_result.to_dict())

    async def get_replay_log(self, replay_id: UUID) -> dict[str, Any] | None:
        """Get replay log entry"""
        replay_path = self._get_replay_path(replay_id)
        if not replay_path.exists():
            return None

        return await self._read_json(replay_path)

    async def list_replays(self, original_saga_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
        """List replays for original saga"""
        replays = []

        # Scan all replay files
        for replay_file in self.replays_dir.iterdir():
            if not replay_file.is_file():
                continue

            try:
                replay_data = await self._read_json(replay_file)
                if UUID(replay_data["original_saga_id"]) == original_saga_id:
                    replays.append(replay_data)
            except Exception:
                continue

        # Sort by created_at DESC
        replays.sort(key=lambda r: r.get("created_at", ""), reverse=True)

        return replays[:limit]
