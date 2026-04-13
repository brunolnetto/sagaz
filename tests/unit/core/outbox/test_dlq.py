"""
Unit tests for Dead Letter Queue (DLQ) feature — ADR-038 / issue #44.

Covers:
  Phase 0 (existing) — dead_letter_at / dead_letter_reason fields, basic
    requeue/purge on InMemoryOutboxStorage, worker transition, Prometheus gauge,
    CLI commands.
  Phase 1 (ADR-038 §Phase-1) — error_type, error_classification,
    error_fingerprint on OutboxEvent; classify_error() and
    create_error_fingerprint() helpers; enhanced Prometheus labels.
  Phase 2 (ADR-038 §Phase-2) — replay_count, ReplayLoopError guard,
    DLQReplayValidator.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

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
        from sagaz.core.outbox.worker import OutboxWorker

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
        await worker._move_to_dead_letter(event)

        stored = await storage.get_by_id(event.event_id)
        assert stored is not None
        assert stored.status == OutboxStatus.DEAD_LETTER
        assert stored.dead_letter_at is not None
        assert stored.dead_letter_reason is not None

    @pytest.mark.asyncio
    async def test_move_to_dead_letter_reason_from_last_error(self):
        from sagaz.core.outbox.worker import OutboxWorker

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
        import sagaz.core.outbox.worker as worker_mod

        assert hasattr(worker_mod, "OUTBOX_DLQ_DEPTH"), (
            "sagaz_dlq_depth gauge must be defined in sagaz.core.outbox.worker"
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
        from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
        from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

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
        from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

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


# ===========================================================================
# Phase 1 — Error classification fields on OutboxEvent
# ===========================================================================


class TestOutboxEventErrorClassificationFields:
    """OutboxEvent must carry error_type, error_classification, error_fingerprint."""

    def test_error_type_defaults_to_none(self):
        event = OutboxEvent(saga_id="s1", event_type="Foo", payload={})
        assert event.error_type is None

    def test_error_classification_defaults_to_none(self):
        event = OutboxEvent(saga_id="s1", event_type="Foo", payload={})
        assert event.error_classification is None

    def test_error_fingerprint_defaults_to_none(self):
        event = OutboxEvent(saga_id="s1", event_type="Foo", payload={})
        assert event.error_fingerprint is None

    def test_error_fields_settable(self):
        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            error_type="ConnectionError",
            error_classification="TRANSIENT",
            error_fingerprint="abc123ab12345678",
        )
        assert event.error_type == "ConnectionError"
        assert event.error_classification == "TRANSIENT"
        assert event.error_fingerprint == "abc123ab12345678"

    def test_to_dict_includes_error_classification_fields(self):
        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            error_type="ValueError",
            error_classification="PERMANENT",
            error_fingerprint="deadbeef12345678",
        )
        d = event.to_dict()
        assert d["error_type"] == "ValueError"
        assert d["error_classification"] == "PERMANENT"
        assert d["error_fingerprint"] == "deadbeef12345678"

    def test_from_dict_roundtrip_preserves_error_fields(self):
        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            error_type="TimeoutError",
            error_classification="TRANSIENT",
            error_fingerprint="cafebabe12345678",
        )
        restored = OutboxEvent.from_dict(event.to_dict())
        assert restored.error_type == "TimeoutError"
        assert restored.error_classification == "TRANSIENT"
        assert restored.error_fingerprint == "cafebabe12345678"

    def test_from_dict_missing_error_fields_defaults_to_none(self):
        raw = {"saga_id": "s1", "event_type": "Foo", "payload": {}}
        event = OutboxEvent.from_dict(raw)
        assert event.error_type is None
        assert event.error_classification is None
        assert event.error_fingerprint is None


# ===========================================================================
# Phase 1 — classify_error() helper
# ===========================================================================


class TestClassifyError:
    @pytest.fixture(autouse=True)
    def _import(self):
        from sagaz.core.outbox.error_classifier import classify_error

        self.classify_error = classify_error

    def test_connection_error_is_transient(self):
        assert self.classify_error(ConnectionError("refused")) == "TRANSIENT"

    def test_timeout_error_is_transient(self):
        assert self.classify_error(TimeoutError("timed out")) == "TRANSIENT"

    def test_os_error_is_transient(self):
        assert self.classify_error(OSError("gone")) == "TRANSIENT"

    def test_value_error_is_permanent(self):
        assert self.classify_error(ValueError("bad")) == "PERMANENT"

    def test_type_error_is_permanent(self):
        assert self.classify_error(TypeError("wrong type")) == "PERMANENT"

    def test_key_error_is_permanent(self):
        assert self.classify_error(KeyError("missing")) == "PERMANENT"

    def test_assertion_error_is_permanent(self):
        assert self.classify_error(AssertionError("nope")) == "PERMANENT"

    def test_unknown_exception_is_unknown(self):
        class WeirdError(Exception):
            pass

        assert self.classify_error(WeirdError("mystery")) == "UNKNOWN"

    def test_returns_string(self):
        result = self.classify_error(RuntimeError("boom"))
        assert isinstance(result, str)


# ===========================================================================
# Phase 1 — create_error_fingerprint() helper
# ===========================================================================


class TestCreateErrorFingerprint:
    @pytest.fixture(autouse=True)
    def _import(self):
        from sagaz.core.outbox.error_classifier import create_error_fingerprint

        self.fingerprint = create_error_fingerprint

    def test_returns_non_empty_string(self):
        fp = self.fingerprint("Connection refused")
        assert isinstance(fp, str)
        assert len(fp) > 0

    def test_same_message_same_fingerprint(self):
        fp1 = self.fingerprint("Connection refused to db:5432")
        fp2 = self.fingerprint("Connection refused to db:5432")
        assert fp1 == fp2

    def test_different_numbers_same_fingerprint(self):
        fp1 = self.fingerprint("Failed after 3 retries")
        fp2 = self.fingerprint("Failed after 10 retries")
        assert fp1 == fp2

    def test_different_hosts_same_fingerprint(self):
        fp1 = self.fingerprint("Connect db1.example.com:5432 refused")
        fp2 = self.fingerprint("Connect db2.example.com:9999 refused")
        assert fp1 == fp2

    def test_structurally_different_messages_differ(self):
        fp1 = self.fingerprint("Connection refused")
        fp2 = self.fingerprint("Validation failed: missing field")
        assert fp1 != fp2

    def test_fingerprint_length_is_16(self):
        fp = self.fingerprint("any message here")
        assert len(fp) == 16


# ===========================================================================
# Phase 1 — Worker populates error classification on failure
# ===========================================================================


class TestWorkerPopulatesErrorClassification:
    @pytest.mark.asyncio
    async def test_handle_failure_sets_error_type(self):
        from sagaz.core.outbox.worker import OutboxWorker

        storage = InMemoryOutboxStorage()
        broker = AsyncMock()
        worker = OutboxWorker(storage=storage, broker=broker)

        event = OutboxEvent(saga_id="s1", event_type="E", payload={}, retry_count=0)
        await storage.insert(event)
        await worker._handle_publish_failure(event, ConnectionError("refused"))

        stored = await storage.get_by_id(event.event_id)
        assert stored is not None
        assert stored.error_type == "ConnectionError"

    @pytest.mark.asyncio
    async def test_handle_failure_sets_error_classification(self):
        from sagaz.core.outbox.worker import OutboxWorker

        storage = InMemoryOutboxStorage()
        broker = AsyncMock()
        worker = OutboxWorker(storage=storage, broker=broker)

        event = OutboxEvent(saga_id="s1", event_type="E", payload={}, retry_count=0)
        await storage.insert(event)
        await worker._handle_publish_failure(event, ConnectionError("refused"))

        stored = await storage.get_by_id(event.event_id)
        assert stored is not None
        assert stored.error_classification == "TRANSIENT"

    @pytest.mark.asyncio
    async def test_handle_failure_sets_error_fingerprint(self):
        from sagaz.core.outbox.worker import OutboxWorker

        storage = InMemoryOutboxStorage()
        broker = AsyncMock()
        worker = OutboxWorker(storage=storage, broker=broker)

        event = OutboxEvent(saga_id="s1", event_type="E", payload={}, retry_count=0)
        await storage.insert(event)
        await worker._handle_publish_failure(event, ValueError("schema mismatch"))

        stored = await storage.get_by_id(event.event_id)
        assert stored is not None
        assert stored.error_fingerprint is not None
        assert len(stored.error_fingerprint) == 16

    @pytest.mark.asyncio
    async def test_move_to_dead_letter_preserves_error_classification(self):
        from sagaz.core.outbox.worker import OutboxWorker

        storage = InMemoryOutboxStorage()
        broker = AsyncMock()
        worker = OutboxWorker(storage=storage, broker=broker)

        event = OutboxEvent(
            saga_id="s1",
            event_type="E",
            payload={},
            retry_count=10,
            last_error="schema invalid",
            error_type="ValueError",
            error_classification="PERMANENT",
            error_fingerprint="aabbccdd11223344",
        )
        await storage.insert(event)
        await worker._move_to_dead_letter(event)

        stored = await storage.get_by_id(event.event_id)
        assert stored is not None
        assert stored.error_classification == "PERMANENT"
        assert stored.error_fingerprint == "aabbccdd11223344"


# ===========================================================================
# Phase 2 — replay_count field on OutboxEvent
# ===========================================================================


class TestOutboxEventReplayCountField:
    def test_replay_count_defaults_to_zero(self):
        event = OutboxEvent(saga_id="s1", event_type="Foo", payload={})
        assert event.replay_count == 0

    def test_replay_count_settable(self):
        event = OutboxEvent(saga_id="s1", event_type="Foo", payload={}, replay_count=2)
        assert event.replay_count == 2

    def test_to_dict_includes_replay_count(self):
        event = OutboxEvent(saga_id="s1", event_type="Foo", payload={}, replay_count=3)
        assert event.to_dict()["replay_count"] == 3

    def test_from_dict_roundtrip_preserves_replay_count(self):
        event = OutboxEvent(saga_id="s1", event_type="Foo", payload={}, replay_count=2)
        restored = OutboxEvent.from_dict(event.to_dict())
        assert restored.replay_count == 2

    def test_from_dict_missing_replay_count_defaults_to_zero(self):
        raw = {"saga_id": "s1", "event_type": "Foo", "payload": {}}
        event = OutboxEvent.from_dict(raw)
        assert event.replay_count == 0


# ===========================================================================
# Phase 2 — ReplayLoopError
# ===========================================================================


class TestReplayLoopError:
    def test_replay_loop_error_importable(self):
        from sagaz.core.outbox.types import ReplayLoopError  # noqa: F401

    def test_replay_loop_error_is_outbox_error(self):
        from sagaz.core.outbox.types import OutboxError, ReplayLoopError

        assert issubclass(ReplayLoopError, OutboxError)

    def test_replay_loop_error_carries_event_id(self):
        from sagaz.core.outbox.types import ReplayLoopError

        err = ReplayLoopError(event_id="abc-123", replay_count=4, max_replays=3)
        assert err.event_id == "abc-123"
        assert err.replay_count == 4
        assert err.max_replays == 3


# ===========================================================================
# Phase 2 — requeue_dead_letter_event increments replay_count and guards loop
# ===========================================================================


class TestRequeueReplayGuard:
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
    async def test_requeue_increments_replay_count(self, storage, dead_event):
        await storage.insert(dead_event)
        requeued = await storage.requeue_dead_letter_event(dead_event.event_id)
        assert requeued.replay_count == 1

    @pytest.mark.asyncio
    async def test_requeue_second_time_increments_again(self, storage, dead_event):
        await storage.insert(dead_event)
        ev = await storage.requeue_dead_letter_event(dead_event.event_id)
        # Move back to DLQ manually
        ev.status = OutboxStatus.DEAD_LETTER
        ev.dead_letter_at = datetime.now(UTC)
        ev.dead_letter_reason = "failed again"
        requeued = await storage.requeue_dead_letter_event(dead_event.event_id)
        assert requeued.replay_count == 2

    @pytest.mark.asyncio
    async def test_requeue_raises_replay_loop_error_after_max_replays(self, storage):
        from sagaz.core.outbox.types import ReplayLoopError

        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            status=OutboxStatus.DEAD_LETTER,
            dead_letter_at=datetime.now(UTC),
            dead_letter_reason="max_retries_exceeded",
            replay_count=3,
        )
        await storage.insert(event)
        with pytest.raises(ReplayLoopError):
            await storage.requeue_dead_letter_event(event.event_id)

    @pytest.mark.asyncio
    async def test_requeue_force_bypasses_replay_loop_guard(self, storage):
        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            status=OutboxStatus.DEAD_LETTER,
            dead_letter_at=datetime.now(UTC),
            dead_letter_reason="max_retries_exceeded",
            replay_count=3,
        )
        await storage.insert(event)
        requeued = await storage.requeue_dead_letter_event(event.event_id, force=True)
        assert requeued.status == OutboxStatus.PENDING
        assert requeued.replay_count == 4

    @pytest.mark.asyncio
    async def test_default_max_replays_is_three(self, storage):
        from sagaz.core.outbox.types import ReplayLoopError

        event = OutboxEvent(
            saga_id="s1",
            event_type="Foo",
            payload={},
            status=OutboxStatus.DEAD_LETTER,
            dead_letter_at=datetime.now(UTC),
            dead_letter_reason="x",
            replay_count=2,
        )
        await storage.insert(event)
        # replay_count 2 → requeue → becomes 3 (not yet at limit)
        requeued = await storage.requeue_dead_letter_event(event.event_id)
        assert requeued.replay_count == 3

        requeued.status = OutboxStatus.DEAD_LETTER
        requeued.dead_letter_at = datetime.now(UTC)

        # replay_count 3 → next call should raise
        with pytest.raises(ReplayLoopError):
            await storage.requeue_dead_letter_event(event.event_id)


# ===========================================================================
# Phase 2 — DLQReplayValidator
# ===========================================================================


class TestDLQReplayValidator:
    @pytest.fixture(autouse=True)
    def _import(self):
        from sagaz.core.outbox.dlq_validator import DLQReplayValidator

        self.Validator = DLQReplayValidator

    def _make_dlq_event(self, **kwargs) -> OutboxEvent:
        defaults = dict(
            saga_id="s1",
            event_type="Foo",
            payload={},
            status=OutboxStatus.DEAD_LETTER,
            dead_letter_at=datetime.now(UTC),
            dead_letter_reason="max_retries_exceeded",
            replay_count=0,
        )
        defaults.update(kwargs)
        return OutboxEvent(**defaults)

    def test_can_replay_returns_true_for_fresh_event(self):
        validator = self.Validator()
        event = self._make_dlq_event()
        ok, reason = validator.can_replay(event)
        assert ok is True

    def test_can_replay_returns_false_for_permanent_error(self):
        validator = self.Validator()
        event = self._make_dlq_event(error_classification="PERMANENT")
        ok, reason = validator.can_replay(event)
        assert ok is False
        assert reason

    def test_can_replay_returns_false_when_replay_count_at_limit(self):
        validator = self.Validator(max_replays=3)
        event = self._make_dlq_event(replay_count=3)
        ok, reason = validator.can_replay(event)
        assert ok is False
        assert "replay" in reason.lower()

    def test_can_replay_returns_true_for_transient_under_limit(self):
        validator = self.Validator(max_replays=3)
        event = self._make_dlq_event(error_classification="TRANSIENT", replay_count=1)
        ok, reason = validator.can_replay(event)
        assert ok is True

    def test_can_replay_unknown_classification_is_allowed(self):
        validator = self.Validator()
        event = self._make_dlq_event(error_classification="UNKNOWN")
        ok, _ = validator.can_replay(event)
        assert ok is True

    def test_can_replay_result_is_tuple_of_bool_and_str(self):
        validator = self.Validator()
        event = self._make_dlq_event()
        result = validator.can_replay(event)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)


# ===========================================================================
# Phase 2 — OUTBOX_REPLAY_LOOP_DETECTED Prometheus counter
# ===========================================================================


class TestReplayLoopPrometheusCounter:
    def test_replay_loop_counter_exists_when_prometheus_available(self):
        pytest.importorskip("prometheus_client")
        import sagaz.core.outbox.worker as worker_mod

        assert hasattr(worker_mod, "OUTBOX_REPLAY_LOOP_DETECTED"), (
            "OUTBOX_REPLAY_LOOP_DETECTED counter must be defined in sagaz.core.outbox.worker"
        )


# ===========================================================================
# Coverage — CLI duration parsing & rich fallback
# ===========================================================================


class TestCLIDurationParsing:
    """Test _parse_duration helper in sagaz.cli.dlq."""

    def test_parse_duration_days(self):
        from sagaz.cli.dlq import _parse_duration

        dur = _parse_duration("7d")
        assert dur.days == 7

    def test_parse_duration_hours(self):
        from sagaz.cli.dlq import _parse_duration

        dur = _parse_duration("24h")
        assert dur.total_seconds() == 86400

    def test_parse_duration_minutes(self):
        from sagaz.cli.dlq import _parse_duration

        dur = _parse_duration("30m")
        assert dur.total_seconds() == 1800

    def test_parse_duration_invalid_unit(self):
        """Coverage: lines 51-53 in dlq.py (invalid duration unit error)."""
        from click.exceptions import BadParameter

        from sagaz.cli.dlq import _parse_duration

        with pytest.raises(BadParameter):
            _parse_duration("7x")

    def test_parse_duration_malformed(self):
        from click.exceptions import BadParameter

        from sagaz.cli.dlq import _parse_duration

        with pytest.raises((BadParameter, ValueError)):
            _parse_duration("xyz")


class TestCLIRichFallback:
    """Coverage: basic CLI module structure (fallback is implicit in importability)."""

    def test_cli_module_importable(self):
        """Verify CLI dlq module has rich fallback with proper attributes."""
        from sagaz.cli import dlq as dlq_mod

        # Verify module has expected attributes
        assert hasattr(dlq_mod, "console"), "dlq module should have console attribute"
        assert hasattr(dlq_mod, "Table"), "dlq module should have Table attribute"
        assert hasattr(dlq_mod, "_parse_duration"), "dlq module should have _parse_duration"
        assert hasattr(dlq_mod, "_get_storage"), "dlq module should have _get_storage"

        # Verify console is Console instance or None (depends on rich availability)
        # Either rich is imported and console is a Console object, OR it failed and is None
        from rich.console import Console
        assert isinstance(dlq_mod.console, (Console, type(None))), \
            "console should be either a Console instance or None"
        assert dlq_mod.Table is None or hasattr(dlq_mod.Table, "__mro__"), \
            "Table should be None or a class"

    def test_get_storage_returns_in_memory_storage(self):
        """Test: _get_storage() returns InMemoryOutboxStorage instance."""
        from sagaz.cli.dlq import _get_storage
        from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

        storage = _get_storage()
        assert isinstance(storage, InMemoryOutboxStorage)


# ===========================================================================
# Coverage — OutboxStorage base class NotImplementedError
# ===========================================================================


class TestOutboxStorageBaseClassNotImplemented:
    """Coverage: lines 370, 388 in storage/interfaces/outbox.py."""

    @pytest.mark.asyncio
    async def test_base_requeue_raises_not_implemented(self):
        """Create a concrete subclass that doesn't override the DLQ methods."""
        from sagaz.core.storage.interfaces.outbox import OutboxStorage

        class MinimalStorage(OutboxStorage):
            """Implements all abstract methods except DLQ ones."""

            async def insert(self, event: OutboxEvent) -> OutboxEvent:
                return event

            async def get_by_id(self, event_id: str) -> OutboxEvent | None:
                return None

            async def get_events_by_saga(self, saga_id: str):
                return []

            async def claim_batch(self, worker_id: str, batch_size: int):
                return []

            async def update_status(self, event_id: str, status, error_message: str | None = None):
                return None

            async def get_pending_count(self) -> int:
                return 0

            async def release_stuck_events(self, claimed_older_than_seconds: float) -> int:
                return 0

            async def get_stuck_events(self, older_than_seconds: float):
                return []

            async def get_dead_letter_events(self):
                return []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        storage = MinimalStorage()
        with pytest.raises(NotImplementedError):
            await storage.requeue_dead_letter_event("event-id")

    @pytest.mark.asyncio
    async def test_base_purge_raises_not_implemented(self):
        """Test that base purge_dead_letter_events raises NotImplementedError."""
        from sagaz.core.storage.interfaces.outbox import OutboxStorage

        class MinimalStorage(OutboxStorage):
            async def insert(self, event: OutboxEvent) -> OutboxEvent:
                return event

            async def get_by_id(self, event_id: str) -> OutboxEvent | None:
                return None

            async def get_events_by_saga(self, saga_id: str):
                return []

            async def claim_batch(self, worker_id: str, batch_size: int):
                return []

            async def update_status(self, event_id: str, status, error_message: str | None = None):
                return None

            async def get_pending_count(self) -> int:
                return 0

            async def release_stuck_events(self, claimed_older_than_seconds: float) -> int:
                return 0

            async def get_stuck_events(self, older_than_seconds: float):
                return []

            async def get_dead_letter_events(self):
                return []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        storage = MinimalStorage()
        with pytest.raises(NotImplementedError):
            await storage.purge_dead_letter_events()


# ===========================================================================
# Coverage — InMemoryOutboxStorage edge cases
# ===========================================================================


class TestInMemoryOutboxStoragePurgeEdgeCases:
    """Coverage: line 245 in backends/memory/outbox.py (skip non-DEAD_LETTER events)."""

    @pytest.mark.asyncio
    async def test_purge_skips_non_dead_letter_events(self):
        """Purge should skip events that are not in DEAD_LETTER status."""
        from sagaz.core.outbox.types import OutboxStatus

        storage = InMemoryOutboxStorage()

        # Create an event in PENDING status (not DEAD_LETTER)
        event = OutboxEvent(
            saga_id="s1",
            event_type="Regular",
            payload={},
            status=OutboxStatus.PENDING,
        )
        await storage.insert(event)

        # Purge without time cutoff
        count = await storage.purge_dead_letter_events()  # No older_than filter
        assert count == 0  # Event not purged (not in DEAD_LETTER status)

        # Verify it's still there
        result = await storage.get_by_id(event.event_id)
        assert result is not None
        assert result.event_id == event.event_id
