"""
Tests for CLI replay module.
"""

from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from click.testing import CliRunner

from sagaz.cli.replay import (
    _execute_list_changes,
    _execute_replay,
    _execute_time_travel,
    list_changes_command,
    replay,
    replay_command,
    time_travel_command,
)


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def mock_saga_replay():
    """Mock SagaReplay class."""
    with patch("sagaz.core.saga_replay.SagaReplay") as mock:
        instance = MagicMock()
        instance.list_available_checkpoints = AsyncMock(return_value=[])
        instance.from_checkpoint = AsyncMock()
        mock.return_value = instance
        yield mock


@pytest.fixture
def mock_time_travel():
    """Mock SagaTimeTravel class."""
    with patch("sagaz.core.time_travel.SagaTimeTravel") as mock:
        instance = MagicMock()
        instance.get_context_at = AsyncMock(return_value=None)
        instance.get_state_at = AsyncMock(return_value=None)
        instance.list_state_changes = AsyncMock(return_value=[])
        mock.return_value = instance
        yield mock


@pytest.fixture
def mock_memory_storage():
    """Mock InMemorySnapshotStorage."""
    with patch("sagaz.storage.backends.memory_snapshot.InMemorySnapshotStorage") as mock:
        yield mock


class TestReplayCommandGroup:
    """Tests for replay command group."""

    def test_replay_group_exists(self, runner):
        """Test that replay group exists."""
        result = runner.invoke(replay, ["--help"])
        assert result.exit_code == 0
        assert "Saga replay and time-travel commands" in result.output

    def test_replay_group_has_subcommands(self, runner):
        """Test that replay group has subcommands."""
        result = runner.invoke(replay, ["--help"])
        assert "run" in result.output
        assert "time-travel" in result.output
        assert "list-changes" in result.output


class TestReplayCommand:
    """Tests for replay run command."""

    def test_replay_command_requires_saga_id(self, runner):
        """Test that replay command requires saga_id argument."""
        result = runner.invoke(replay_command, [])
        assert result.exit_code != 0

    def test_replay_command_requires_from_step(self, runner):
        """Test that replay command requires --from-step option."""
        result = runner.invoke(
            replay_command, ["550e8400-e29b-41d4-a716-446655440000"]
        )
        assert result.exit_code != 0

    def test_replay_command_invalid_saga_id(self, runner):
        """Test replay command with invalid saga ID."""
        result = runner.invoke(
            replay_command, ["invalid-uuid", "--from-step", "step1"]
        )
        # Click wraps return values, check output instead
        assert "Invalid saga ID" in result.output

    def test_replay_command_invalid_override_format(self, runner):
        """Test replay command with invalid override format."""
        result = runner.invoke(
            replay_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--from-step",
                "step1",
                "--override",
                "invalid_format",
            ],
        )
        assert "Invalid override format" in result.output

    def test_replay_command_valid_override(self, runner, mock_saga_replay, mock_memory_storage):
        """Test replay command with valid override."""
        # Mock successful replay
        mock_result = MagicMock()
        mock_result.replay_status.value = "success"
        mock_result.original_saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_result.new_saga_id = "660e8400-e29b-41d4-a716-446655440000"
        mock_result.checkpoint_step = "step1"
        mock_result.error_message = None

        mock_saga_replay.return_value.from_checkpoint.return_value = mock_result

        result = runner.invoke(
            replay_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--from-step",
                "step1",
                "--override",
                "key1=value1",
            ],
        )
        assert result.exit_code == 0

    def test_replay_command_dry_run(self, runner, mock_saga_replay, mock_memory_storage):
        """Test replay command with dry-run flag."""
        mock_result = MagicMock()
        mock_result.replay_status.value = "success"
        mock_result.original_saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_result.new_saga_id = None
        mock_result.checkpoint_step = "step1"
        mock_result.error_message = None

        mock_saga_replay.return_value.from_checkpoint.return_value = mock_result

        result = runner.invoke(
            replay_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--from-step",
                "step1",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0

    def test_replay_command_verbose_mode(self, runner, mock_saga_replay, mock_memory_storage):
        """Test replay command with verbose flag."""
        mock_saga_replay.return_value.list_available_checkpoints.return_value = [
            {"step_name": "step1", "created_at": "2024-01-01T00:00:00Z"}
        ]

        mock_result = MagicMock()
        mock_result.replay_status.value = "success"
        mock_result.original_saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_result.new_saga_id = "660e8400-e29b-41d4-a716-446655440000"
        mock_result.checkpoint_step = "step1"
        mock_result.error_message = None

        mock_saga_replay.return_value.from_checkpoint.return_value = mock_result

        result = runner.invoke(
            replay_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--from-step",
                "step1",
                "--verbose",
            ],
        )
        assert result.exit_code == 0

    def test_replay_command_failed_replay(self, runner, mock_saga_replay, mock_memory_storage):
        """Test replay command when replay fails."""
        mock_result = MagicMock()
        mock_result.replay_status.value = "failed"
        mock_result.original_saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_result.new_saga_id = None
        mock_result.checkpoint_step = "step1"
        mock_result.error_message = "Something went wrong"

        mock_saga_replay.return_value.from_checkpoint.return_value = mock_result

        result = runner.invoke(
            replay_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--from-step",
                "step1",
            ],
        )
        assert "failed" in result.output.lower()

    def test_replay_command_exception_handling(self, runner, mock_saga_replay, mock_memory_storage):
        """Test replay command exception handling."""
        mock_saga_replay.return_value.from_checkpoint.side_effect = Exception("Test error")

        result = runner.invoke(
            replay_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--from-step",
                "step1",
            ],
        )
        assert "Error" in result.output or "Test error" in result.output


