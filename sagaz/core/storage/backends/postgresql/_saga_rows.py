"""Row mapping helpers for :class:`PostgreSQLSagaStorage`."""

import json
from typing import Any


class _PostgreSQLSagaRowMixin:
    """Converts asyncpg saga/step rows into the storage dict format."""

    def _build_saga_dict(self, saga_row, step_rows) -> dict[str, Any]:
        """Build saga dict from database rows."""
        try:
            raw_configuration = saga_row["configuration"]
        except (KeyError, IndexError):
            raw_configuration = None

        if isinstance(raw_configuration, str):
            raw_configuration = json.loads(raw_configuration)
        configuration = raw_configuration or [saga_row["status"]]

        return {
            "saga_id": saga_row["saga_id"],
            "saga_name": saga_row["saga_name"],
            "status": saga_row["status"],
            "configuration": configuration,
            "context": json.loads(saga_row["context"]) if saga_row["context"] else {},
            "metadata": json.loads(saga_row["metadata"]) if saga_row["metadata"] else {},
            "steps": [self._parse_step_row(row) for row in step_rows],
            "created_at": saga_row["created_at"].isoformat(),
            "updated_at": saga_row["updated_at"].isoformat(),
        }

    def _parse_step_row(self, step_row) -> dict[str, Any]:
        """Parse a step database row into a dict."""
        step_data = {
            "name": step_row["step_name"],
            "status": step_row["status"],
            "error": step_row["error"],
            "retry_count": step_row["retry_count"],
        }

        if step_row["result"]:
            step_data["result"] = self._parse_json_safe(step_row["result"])

        if step_row["executed_at"]:
            step_data["executed_at"] = step_row["executed_at"].isoformat()
        if step_row["compensated_at"]:
            step_data["compensated_at"] = step_row["compensated_at"].isoformat()
        try:
            duration_ms = step_row["duration_ms"]
        except (KeyError, IndexError):  # rows selected without the column
            duration_ms = None
        if duration_ms is not None:
            step_data["duration_ms"] = duration_ms

        return step_data

    def _parse_json_safe(self, value: str) -> Any:
        """Parse JSON, returning raw value on failure."""
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _format_bytes(self, num_bytes: int) -> str:
        """Format bytes in human readable format"""
        size: float = float(num_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.1f}{unit}"
            size = size / 1024.0
        return f"{size:.1f}PB"
