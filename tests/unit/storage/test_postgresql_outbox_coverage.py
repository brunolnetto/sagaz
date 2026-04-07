"""
Tests covering missing lines in sagaz/storage/backends/postgresql/outbox.py.

Missing lines: 32-33, 141-142, 163->exit, 170, 172-173, 209-210, 220-221,
              266-293, 298-299, 304-305, 310-311, 322-323, 337-338, 359-360,
              381-382, 394-407, 414-435, 440->443, 444->447, 568-586
"""

import importlib
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.outbox.types import OutboxEvent, OutboxStatus
from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
from sagaz.storage.interfaces.outbox import OutboxStorageError

# ==========================================================================
# Helpers
# ==========================================================================


def _make_mock_row(
    event_id="evt-001",
    saga_id="saga-001",
    event_type="TestEvent",
    payload=None,
    headers=None,
    status="pending",
):
    """Return a dict-like mock that supports row['field'] access."""
    return {
        "event_id": event_id,
        "saga_id": saga_id,
        "aggregate_type": "saga",
        "aggregate_id": saga_id,
        "event_type": event_type,
        "payload": payload if payload is not None else {"data": "value"},
        "headers": headers if headers is not None else {},
        "status": status,
        "created_at": datetime.now(UTC),
        "claimed_at": None,
        "sent_at": None,
        "retry_count": 0,
        "last_error": None,
        "worker_id": None,
    }


def _make_pool_with_conn(mock_conn):
    """Wire up a pool whose acquire() context manager yields mock_conn.

    The pool must NOT have 'execute' or 'fetchrow' attributes so that
    hasattr(conn, 'execute') / hasattr(conn, 'fetchrow') returns False,
    correctly triggering the pool path in insert/update_status.
    """
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    # Use spec to prevent MagicMock auto-creating 'execute'/'fetchrow'
    class _PoolSpec:
        def acquire(self): ...
        async def close(self): ...

    mock_pool = MagicMock(spec=_PoolSpec)
    mock_pool.acquire = MagicMock(return_value=mock_ctx)
    mock_pool.close = AsyncMock()
    return mock_pool


def _make_transaction_ctx():
    """Return a mock async context manager for conn.transaction()."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=None)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _uninitialized_storage():
    return PostgreSQLOutboxStorage("postgresql://localhost/test")


class AsyncIterableMock:
    """Async iterable that yields rows from a list."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


# ==========================================================================
# Lines 32-33, 141-142: asyncpg ImportError fallback
# ==========================================================================


class TestAsyncpgImportErrorFallback:
    """Lines 32-33, 141-142: cover the asyncpg unavailable path."""

    def test_import_without_asyncpg_sets_flag_false(self):
        """Lines 32-33: ASYNCPG_AVAILABLE=False / asyncpg=None path."""
        import sagaz.storage.backends.postgresql as pg_pkg
        import sagaz.storage.backends.postgresql.outbox as outbox_mod

        original_asyncpg = sys.modules.get("asyncpg")
        try:
            sys.modules["asyncpg"] = None  # type: ignore[assignment]
            importlib.reload(outbox_mod)
            assert outbox_mod.ASYNCPG_AVAILABLE is False
            assert outbox_mod.asyncpg is None
        finally:
            if original_asyncpg is not None:
                sys.modules["asyncpg"] = original_asyncpg
            else:
                sys.modules.pop("asyncpg", None)
            # Reload outbox and then the parent package to restore class identity
            importlib.reload(outbox_mod)
            importlib.reload(pg_pkg)

    def test_constructor_raises_when_asyncpg_unavailable(self):
        """Lines 141-142: MissingDependencyError raised when asyncpg not available."""
        import sagaz.storage.backends.postgresql.outbox as mod

        original_flag = mod.ASYNCPG_AVAILABLE
        try:
            mod.ASYNCPG_AVAILABLE = False
            from sagaz.core.exceptions import MissingDependencyError

            with pytest.raises(MissingDependencyError):
                PostgreSQLOutboxStorage("postgresql://localhost/test")
        finally:
            mod.ASYNCPG_AVAILABLE = original_flag


# ==========================================================================
# Lines 163->exit: close() when _pool is None
# ==========================================================================


