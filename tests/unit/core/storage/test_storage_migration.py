"""
Unit tests for sagaz.storage.migration — SagaStorageMigrator facade.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.storage.migration import MigrationResult, SagaStorageMigrator, VerificationResult

_TRANSFER_DATA_PATH = "sagaz.core.storage.migration.transfer_data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _async_records(records):
    async def _iterate():
        for record in records:
            yield record

    return _iterate()


def _mock_manager(saga_total: int = 5, event_count: int = 3) -> MagicMock:
    """Return a StorageManager mock with deterministic export streams."""
    stats = MagicMock()
    stats.total_records = saga_total

    saga = MagicMock()
    saga.get_statistics = AsyncMock(return_value=stats)
    saga.export_all = MagicMock(
        return_value=_async_records(
            [
                {"saga_id": f"saga-{index}", "status": "completed", "context": {"index": index}}
                for index in range(saga_total)
            ]
        )
    )

    outbox = MagicMock()
    outbox.count = AsyncMock(return_value=event_count)
    outbox.export_all = MagicMock(
        return_value=_async_records(
            [
                {
                    "event_id": f"event-{index}",
                    "saga_id": f"saga-{index}",
                    "event_type": "Created",
                    "payload": {"index": index},
                }
                for index in range(event_count)
            ]
        )
    )

    manager = MagicMock()
    manager.saga = saga
    manager.outbox = outbox
    return manager


def _transfer_result(transferred: int = 5, failed: int = 0, skipped: int = 0) -> MagicMock:
    r = MagicMock()
    r.transferred = transferred
    r.failed = failed
    r.skipped = skipped
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
            "sagas_skipped",
            "events_transferred",
            "events_failed",
            "events_skipped",
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

    def test_not_ok_when_saga_checksums_differ(self):
        vr = VerificationResult(
            source_sagas=10,
            dest_sagas=10,
            source_events=5,
            dest_events=5,
            source_saga_checksum="source-checksum",
            dest_saga_checksum="different-checksum",
        )
        assert vr.sagas_match is True
        assert vr.saga_checksums_match is False
        assert vr.ok is False

    def test_not_ok_when_event_checksums_differ(self):
        vr = VerificationResult(
            source_sagas=10,
            dest_sagas=10,
            source_events=5,
            dest_events=5,
            source_event_checksum="source-checksum",
            dest_event_checksum="different-checksum",
        )
        assert vr.events_match is True
        assert vr.event_checksums_match is False
        assert vr.ok is False

    def test_not_ok_when_one_side_checksum_is_unavailable(self):
        vr = VerificationResult(
            source_sagas=10,
            dest_sagas=10,
            source_events=5,
            dest_events=5,
            source_event_checksum="available",
        )
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
    async def test_saga_export_error_returns_minus_one(self):
        source = _mock_manager()
        dest = _mock_manager()
        source.saga.export_all = MagicMock(side_effect=RuntimeError("unavailable"))
        dest.saga.export_all = MagicMock(side_effect=RuntimeError("unavailable"))
        migrator = SagaStorageMigrator(source, dest)

        vr = await migrator.verify()
        assert vr.source_sagas == -1
        assert vr.dest_sagas == -1
        assert vr.ok is False

    @pytest.mark.asyncio
    async def test_event_export_error_returns_minus_one(self):
        source = _mock_manager()
        dest = _mock_manager()
        source.outbox.export_all = MagicMock(side_effect=RuntimeError("db down"))
        dest.outbox.export_all = MagicMock(side_effect=RuntimeError("db down"))
        migrator = SagaStorageMigrator(source, dest)

        vr = await migrator.verify()
        assert vr.source_events == -1
        assert vr.dest_events == -1
        assert vr.ok is False

    @pytest.mark.asyncio
    async def test_skipped_records_are_counted_as_failures(self):
        source = _mock_manager()
        dest = _mock_manager()
        migrator = SagaStorageMigrator(source, dest)

        saga_r = _transfer_result(transferred=4, failed=0, skipped=2)
        event_r = _transfer_result(transferred=3, failed=0, skipped=1)

        with patch(_TRANSFER_DATA_PATH, new=AsyncMock(side_effect=[saga_r, event_r])):
            result = await migrator.migrate()

        assert result.sagas_failed == 0
        assert result.sagas_skipped == 2
        assert result.events_failed == 0
        assert result.events_skipped == 1
        assert result.success is False


class TestCanonicalChecksumValue:
    """Characterize deterministic normalization used by storage checksums."""

    def test_object_with_to_dict_is_recursively_normalized(self):
        from sagaz.core.storage.migration import _canonical_checksum_value

        class Record:
            def to_dict(self):
                return {"payload": (1, 2), "name": "example"}

        assert _canonical_checksum_value(Record()) == {
            "payload": [1, 2],
            "name": "example",
        }

    def test_dictionary_keys_are_converted_to_strings(self):
        from sagaz.core.storage.migration import _canonical_checksum_value

        value = {1: "one", 2: {"nested": "value"}}

        assert _canonical_checksum_value(value) == {
            "1": "one",
            "2": {"nested": "value"},
        }

    def test_list_and_tuple_are_normalized_to_lists(self):
        from sagaz.core.storage.migration import _canonical_checksum_value

        assert _canonical_checksum_value((1, (2, 3))) == [1, [2, 3]]

    def test_set_is_sorted_deterministically(self):
        from sagaz.core.storage.migration import _canonical_checksum_value

        assert _canonical_checksum_value({"charlie", "alpha", "bravo"}) == [
            "alpha",
            "bravo",
            "charlie",
        ]

    def test_aware_datetime_is_normalized_to_utc(self):
        from datetime import datetime, timedelta, timezone

        from sagaz.core.storage.migration import _canonical_checksum_value

        value = datetime(2024, 1, 1, 3, tzinfo=timezone(timedelta(hours=3)))

        assert _canonical_checksum_value(value) == "2024-01-01T00:00:00+00:00"

    def test_naive_datetime_keeps_its_local_representation(self):
        from datetime import datetime

        from sagaz.core.storage.migration import _canonical_checksum_value

        value = datetime(2024, 1, 1, 12, 30)

        assert _canonical_checksum_value(value) == "2024-01-01T12:30:00"

    @pytest.mark.parametrize(
        "field_name",
        ["created_at", "claimed_at", "sent_at", "dead_letter_at"],
    )
    def test_timestamp_fields_are_normalized_to_utc(self, field_name):
        from sagaz.core.storage.migration import _canonical_checksum_value

        value = "2024-01-01T03:00:00+03:00"

        assert _canonical_checksum_value(value, field_name) == ("2024-01-01T00:00:00+00:00")

    def test_invalid_timestamp_string_is_preserved(self):
        from sagaz.core.storage.migration import _canonical_checksum_value

        assert _canonical_checksum_value("not-a-date", "created_at") == "not-a-date"

    def test_non_timestamp_string_is_not_parsed(self):
        from sagaz.core.storage.migration import _canonical_checksum_value

        value = "2024-01-01T03:00:00+03:00"

        assert _canonical_checksum_value(value, "description") == value

    def test_isoformat_fallback_is_preserved(self):
        from datetime import date

        from sagaz.core.storage.migration import _canonical_checksum_value

        assert _canonical_checksum_value(date(2024, 1, 2)) == "2024-01-02"

    def test_value_attribute_fallback_is_preserved(self):
        from enum import Enum

        from sagaz.core.storage.migration import _canonical_checksum_value

        class Status(Enum):
            COMPLETED = "completed"

        assert _canonical_checksum_value(Status.COMPLETED) == "completed"


class TestStorageChecksumCanonicalCompatibility:
    """Ensure equivalent timestamp representations produce equal checksums."""

    @pytest.mark.asyncio
    async def test_equivalent_timestamp_representations_produce_same_checksum(self):
        from datetime import datetime, timedelta, timezone

        from sagaz.core.storage.migration import _storage_checksum

        class Storage:
            def __init__(self, record):
                self.record = record

            async def export_all(self):
                yield self.record

        offset_datetime = datetime(2024, 1, 1, 3, tzinfo=timezone(timedelta(hours=3)))

        string_storage = Storage({"event_id": "event-1", "created_at": "2024-01-01T03:00:00+03:00"})
        datetime_storage = Storage({"event_id": "event-1", "created_at": offset_datetime})

        string_checksum = await _storage_checksum(string_storage)
        datetime_checksum = await _storage_checksum(datetime_storage)

        assert string_checksum == datetime_checksum


class TestVerifyWithoutExportAll:
    """Backends lacking export_all() fall back to plain record counts."""

    @staticmethod
    def _count_only_manager(saga_total: int, event_count: int, *, broken: bool = False):
        manager = _mock_manager(saga_total, event_count)
        del manager.saga.export_all
        del manager.outbox.export_all
        if broken:
            manager.saga.get_statistics = AsyncMock(side_effect=RuntimeError("down"))
            manager.outbox.count = AsyncMock(side_effect=RuntimeError("down"))
        return manager

    @pytest.mark.asyncio
    async def test_counts_are_compared_without_checksums(self):
        source = self._count_only_manager(4, 2)
        dest = self._count_only_manager(4, 2)

        vr = await SagaStorageMigrator(source, dest).verify()

        assert (vr.source_sagas, vr.dest_sagas) == (4, 4)
        assert (vr.source_events, vr.dest_events) == (2, 2)
        assert vr.source_saga_checksum == vr.dest_event_checksum == ""
        assert vr.ok is True

    @pytest.mark.asyncio
    async def test_count_failures_are_reported_as_minus_one(self):
        source = self._count_only_manager(4, 2, broken=True)
        dest = self._count_only_manager(4, 2, broken=True)

        vr = await SagaStorageMigrator(source, dest).verify()

        assert vr.source_sagas == vr.dest_sagas == -1
        assert vr.source_events == vr.dest_events == -1


@pytest.mark.asyncio
async def test_storage_checksum_requires_export_all():
    from sagaz.core.storage.migration import _storage_checksum

    with pytest.raises(TypeError, match="does not support export_all"):
        await _storage_checksum(object())
