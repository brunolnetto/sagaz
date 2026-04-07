"""
Unit tests for sagaz.storage.migration — SagaStorageMigrator facade.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.storage.migration import MigrationResult, SagaStorageMigrator, VerificationResult

_TRANSFER_DATA_PATH = "sagaz.storage.migration.transfer_data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_manager(saga_total: int = 5, event_count: int = 3) -> MagicMock:
    """Return a minimal StorageManager mock."""
    stats = MagicMock()
    stats.total_records = saga_total

    saga = MagicMock()
    saga.get_statistics = AsyncMock(return_value=stats)

    outbox = MagicMock()
    outbox.count = AsyncMock(return_value=event_count)

    manager = MagicMock()
    manager.saga = saga
    manager.outbox = outbox
    return manager


def _transfer_result(transferred: int = 5, failed: int = 0) -> MagicMock:
    r = MagicMock()
    r.transferred = transferred
    r.failed = failed
    return r


# ---------------------------------------------------------------------------
# MigrationResult
# ---------------------------------------------------------------------------


class TestMigrationResult:
    def test_success_when_no_failures(self):
        r = MigrationResult(sagas_transferred=5, events_transferred=3)
        assert r.success is True

    def test_failure_when_saga_fails(self):
        r = MigrationResult(sagas_transferred=4, sagas_failed=1)
        assert r.success is False

    def test_failure_when_event_fails(self):
        r = MigrationResult(events_transferred=2, events_failed=1)
        assert r.success is False

    def test_dry_run_flag_defaults_false(self):
        r = MigrationResult()
        assert r.dry_run is False
        assert r.sagas_transferred == 0

    def test_dry_run_flag_true(self):
        r = MigrationResult(dry_run=True)
        assert r.dry_run is True

    def test_to_dict_keys(self):
        r = MigrationResult(sagas_transferred=2, events_transferred=1)
        d = r.to_dict()
        assert set(d.keys()) == {
            "sagas_transferred",
            "sagas_failed",
            "events_transferred",
            "events_failed",
            "dry_run",
            "success",
        }


# ---------------------------------------------------------------------------
# VerificationResult
# ---------------------------------------------------------------------------


class TestVerificationResult:
    def test_ok_when_counts_match(self):
        vr = VerificationResult(source_sagas=10, dest_sagas=10, source_events=5, dest_events=5)
        assert vr.ok is True

    def test_not_ok_when_sagas_differ(self):
        vr = VerificationResult(source_sagas=10, dest_sagas=9, source_events=5, dest_events=5)
        assert vr.sagas_match is False
        assert vr.ok is False

    def test_not_ok_when_events_differ(self):
        vr = VerificationResult(source_sagas=5, dest_sagas=5, source_events=3, dest_events=2)
        assert vr.events_match is False
        assert vr.ok is False

    def test_to_dict_keys(self):
        vr = VerificationResult()
        keys = vr.to_dict().keys()
        assert "sagas_match" in keys
        assert "events_match" in keys
        assert "ok" in keys


# ---------------------------------------------------------------------------
# SagaStorageMigrator.migrate
# ---------------------------------------------------------------------------


class TestSagaStorageMigratorMigrate:
    @pytest.mark.asyncio
    async def test_dry_run_returns_zero_counts_and_skips_transfer(self):
        source = _mock_manager()
        dest = _mock_manager()
        migrator = SagaStorageMigrator(source, dest)

        with patch(_TRANSFER_DATA_PATH) as mock_td:
            result = await migrator.migrate(dry_run=True)

        assert result.dry_run is True
        assert result.sagas_transferred == 0
        assert result.events_transferred == 0
        mock_td.assert_not_called()

    @pytest.mark.asyncio
    async def test_transfers_sagas_and_events(self):
        source = _mock_manager()
        dest = _mock_manager()
        migrator = SagaStorageMigrator(source, dest)

        saga_r = _transfer_result(transferred=5)
        event_r = _transfer_result(transferred=3)

        with patch(_TRANSFER_DATA_PATH, new=AsyncMock(side_effect=[saga_r, event_r])):
            result = await migrator.migrate(dry_run=False)

        assert result.sagas_transferred == 5
        assert result.events_transferred == 3
        assert result.sagas_failed == 0
        assert result.success is True

    @pytest.mark.asyncio
    async def test_failure_counts_propagated(self):
        source = _mock_manager()
        dest = _mock_manager()
        migrator = SagaStorageMigrator(source, dest)

        saga_r = _transfer_result(transferred=4, failed=1)
        event_r = _transfer_result(transferred=3)

        with patch(_TRANSFER_DATA_PATH, new=AsyncMock(side_effect=[saga_r, event_r])):
            result = await migrator.migrate()

        assert result.sagas_failed == 1
        assert result.success is False

    @pytest.mark.asyncio
    async def test_transfer_data_called_twice_once_per_store(self):
        source = _mock_manager()
        dest = _mock_manager()
        migrator = SagaStorageMigrator(source, dest)
        ok = _transfer_result()

        with patch(_TRANSFER_DATA_PATH, new=AsyncMock(return_value=ok)) as mock_td:
            await migrator.migrate()

        assert mock_td.call_count == 2

    @pytest.mark.asyncio
    async def test_batch_size_forwarded(self):
        source = _mock_manager()
        dest = _mock_manager()
        migrator = SagaStorageMigrator(source, dest)
        ok = _transfer_result()

        with patch(_TRANSFER_DATA_PATH, new=AsyncMock(return_value=ok)) as mock_td:
            await migrator.migrate(batch_size=250)

        for call in mock_td.call_args_list:
            assert call.kwargs.get("batch_size") == 250

    @pytest.mark.asyncio
    async def test_on_error_forwarded(self):
        source = _mock_manager()
        dest = _mock_manager()
        migrator = SagaStorageMigrator(source, dest)
        ok = _transfer_result()

        with patch(_TRANSFER_DATA_PATH, new=AsyncMock(return_value=ok)) as mock_td:
            await migrator.migrate(on_error="abort")

        for call in mock_td.call_args_list:
            assert call.kwargs.get("on_error") == "abort"


# ---------------------------------------------------------------------------
# SagaStorageMigrator.verify
# ---------------------------------------------------------------------------


class TestSagaStorageMigratorVerify:
    @pytest.mark.asyncio
    async def test_ok_when_counts_match(self):
        source = _mock_manager(saga_total=7, event_count=4)
        dest = _mock_manager(saga_total=7, event_count=4)
        migrator = SagaStorageMigrator(source, dest)

        vr = await migrator.verify()
        assert vr.ok is True
        assert vr.source_sagas == 7
        assert vr.dest_sagas == 7

    @pytest.mark.asyncio
    async def test_not_ok_when_counts_differ(self):
        source = _mock_manager(saga_total=7, event_count=4)
        dest = _mock_manager(saga_total=6, event_count=4)
        migrator = SagaStorageMigrator(source, dest)

        vr = await migrator.verify()
        assert vr.sagas_match is False
        assert vr.ok is False

    @pytest.mark.asyncio
    async def test_saga_stats_error_returns_minus_one(self):
        source = _mock_manager()
        dest = _mock_manager()
        source.saga.get_statistics = AsyncMock(side_effect=RuntimeError("unavailable"))
        dest.saga.get_statistics = AsyncMock(side_effect=RuntimeError("unavailable"))
        migrator = SagaStorageMigrator(source, dest)

        vr = await migrator.verify()
        assert vr.source_sagas == -1
        assert vr.dest_sagas == -1

    @pytest.mark.asyncio
    async def test_event_count_error_returns_minus_one(self):
        source = _mock_manager()
        dest = _mock_manager()
        source.outbox.count = AsyncMock(side_effect=RuntimeError("db down"))
        dest.outbox.count = AsyncMock(side_effect=RuntimeError("db down"))
        migrator = SagaStorageMigrator(source, dest)

        vr = await migrator.verify()
        assert vr.source_events == -1
        assert vr.dest_events == -1