class TestTimeTravelCommand:
    """Tests for time-travel command."""

    def test_time_travel_requires_saga_id(self, runner):
        """Test that time-travel requires saga_id."""
        result = runner.invoke(time_travel_command, [])
        assert result.exit_code != 0

    def test_time_travel_requires_timestamp(self, runner):
        """Test that time-travel requires --at option."""
        result = runner.invoke(
            time_travel_command, ["550e8400-e29b-41d4-a716-446655440000"]
        )
        assert result.exit_code != 0

    def test_time_travel_invalid_saga_id(self, runner):
        """Test time-travel with invalid saga ID."""
        result = runner.invoke(
            time_travel_command, ["invalid-uuid", "--at", "2024-01-15T10:30:00Z"]
        )
        assert "Invalid saga ID" in result.output

    def test_time_travel_invalid_timestamp(self, runner):
        """Test time-travel with invalid timestamp."""
        result = runner.invoke(
            time_travel_command,
            ["550e8400-e29b-41d4-a716-446655440000", "--at", "invalid-timestamp"],
        )
        assert "Invalid timestamp" in result.output

    def test_time_travel_query_state_not_found(self, runner, mock_time_travel, mock_memory_storage):
        """Test time-travel when state is not found."""
        mock_time_travel.return_value.get_state_at.return_value = None

        result = runner.invoke(
            time_travel_command,
            ["550e8400-e29b-41d4-a716-446655440000", "--at", "2024-01-15T10:30:00Z"],
        )
        assert "No state found" in result.output

    def test_time_travel_query_specific_key_not_found(self, runner, mock_time_travel, mock_memory_storage):
        """Test time-travel querying specific key not found."""
        mock_time_travel.return_value.get_context_at.return_value = None

        result = runner.invoke(
            time_travel_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--at",
                "2024-01-15T10:30:00Z",
                "--key",
                "payment_token",
            ],
        )
        assert "No state found" in result.output

    def test_time_travel_query_specific_key_found(self, runner, mock_time_travel, mock_memory_storage):
        """Test time-travel querying specific key found."""
        mock_time_travel.return_value.get_context_at.return_value = "token123"

        result = runner.invoke(
            time_travel_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--at",
                "2024-01-15T10:30:00Z",
                "--key",
                "payment_token",
            ],
        )
        assert result.exit_code == 0
        assert "token123" in result.output

    def test_time_travel_json_format(self, runner, mock_time_travel, mock_memory_storage):
        """Test time-travel with JSON output format."""
        mock_time_travel.return_value.get_context_at.return_value = "token123"

        result = runner.invoke(
            time_travel_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--at",
                "2024-01-15T10:30:00Z",
                "--key",
                "payment_token",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert '"payment_token"' in result.output
        assert '"token123"' in result.output

    def test_time_travel_full_state_text_format(self, runner, mock_time_travel, mock_memory_storage):
        """Test time-travel full state with text format."""
        mock_state = MagicMock()
        mock_state.saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_state.saga_name = "TestSaga"
        mock_state.status = "executing"
        mock_state.current_step = "step1"
        mock_state.step_index = 0
        mock_state.completed_steps = ["step0"]
        mock_state.context = {"key1": "value1"}
        mock_state.to_dict.return_value = {
            "saga_id": "550e8400-e29b-41d4-a716-446655440000",
            "saga_name": "TestSaga",
            "status": "executing",
        }

        mock_time_travel.return_value.get_state_at.return_value = mock_state

        result = runner.invoke(
            time_travel_command,
            ["550e8400-e29b-41d4-a716-446655440000", "--at", "2024-01-15T10:30:00Z"],
        )
        assert result.exit_code == 0
        assert "TestSaga" in result.output
        assert "executing" in result.output

    def test_time_travel_exception_handling(self, runner, mock_time_travel, mock_memory_storage):
        """Test time-travel exception handling."""
        mock_time_travel.return_value.get_state_at.side_effect = Exception("Test error")

        result = runner.invoke(
            time_travel_command,
            ["550e8400-e29b-41d4-a716-446655440000", "--at", "2024-01-15T10:30:00Z"],
        )
        assert "Error" in result.output or "Test error" in result.output


class TestListChangesCommand:
    """Tests for list-changes command."""

    def test_list_changes_requires_saga_id(self, runner):
        """Test that list-changes requires saga_id."""
        result = runner.invoke(list_changes_command, [])
        assert result.exit_code != 0

    def test_list_changes_invalid_saga_id(self, runner):
        """Test list-changes with invalid saga ID."""
        result = runner.invoke(list_changes_command, ["invalid-uuid"])
        assert "Invalid saga ID" in result.output

    def test_list_changes_invalid_after_timestamp(self, runner):
        """Test list-changes with invalid after timestamp."""
        result = runner.invoke(
            list_changes_command,
            ["550e8400-e29b-41d4-a716-446655440000", "--after", "invalid-timestamp"],
        )
        assert "Invalid 'after' timestamp" in result.output

    def test_list_changes_invalid_before_timestamp(self, runner):
        """Test list-changes with invalid before timestamp."""
        result = runner.invoke(
            list_changes_command,
            ["550e8400-e29b-41d4-a716-446655440000", "--before", "invalid-timestamp"],
        )
        assert "Invalid 'before' timestamp" in result.output

    def test_list_changes_no_changes_found(self, runner, mock_time_travel, mock_memory_storage):
        """Test list-changes when no changes found."""
        mock_time_travel.return_value.list_state_changes.return_value = []

        result = runner.invoke(
            list_changes_command, ["550e8400-e29b-41d4-a716-446655440000"]
        )
        assert result.exit_code == 0
        assert "No state changes found" in result.output

    def test_list_changes_with_results(self, runner, mock_time_travel, mock_memory_storage):
        """Test list-changes with results."""
        mock_change = MagicMock()
        mock_change.timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        mock_change.current_step = "step1"
        mock_change.status = "executing"
        mock_change.completed_steps = ["step0"]

        mock_time_travel.return_value.list_state_changes.return_value = [mock_change]

        result = runner.invoke(
            list_changes_command, ["550e8400-e29b-41d4-a716-446655440000"]
        )
        assert result.exit_code == 0
        assert "step1" in result.output

    def test_list_changes_with_time_filters(self, runner, mock_time_travel, mock_memory_storage):
        """Test list-changes with time filters."""
        mock_change = MagicMock()
        mock_change.timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        mock_change.current_step = "step1"
        mock_change.status = "executing"
        mock_change.completed_steps = ["step0"]

        mock_time_travel.return_value.list_state_changes.return_value = [mock_change]

        result = runner.invoke(
            list_changes_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--after",
                "2024-01-15T09:00:00Z",
                "--before",
                "2024-01-15T11:00:00Z",
                "--limit",
                "10",
            ],
        )
        assert result.exit_code == 0

    def test_list_changes_exception_handling(self, runner, mock_time_travel, mock_memory_storage):
        """Test list-changes exception handling."""
        mock_time_travel.return_value.list_state_changes.side_effect = Exception(
            "Test error"
        )

        result = runner.invoke(
            list_changes_command, ["550e8400-e29b-41d4-a716-446655440000"]
        )
        assert "Error" in result.output or "Test error" in result.output