class TestClose:
    """Line 163: close() is a no-op when _pool is already None."""

    async def test_close_no_pool(self):
        """Lines 163->exit: close() does nothing when pool is None."""
        storage = _uninitialized_storage()
        # No error, no-op
        await storage.close()

    async def test_close_with_pool(self):
        """Line 163 True branch: close() actually closes the pool."""
        storage = _uninitialized_storage()
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        storage._pool = mock_pool

        await storage.close()

        mock_pool.close.assert_awaited_once()
        assert storage._pool is None


# ==========================================================================
# Lines 170, 172-173: _get_connection() paths
# ==========================================================================


class TestGetConnection:
    """Lines 170, 172-173: _get_connection branches."""

    def test_get_connection_returns_provided_connection(self):
        """Line 170: _get_connection returns the passed-in connection directly."""
        storage = _uninitialized_storage()
        mock_conn = MagicMock()
        result = storage._get_connection(mock_conn)
        assert result is mock_conn

    def test_get_connection_raises_when_pool_not_initialized(self):
        """Lines 172-173: OutboxStorageError when no pool and no connection."""
        storage = _uninitialized_storage()
        # _pool is None and no connection provided
        with pytest.raises(OutboxStorageError, match="not initialized"):
            storage._get_connection(None)

    def test_get_connection_returns_pool_when_initialized(self):
        """Line 174: _get_connection returns pool when no connection given."""
        storage = _uninitialized_storage()
        storage._pool = MagicMock()
        result = storage._get_connection(None)
        assert result is storage._pool


# ==========================================================================
# Lines 209-210: insert() via pool (not direct connection)
# ==========================================================================


class TestInsertViaPool:
    """Lines 209-210: insert uses pool.acquire() when no direct connection."""

    async def test_insert_via_pool(self):
        """Lines 209-210: insert via pool path."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        # No 'execute' attribute on pool itself → conn.acquire() path
        mock_pool = _make_pool_with_conn(mock_conn)
        storage._pool = mock_pool

        event = OutboxEvent(
            saga_id="saga-pool-1",
            event_type="PaymentEvent",
            payload={"amount": 100},
        )

        result = await storage.insert(event)  # no connection argument
        assert result is event

    async def test_insert_via_direct_connection(self):
        """Line 208: insert via direct connection path."""
        storage = _uninitialized_storage()
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()

        # A direct conn has 'execute' attribute
        event = OutboxEvent(
            saga_id="saga-direct-1",
            event_type="OrderEvent",
            payload={},
        )
        result = await storage.insert(event, connection=mock_conn)
        assert result is event


# ==========================================================================
# Lines 220-221: claim_batch() when pool not initialized
# ==========================================================================


class TestClaimBatch:
    """Lines 220-221: claim_batch pool not initialized."""

    async def test_claim_batch_not_initialized(self):
        """Lines 220-221: OutboxStorageError when pool is None."""
        storage = _uninitialized_storage()
        with pytest.raises(OutboxStorageError, match="not initialized"):
            await storage.claim_batch("worker-1")

    async def test_claim_batch_success(self):
        """Line 223+: claim_batch with mocked pool."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(status="claimed")
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[mock_row])
        storage._pool = _make_pool_with_conn(mock_conn)

        events = await storage.claim_batch("worker-1", batch_size=10)

        assert len(events) == 1
        assert events[0].event_type == "TestEvent"


# ==========================================================================
# Lines 266-293: update_status() FAILED / PENDING / else branches
# Lines 298-299: event not found error
# Lines 304-305: update_status() via pool
# ==========================================================================


