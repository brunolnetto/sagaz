"""
Unit tests for Dead Letter Queue (DLQ) feature — issue #44.

TDD red phase: these tests define the acceptance criteria and must
run before the implementation is added.

Acceptance Criteria (from issue #44):
- OutboxEvent gains dead_letter_at and dead_letter_reason fields
- After max_retries is exceeded, event moves to DLQ with those fields set
- InMemoryOutboxStorage supports requeue_dead_letter_event and purge_dead_letter_events
- sagaz_dlq_depth Prometheus gauge exists on the OutboxWorkerMetrics class
- CLI module sagaz.cli.dlq exports dlq_cli group with list/replay/purge commands
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sagaz.outbox.types import OutboxEvent, OutboxStatus
from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage

# ---------------------------------------------------------------------------
# OutboxEvent field tests
# ---------------------------------------------------------------------------


class TestOutboxEventDLQFields:
    """OutboxEvent must carry dead_letter_at and dead_letter_reason."""

    def test_dead_letter_at_defaults_to_none(self):
        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
        )
        assert event.dead_letter_at is None

    def test_dead_letter_reason_defaults_to_none(self):
        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
        )
        assert event.dead_letter_reason is None

    def test_dead_letter_fields_settable(self):
        now = datetime.now(UTC)
        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            dead_letter_at=now,
            dead_letter_reason="max_retries_exceeded",
        )
        assert event.dead_letter_at == now
        assert event.dead_letter_reason == "max_retries_exceeded"

    def test_to_dict_includes_dead_letter_fields(self):
        now = datetime.now(UTC)
        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            dead_letter_at=now,
            dead_letter_reason="poison_message",
        )
        d = event.to_dict()
        assert "dead_letter_at" in d
        assert "dead_letter_reason" in d
        assert d["dead_letter_reason"] == "poison_message"

    def test_from_dict_roundtrip_preserves_dead_letter_fields(self):
        now = datetime.now(UTC)
        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            dead_letter_at=now,
            dead_letter_reason="max_retries_exceeded",
        )
        restored = OutboxEvent.from_dict(event.to_dict())
        assert restored.dead_letter_reason == "max_retries_exceeded"
        assert restored.dead_letter_at is not None

    def test_from_dict_missing_dead_letter_fields_defaults_to_none(self):
        raw = {
            "saga_id": "s1",
            "event_type": "Foo",
            "payload": {},
        }
        event = OutboxEvent.from_dict(raw)
        assert event.dead_letter_at is None
        assert event.dead_letter_reason is None


# ---------------------------------------------------------------------------
# InMemoryOutboxStorage DLQ operations
# ---------------------------------------------------------------------------


class TestInMemoryOutboxStorageDLQ:
    """InMemoryOutboxStorage must support requeue and purge for DLQ events."""

    @pytest.fixture
    def storage(self):
        return InMemoryOutboxStorage()

    @pytest.fixture
    def dead_event(self):
        return OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            status=OutboxStatus.DEAD_LETTER,
            dead_letter_at=datetime.now(UTC),
            dead_letter_reason="max_retries_exceeded",
        )

    @pytest.mark.asyncio
    async def test_requeue_dead_letter_event_resets_to_pending(self, storage, dead_event):
        await storage.insert(dead_event)
        requeued = await storage.requeue_dead_letter_event(dead_event.event_id)
        assert requeued.status == OutboxStatus.PENDING
        assert requeued.retry_count == 0

    @pytest.mark.asyncio
    async def test_requeue_clears_dead_letter_fields(self, storage, dead_event):
        await storage.insert(dead_event)
        requeued = await storage.requeue_dead_letter_event(dead_event.event_id)
        assert requeued.dead_letter_at is None
        assert requeued.dead_letter_reason is None

    @pytest.mark.asyncio
    async def test_requeue_nonexistent_event_raises(self, storage):
        with pytest.raises(Exception):
            await storage.requeue_dead_letter_event("nonexistent-id")

    @pytest.mark.asyncio
    async def test_purge_dead_letter_events_removes_all_when_no_cutoff(self, storage, dead_event):
        await storage.insert(dead_event)
        count = await storage.purge_dead_letter_events()
        assert count == 1
        dlq = await storage.get_dead_letter_events()
        assert dlq == []

    @pytest.mark.asyncio
    async def test_purge_older_than_removes_only_old_events(self, storage):
        old_event = OutboxEvent(
            saga_id="s1",
            event_type="Old",
            payload={},
            status=OutboxStatus.DEAD_LETTER,
            dead_letter_at=datetime.now(UTC) - timedelta(days=10),
            dead_letter_reason="old",
        )
        new_event = OutboxEvent(
            saga_id="s2",
            event_type="New",
            payload={},
            status=OutboxStatus.DEAD_LETTER,
            dead_letter_at=datetime.now(UTC),
            dead_letter_reason="recent",
        )
        await storage.insert(old_event)
        await storage.insert(new_event)

        count = await storage.purge_dead_letter_events(older_than=timedelta(days=5))
        assert count == 1
        remaining = await storage.get_dead_letter_events()
        assert len(remaining) == 1
        assert remaining[0].event_id == new_event.event_id

    @pytest.mark.asyncio
    async def test_purge_with_no_dlq_events_returns_zero(self, storage):
        count = await storage.purge_dead_letter_events()
        assert count == 0


# ---------------------------------------------------------------------------
# Worker sets dead_letter_at / dead_letter_reason on move
# ---------------------------------------------------------------------------


class TestWorkerDLQFieldsOnMove:
    """Worker._move_to_dead_letter must populate the new DLQ fields."""

    @pytest.mark.asyncio
    async def test_move_to_dead_letter_sets_dead_letter_at(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from sagaz.outbox.worker import OutboxWorker

        storage = InMemoryOutboxStorage()
        broker = AsyncMock()
        broker.is_connected = True

        worker = OutboxWorker(storage=storage, broker=broker)

        event = OutboxEvent(
            saga_id="s1",
            event_type="Boom",
            payload={},
            retry_count=10,
            last_error="connection refused",
        )
        await storage.insert(event)

        with patch.object(worker, "_events_dead_lettered", 0):
            await worker._move_to_dead_letter(event)

        stored = await storage.get_by_id(event.event_id)
        assert stored is not None
        assert stored.status == OutboxStatus.DEAD_LETTER
        assert stored.dead_letter_at is not None
        assert stored.dead_letter_reason is not None

    @pytest.mark.asyncio
    async def test_move_to_dead_letter_reason_from_last_error(self):
        from unittest.mock import AsyncMock

        from sagaz.outbox.worker import OutboxWorker

        storage = InMemoryOutboxStorage()
        broker = AsyncMock()
        broker.is_connected = True

        worker = OutboxWorker(storage=storage, broker=broker)

        event = OutboxEvent(
            saga_id="s1",
            event_type="Boom",
            payload={},
            retry_count=10,
            last_error="upstream_timeout",
        )
        await storage.insert(event)
        await worker._move_to_dead_letter(event)

        stored = await storage.get_by_id(event.event_id)
        assert stored is not None
        assert "upstream_timeout" in (stored.dead_letter_reason or "")


# ---------------------------------------------------------------------------
# Prometheus DLQ depth gauge
# ---------------------------------------------------------------------------


class TestDLQDepthGauge:
    """sagaz_dlq_depth gauge must be defined on OutboxWorkerMetrics (or similar)."""

    def test_dlq_depth_gauge_exists_when_prometheus_available(self):
        pytest.importorskip("prometheus_client")
        import sagaz.outbox.worker as worker_mod

        # The attribute can live on the module-level class or as a module-level name
        assert hasattr(worker_mod, "OUTBOX_DLQ_DEPTH") or hasattr(worker_mod, "outbox_dlq_depth"), (
            "sagaz_dlq_depth gauge must be defined in sagaz.outbox.worker"
        )


# ---------------------------------------------------------------------------
# CLI DLQ command group
# ---------------------------------------------------------------------------


class TestCLIDLQCommands:
    """sagaz.cli.dlq must export dlq_cli group with list/replay/purge commands."""

    def test_dlq_cli_module_importable(self):
        from sagaz.cli import dlq as dlq_mod  # noqa: F401

    def test_dlq_cli_group_exported(self):
        from sagaz.cli.dlq import dlq_cli

        assert dlq_cli is not None

    def test_dlq_list_command_exists(self):
        from sagaz.cli.dlq import dlq_cli

        assert "list" in dlq_cli.commands

    def test_dlq_replay_command_exists(self):
        from sagaz.cli.dlq import dlq_cli

        assert "replay" in dlq_cli.commands

    def test_dlq_purge_command_exists(self):
        from sagaz.cli.dlq import dlq_cli

        assert "purge" in dlq_cli.commands

    def test_dlq_cli_registered_on_main_cli(self):
        from sagaz.cli.app import cli

        assert "dlq" in cli.commands


class TestCLIDLQCommandInvocations:
    """Exercise dlq list / replay / purge via Click's CliRunner."""

    @pytest.fixture(autouse=True)
    def _patch_storage(self, monkeypatch):
        """Inject a pre-populated InMemoryOutboxStorage into all CLI commands."""
        from sagaz.outbox.types import OutboxEvent, OutboxStatus
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage

        self.storage = InMemoryOutboxStorage()

        # Seed one DLQ event
        self.dlq_event = OutboxEvent(
            saga_id="s1",
            event_type="BrokenEvent",
            payload={"x": 1},
            status=OutboxStatus.DEAD_LETTER,
            dead_letter_at=datetime.now(UTC),
            dead_letter_reason="max_retries_exceeded",
        )
        import asyncio

        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.storage.insert(self.dlq_event))
        loop.close()

        import sagaz.cli.dlq as dlq_mod

        monkeypatch.setattr(dlq_mod, "_get_storage", lambda: self.storage)

    def _runner(self):
        from click.testing import CliRunner

        return CliRunner()

    def test_dlq_list_table_output(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["list"])
        assert result.exit_code == 0, result.output

    def test_dlq_list_json_output(self):
        import json

        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["list", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["dead_letter_reason"] == "max_retries_exceeded"

    def test_dlq_list_empty_queue(self, monkeypatch):
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage

        empty = InMemoryOutboxStorage()
        import sagaz.cli.dlq as dlq_mod

        monkeypatch.setattr(dlq_mod, "_get_storage", lambda: empty)

        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["list"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()

    def test_dlq_replay_single_event(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["replay", "--id", self.dlq_event.event_id])
        assert result.exit_code == 0, result.output
        assert "Re-queued" in result.output

    def test_dlq_replay_not_found(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["replay", "--id", "nonexistent"])
        assert result.exit_code != 0

    def test_dlq_replay_all(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["replay", "--all"])
        assert result.exit_code == 0, result.output
        assert "Re-queued 1" in result.output

    def test_dlq_replay_no_args_error(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["replay"])
        assert result.exit_code != 0

    def test_dlq_purge_all(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["purge", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Purged 1" in result.output

    def test_dlq_purge_with_older_duration(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        # All events are just-created, so --older 7d should purge 0
        result = runner.invoke(dlq_cli, ["purge", "--older", "7d", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Purged 0" in result.output

    def test_dlq_purge_older_hours(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["purge", "--older", "24h", "--yes"])
        assert result.exit_code == 0, result.output

    def test_dlq_purge_older_minutes(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["purge", "--older", "30m", "--yes"])
        assert result.exit_code == 0, result.output

    def test_dlq_purge_invalid_duration(self):
        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["purge", "--older", "7x", "--yes"])
        assert result.exit_code != 0

    def test_dlq_list_fallback_no_rich(self, monkeypatch):
        """Cover the else branch when rich is unavailable."""
        import sagaz.cli.dlq as dlq_mod

        monkeypatch.setattr(dlq_mod, "console", None)
        monkeypatch.setattr(dlq_mod, "Table", None)

        from sagaz.cli.dlq import dlq_cli

        runner = self._runner()
        result = runner.invoke(dlq_cli, ["list"])
        assert result.exit_code == 0, result.output
        assert "BrokenEvent" in result.output