class TestExecuteReplay:
    """Tests for _execute_replay function."""

    @pytest.mark.asyncio
    async def test_execute_replay_basic(self, mock_saga_replay, mock_memory_storage):
        """Test basic replay execution."""
        mock_result = MagicMock()
        mock_result.replay_status.value = "success"
        mock_saga_replay.return_value.from_checkpoint.return_value = mock_result

        saga_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = await _execute_replay(
            saga_id, "step1", "memory", None, {}, False, False
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_replay_not_implemented_storage(self, mock_saga_replay):
        """Test replay with not implemented storage type."""
        saga_id = UUID("550e8400-e29b-41d4-a716-446655440000")

        with pytest.raises(NotImplementedError, match="redis"):
            await _execute_replay(
                saga_id, "step1", "redis", "redis://localhost", {}, False, False
            )


class TestExecuteTimeTravel:
    """Tests for _execute_time_travel function."""

    @pytest.mark.asyncio
    async def test_execute_time_travel_key_found(self, mock_time_travel, mock_memory_storage):
        """Test time-travel execution with key found."""
        mock_time_travel.return_value.get_context_at.return_value = "value123"

        saga_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

        result = await _execute_time_travel(
            saga_id, timestamp, "memory", None, "key1", "text"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_time_travel_key_not_found(self, mock_time_travel, mock_memory_storage):
        """Test time-travel execution with key not found."""
        mock_time_travel.return_value.get_context_at.return_value = None

        saga_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

        result = await _execute_time_travel(
            saga_id, timestamp, "memory", None, "key1", "text"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_execute_time_travel_not_implemented_storage(self, mock_time_travel):
        """Test time-travel with not implemented storage type."""
        saga_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

        with pytest.raises(NotImplementedError, match="postgres"):
            await _execute_time_travel(
                saga_id, timestamp, "postgres", "postgresql://localhost", None, "text"
            )


class TestExecuteListChanges:
    """Tests for _execute_list_changes function."""

    @pytest.mark.asyncio
    async def test_execute_list_changes_no_results(self, mock_time_travel, mock_memory_storage):
        """Test list changes execution with no results."""
        mock_time_travel.return_value.list_state_changes.return_value = []

        saga_id = UUID("550e8400-e29b-41d4-a716-446655440000")

        # Should not raise exception
        await _execute_list_changes(saga_id, None, None, 100, "memory")

    @pytest.mark.asyncio
    async def test_execute_list_changes_with_results(self, mock_time_travel, mock_memory_storage):
        """Test list changes execution with results."""
        mock_change = MagicMock()
        mock_change.timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        mock_change.current_step = "step1"
        mock_change.status = "executing"
        mock_change.completed_steps = ["step0"]

        mock_time_travel.return_value.list_state_changes.return_value = [mock_change]

        saga_id = UUID("550e8400-e29b-41d4-a716-446655440000")

        # Should not raise exception
        await _execute_list_changes(saga_id, None, None, 100, "memory")

    @pytest.mark.asyncio
    async def test_execute_list_changes_not_implemented_storage(self, mock_time_travel):
        """Test list changes with not implemented storage type."""
        saga_id = UUID("550e8400-e29b-41d4-a716-446655440000")

        with pytest.raises(NotImplementedError, match="redis"):
            await _execute_list_changes(saga_id, None, None, 100, "redis")


class TestStorageTypeValidation:
    """Tests for storage type validation across commands."""

    def test_replay_accepts_valid_storage_types(self, runner):
        """Test that replay command accepts valid storage types."""
        for storage_type in ["memory", "redis", "postgres"]:
            result = runner.invoke(
                replay_command,
                [
                    "550e8400-e29b-41d4-a716-446655440000",
                    "--from-step",
                    "step1",
                    "--storage",
                    storage_type,
                    "--dry-run",  # To avoid actual execution
                ],
            )
            # Should fail on storage implementation, not validation
            assert "Invalid value for '--storage'" not in result.output

    def test_time_travel_accepts_valid_storage_types(self, runner):
        """Test that time-travel command accepts valid storage types."""
        for storage_type in ["memory", "redis", "postgres"]:
            result = runner.invoke(
                time_travel_command,
                [
                    "550e8400-e29b-41d4-a716-446655440000",
                    "--at",
                    "2024-01-15T10:30:00Z",
                    "--storage",
                    storage_type,
                ],
            )
            # Should fail on execution, not storage type validation
            assert "Invalid value for '--storage'" not in result.output

    def test_list_changes_accepts_valid_storage_types(self, runner):
        """Test that list-changes command accepts valid storage types."""
        for storage_type in ["memory", "redis", "postgres"]:
            result = runner.invoke(
                list_changes_command,
                [
                    "550e8400-e29b-41d4-a716-446655440000",
                    "--storage",
                    storage_type,
                ],
            )
            # Should fail on execution, not storage type validation
            assert "Invalid value for '--storage'" not in result.output


class TestRichConsoleOutput:
    """Tests for Rich console output paths."""

    def test_replay_verbose_with_rich(self, runner, mock_saga_replay, mock_memory_storage):
        """Test replay verbose mode with Rich console."""
        mock_saga_replay.return_value.list_available_checkpoints.return_value = [
            {"step_name": "step1", "created_at": "2024-01-01T00:00:00Z"},
            {"step_name": "step2", "created_at": "2024-01-01T00:01:00Z"}
        ]

        mock_result = MagicMock()
        mock_result.replay_status.value = "success"
        mock_result.original_saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_result.new_saga_id = "660e8400-e29b-41d4-a716-446655440000"
        mock_result.checkpoint_step = "step1"
        mock_result.error_message = None

        mock_saga_replay.return_value.from_checkpoint.return_value = mock_result

        result = runner.invoke(
            replay_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--from-step",
                "step1",
                "--verbose",
            ],
        )
        assert result.exit_code == 0

    def test_time_travel_with_json_format(self, runner, mock_time_travel, mock_memory_storage):
        """Test time-travel with JSON output format for full state."""
        mock_state = MagicMock()
        mock_state.saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_state.saga_name = "TestSaga"
        mock_state.status = "executing"
        mock_state.current_step = "step1"
        mock_state.step_index = 0
        mock_state.completed_steps = ["step0"]
        mock_state.context = {"key1": "value1"}
        mock_state.to_dict.return_value = {
            "saga_id": "550e8400-e29b-41d4-a716-446655440000",
            "saga_name": "TestSaga",
            "status": "executing",
        }

        mock_time_travel.return_value.get_state_at.return_value = mock_state

        result = runner.invoke(
            time_travel_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--at",
                "2024-01-15T10:30:00Z",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert "TestSaga" in result.output

    def test_time_travel_with_table_format_no_rich(self, runner, mock_time_travel, mock_memory_storage):
        """Test time-travel with table format when Rich is not available."""
        mock_state = MagicMock()
        mock_state.saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_state.saga_name = "TestSaga"
        mock_state.status = "executing"
        mock_state.current_step = "step1"
        mock_state.step_index = 0
        mock_state.completed_steps = ["step0"]
        mock_state.context = {"key1": "value1"}
        mock_state.to_dict.return_value = {
            "saga_id": "550e8400-e29b-41d4-a716-446655440000",
            "saga_name": "TestSaga",
            "status": "executing",
        }

        mock_time_travel.return_value.get_state_at.return_value = mock_state

        # Test table format falls back to text when Rich not available
        with patch("sagaz.cli.replay.HAS_RICH", False):
            result = runner.invoke(
                time_travel_command,
                [
                    "550e8400-e29b-41d4-a716-446655440000",
                    "--at",
                    "2024-01-15T10:30:00Z",
                    "--format",
                    "table",
                ],
            )
            assert result.exit_code == 0
            assert "TestSaga" in result.output


class TestWithoutRich:
    """Tests for CLI without Rich library."""

    def test_replay_command_without_rich(self, runner, mock_saga_replay, mock_memory_storage):
        """Test replay command without Rich available."""
        mock_result = MagicMock()
        mock_result.replay_status.value = "success"
        mock_result.original_saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_result.new_saga_id = "660e8400-e29b-41d4-a716-446655440000"
        mock_result.checkpoint_step = "step1"
        mock_result.error_message = None

        mock_saga_replay.return_value.from_checkpoint.return_value = mock_result

        with patch("sagaz.cli.replay.HAS_RICH", False):
            result = runner.invoke(
                replay_command,
                [
                    "550e8400-e29b-41d4-a716-446655440000",
                    "--from-step",
                    "step1",
                ],
            )
            assert result.exit_code == 0
            assert "Replaying saga" in result.output

    def test_replay_verbose_without_rich(self, runner, mock_saga_replay, mock_memory_storage):
        """Test replay verbose mode without Rich."""
        mock_saga_replay.return_value.list_available_checkpoints.return_value = [
            {"step_name": "step1", "created_at": "2024-01-01T00:00:00Z"}
        ]

        mock_result = MagicMock()
        mock_result.replay_status.value = "success"
        mock_result.original_saga_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_result.new_saga_id = "660e8400-e29b-41d4-a716-446655440000"
        mock_result.checkpoint_step = "step1"
        mock_result.error_message = None

        mock_saga_replay.return_value.from_checkpoint.return_value = mock_result

        with patch("sagaz.cli.replay.HAS_RICH", False):
            result = runner.invoke(
                replay_command,
                [
                    "550e8400-e29b-41d4-a716-446655440000",
                    "--from-step",
                    "step1",
                    "--verbose",
                ],
            )
            assert result.exit_code == 0
            assert "checkpoints" in result.output.lower()

    def test_list_changes_without_rich(self, runner, mock_time_travel, mock_memory_storage):
        """Test list-changes without Rich."""
        mock_change = MagicMock()
        mock_change.timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        mock_change.current_step = "step1"
        mock_change.status = "executing"
        mock_change.completed_steps = ["step0"]

        mock_time_travel.return_value.list_state_changes.return_value = [mock_change]

        with patch("sagaz.cli.replay.HAS_RICH", False):
            result = runner.invoke(
                list_changes_command, ["550e8400-e29b-41d4-a716-446655440000"]
            )
            assert result.exit_code == 0
            assert "step1" in result.output