class TestUpdateStatus:
    """Lines 266-305: update_status branches and pool path."""

    async def test_update_status_failed(self):
        """Lines 266-275: FAILED status branch."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(status="failed")
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)

        result = await storage.update_status(
            "evt-001",
            OutboxStatus.FAILED,
            error_message="broker down",
            connection=mock_conn,
        )
        assert result.status == OutboxStatus.FAILED

    async def test_update_status_pending(self):
        """Lines 276-285: PENDING status branch."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(status="pending")
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)

        result = await storage.update_status(
            "evt-001",
            OutboxStatus.PENDING,
            connection=mock_conn,
        )
        assert result.status == OutboxStatus.PENDING

    async def test_update_status_other(self):
        """Lines 286-293: else branch (e.g., DEAD_LETTER)."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(status="dead_letter")
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)

        result = await storage.update_status(
            "evt-001",
            OutboxStatus.DEAD_LETTER,
            connection=mock_conn,
        )
        assert result.status == OutboxStatus.DEAD_LETTER

    async def test_update_status_event_not_found(self):
        """Lines 298-299: OutboxStorageError when fetchrow returns None."""
        storage = _uninitialized_storage()
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        with pytest.raises(OutboxStorageError, match="not found"):
            await storage.update_status(
                "unknown-evt",
                OutboxStatus.SENT,
                connection=mock_conn,
            )

    async def test_update_status_via_pool(self):
        """Lines 304-305: update_status via pool (conn.acquire())."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(status="sent")
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)
        storage._pool = _make_pool_with_conn(mock_conn)

        result = await storage.update_status("evt-001", OutboxStatus.SENT)
        assert result.status == OutboxStatus.SENT


# ==========================================================================
# Lines 310-311: get_by_id() pool not initialized
# ==========================================================================


class TestGetById:
    """Lines 310-311: get_by_id pool not initialized and success path."""

    async def test_get_by_id_not_initialized(self):
        """Lines 310-311: OutboxStorageError when pool is None."""
        storage = _uninitialized_storage()
        with pytest.raises(OutboxStorageError, match="not initialized"):
            await storage.get_by_id("some-event-id")

    async def test_get_by_id_found(self):
        """Line 315+: get_by_id returns event when found."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)
        storage._pool = _make_pool_with_conn(mock_conn)

        result = await storage.get_by_id("evt-001")
        assert result is not None
        assert result.event_id == "evt-001"

    async def test_get_by_id_not_found(self):
        """Line 316+: get_by_id returns None when not found."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        storage._pool = _make_pool_with_conn(mock_conn)

        result = await storage.get_by_id("missing-evt")
        assert result is None


# ==========================================================================
# Lines 322-323: get_events_by_saga() pool not initialized
# ==========================================================================


class TestGetEventsBySaga:
    """Lines 322-323: get_events_by_saga not initialized."""

    async def test_not_initialized(self):
        """Lines 322-323: raises OutboxStorageError."""
        storage = _uninitialized_storage()
        with pytest.raises(OutboxStorageError, match="not initialized"):
            await storage.get_events_by_saga("saga-1")

    async def test_success(self):
        """Line 325+: returns list of events."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(saga_id="saga-1")
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[mock_row])
        storage._pool = _make_pool_with_conn(mock_conn)

        results = await storage.get_events_by_saga("saga-1")
        assert len(results) == 1


# ==========================================================================
# Lines 337-338: get_stuck_events() pool not initialized
# ==========================================================================


class TestGetStuckEvents:
    """Lines 337-338: get_stuck_events not initialized."""

    async def test_not_initialized(self):
        """Lines 337-338: raises OutboxStorageError."""
        storage = _uninitialized_storage()
        with pytest.raises(OutboxStorageError, match="not initialized"):
            await storage.get_stuck_events()

    async def test_success(self):
        """Line 340+: returns stuck events."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(status="claimed")
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[mock_row])
        storage._pool = _make_pool_with_conn(mock_conn)

        results = await storage.get_stuck_events(claimed_older_than_seconds=60.0)
        assert len(results) == 1


# ==========================================================================
# Lines 359-360: release_stuck_events() pool not initialized
# ==========================================================================


class TestReleaseStuckEvents:
    """Lines 359-360: release_stuck_events not initialized."""

    async def test_not_initialized(self):
        """Lines 359-360: raises OutboxStorageError."""
        storage = _uninitialized_storage()
        with pytest.raises(OutboxStorageError, match="not initialized"):
            await storage.release_stuck_events()

    async def test_success(self):
        """Line 362+: release_stuck_events returns count."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 3")
        storage._pool = _make_pool_with_conn(mock_conn)

        count = await storage.release_stuck_events(claimed_older_than_seconds=300.0)
        assert count == 3


# ==========================================================================
# Lines 381-382: get_pending_count() pool not initialized
# ==========================================================================


class TestGetPendingCount:
    """Lines 381-382: get_pending_count not initialized."""

    async def test_not_initialized(self):
        """Lines 381-382: raises OutboxStorageError."""
        storage = _uninitialized_storage()
        with pytest.raises(OutboxStorageError, match="not initialized"):
            await storage.get_pending_count()

    async def test_success(self):
        """Line 384+: returns pending count."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=7)
        storage._pool = _make_pool_with_conn(mock_conn)

        count = await storage.get_pending_count()
        assert count == 7


# ==========================================================================
# Lines 394-407: get_dead_letter_events() pool not initialized + body
# ==========================================================================


class TestGetDeadLetterEvents:
    """Lines 394-407: get_dead_letter_events."""

    async def test_not_initialized(self):
        """Lines 394-396: raises OutboxStorageError."""
        storage = _uninitialized_storage()
        with pytest.raises(OutboxStorageError, match="not initialized"):
            await storage.get_dead_letter_events()

    async def test_success(self):
        """Lines 397-407: returns dead letter events."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(status="dead_letter")
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[mock_row])
        storage._pool = _make_pool_with_conn(mock_conn)

        results = await storage.get_dead_letter_events(limit=50)
        assert len(results) == 1
        assert results[0].status == OutboxStatus.DEAD_LETTER


# ==========================================================================
# Lines 414-435: archive_sent_events() pool not initialized + body
# ==========================================================================


class TestArchiveSentEvents:
    """Lines 414-435: archive_sent_events."""

    async def test_not_initialized(self):
        """Lines 414-416: raises OutboxStorageError."""
        storage = _uninitialized_storage()
        with pytest.raises(OutboxStorageError, match="not initialized"):
            await storage.archive_sent_events()

    async def test_success(self):
        """Lines 417-435: archive executes two SQL statements."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        # First execute → INSERT (no meaningful return), second → DELETE N
        mock_conn.execute = AsyncMock(side_effect=["INSERT 5", "DELETE 5"])
        mock_conn.transaction = MagicMock(return_value=_make_transaction_ctx())
        storage._pool = _make_pool_with_conn(mock_conn)

        count = await storage.archive_sent_events(older_than_days=7)
        assert count == 5


# ==========================================================================
# Lines 440->443, 444->447: _row_to_event() payload/headers as JSON strings
# ==========================================================================


class TestRowToEventJsonParsing:
    """Lines 440->443, 444->447: test payload/headers as JSON strings."""

    def test_payload_as_json_string(self):
        """Line 440->443: payload is a JSON string → parsed to dict."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(payload='{"key": "value"}')

        event = storage._row_to_event(mock_row)
        assert event.payload == {"key": "value"}

    def test_headers_as_json_string(self):
        """Line 444->447: headers is a JSON string → parsed to dict."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(headers='{"x-trace": "abc"}')

        event = storage._row_to_event(mock_row)
        assert event.headers == {"x-trace": "abc"}

    def test_payload_and_headers_already_dict(self):
        """Lines 440->443, 444->447 False branches: already dicts."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row(
            payload={"already": "parsed"},
            headers={"already": "headers"},
        )

        event = storage._row_to_event(mock_row)
        assert event.payload == {"already": "parsed"}
        assert event.headers == {"already": "headers"}


# ==========================================================================
# Lines 568-586: export_all() body
# ==========================================================================


class TestExportAll:
    """Lines 568-586: export_all async generator body."""

    async def test_export_all_not_initialized(self):
        """Lines 564-566: raises OutboxStorageError when pool is None."""
        storage = _uninitialized_storage()
        with pytest.raises(OutboxStorageError, match="not initialized"):
            async for _ in storage.export_all():
                pass

    async def test_export_all_yields_rows(self):
        """Lines 568-583: export_all yields event dicts."""
        storage = _uninitialized_storage()
        mock_row = _make_mock_row()
        mock_cursor = AsyncIterableMock([mock_row])

        mock_conn = AsyncMock()
        mock_conn.cursor = AsyncMock(return_value=mock_cursor)
        mock_conn.transaction = MagicMock(return_value=_make_transaction_ctx())
        storage._pool = _make_pool_with_conn(mock_conn)

        results = []
        async for item in storage.export_all():
            results.append(item)

        assert len(results) == 1
        assert results[0]["event_id"] == "evt-001"
        assert results[0]["event_type"] == "TestEvent"

    async def test_export_all_with_null_created_at(self):
        """Line 580-582: None created_at → None in output."""
        storage = _uninitialized_storage()
        row = _make_mock_row()
        row["created_at"] = None  # override created_at to None
        mock_cursor = AsyncIterableMock([row])

        mock_conn = AsyncMock()
        mock_conn.cursor = AsyncMock(return_value=mock_cursor)
        mock_conn.transaction = MagicMock(return_value=_make_transaction_ctx())
        storage._pool = _make_pool_with_conn(mock_conn)

        results = []
        async for item in storage.export_all():
            results.append(item)

        assert results[0]["created_at"] is None

    async def test_export_all_exception_reraises(self):
        """Lines 584-586: exception during iteration is re-raised."""
        storage = _uninitialized_storage()

        class ErrorCursor:
            def __aiter__(self):
                return self

            async def __anext__(self):
                msg = "cursor exploded"
                raise RuntimeError(msg)

        mock_conn = AsyncMock()
        mock_conn.cursor = AsyncMock(return_value=ErrorCursor())
        mock_conn.transaction = MagicMock(return_value=_make_transaction_ctx())
        storage._pool = _make_pool_with_conn(mock_conn)

        with pytest.raises(RuntimeError, match="cursor exploded"):
            async for _ in storage.export_all():
                pass


# ==========================================================================
# Consumer Inbox Methods (check_and_insert_inbox, update_inbox_duration,
# cleanup_inbox) - Lines around 465-586
# ==========================================================================


class TestConsumerInboxMethods:
    """Lines 465-510: Consumer inbox operations."""

    async def test_check_and_insert_inbox_new_event(self):
        """check_and_insert_inbox returns False for new event."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()  # no exception → new event

        result = await storage.check_and_insert_inbox(
            event_id="evt-new",
            consumer_name="payment-svc",
            source_topic="payments",
            event_type="PaymentEvent",
            payload={"amount": 50},
            connection=mock_conn,
        )
        assert result is False

    async def test_check_and_insert_inbox_duplicate(self):
        """check_and_insert_inbox returns True for duplicate event."""
        import asyncpg

        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        # Simulate UniqueViolationError for duplicate
        mock_conn.execute = AsyncMock(side_effect=asyncpg.UniqueViolationError("duplicate"))

        result = await storage.check_and_insert_inbox(
            event_id="evt-dup",
            consumer_name="payment-svc",
            source_topic="payments",
            event_type="PaymentEvent",
            payload={"amount": 50},
            connection=mock_conn,
        )
        assert result is True

    async def test_check_and_insert_inbox_via_pool(self):
        """check_and_insert_inbox uses pool when no connection provided."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.transaction = MagicMock(return_value=_make_transaction_ctx())
        storage._pool = _make_pool_with_conn(mock_conn)

        result = await storage.check_and_insert_inbox(
            event_id="evt-pool",
            consumer_name="order-svc",
            source_topic="orders",
            event_type="OrderEvent",
            payload={},
        )
        assert result is False

    async def test_update_inbox_duration(self):
        """update_inbox_duration executes UPDATE."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        storage._pool = _make_pool_with_conn(mock_conn)

        await storage.update_inbox_duration("evt-001", duration_ms=42)
        mock_conn.execute.assert_awaited_once()

    async def test_cleanup_inbox_success(self):
        """cleanup_inbox returns count from DELETE result."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 3")
        storage._pool = _make_pool_with_conn(mock_conn)

        count = await storage.cleanup_inbox("order-svc", older_than_days=30)
        assert count == 3

    async def test_cleanup_inbox_zero_deleted(self):
        """cleanup_inbox returns 0 when result doesn't start with DELETE."""
        storage = _uninitialized_storage()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")
        storage._pool = _make_pool_with_conn(mock_conn)

        count = await storage.cleanup_inbox("order-svc", older_than_days=30)
        assert count == 0
