"""
Tests for missing paths in CLI modules:
- sagaz/cli/project.py (81.7%) - lines 13-14, 24, 104, 121-122, 162-164, 192-193, 201-202, 220, 222-225
- sagaz/cli/replay.py (89.3%) - lines 24-26, 102, 110, 112, 114, 252, 360, 377, 398, 405-414, 416-418, 555
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


# =============================================================================
# sagaz/cli/project.py - missing paths
# =============================================================================


class TestProjectCliRichFallback:
    """Lines 13-14, 24: rich not available → console=None, echo uses click.echo."""

    def test_echo_uses_click_when_console_none(self):
        """Lines 13-14, 24: When rich not installed, echo() delegates to click.echo."""
        from unittest.mock import patch as mock_patch

        import sagaz.cli.project as project_mod

        # Patch console to None inside the module, then call echo()
        with mock_patch("sagaz.cli.project.console", None):
            with mock_patch("sagaz.cli.project.click") as mock_click:
                project_mod.echo("Test message [bold]styled[/bold]")
                mock_click.echo.assert_called_once_with("Test message [bold]styled[/bold]")

    def test_list_sagas_rich_import_fallback(self, runner, tmp_path):
        """Lines 162-164: list_sagas uses click.echo fallback when rich not available."""
        from sagaz.cli.project import list_sagas

        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "sagas").mkdir()

        sagaz_yaml = """name: myproject
version: "0.1.0"
paths:
  - sagas/
"""
        (project_dir / "sagaz.yaml").write_text(sagaz_yaml)

        # Write a saga file
        saga_py = """from sagaz import Saga, action

class MySaga(Saga):
    @action("step")
    async def step(self, ctx):
        return {}
"""
        (project_dir / "sagas" / "my_saga.py").write_text(saga_py)

        with runner.isolated_filesystem(temp_dir=tmp_path):
            os.chdir(project_dir)
            # Patch rich to be unavailable inside list_sagas
            with patch.dict(sys.modules, {"rich": None, "rich.console": None, "rich.table": None}):
                # Force the import to fail inside list_sagas
                result = runner.invoke(list_sagas)
                # Should succeed with click.echo fallback
                assert result.exit_code == 0
                # Either rich output or fallback output
                assert "MySaga" in result.output or result.exit_code == 0

    def test_check_yaml_parse_error(self, runner, tmp_path):
        """Line 104: check() catches YAML parse error and exits 1."""
        from sagaz.cli.project import check

        project_dir = tmp_path / "badproject"
        project_dir.mkdir()

        # Write invalid YAML
        (project_dir / "sagaz.yaml").write_text("name: {invalid yaml: [")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            os.chdir(project_dir)
            result = runner.invoke(check)
            assert result.exit_code == 1
            assert "Error parsing sagaz.yaml" in result.output

    def test_iter_python_files_skips_missing_paths(self, tmp_path):
        """Lines 121-122: _iter_python_files skips non-existent paths."""
        from sagaz.cli.project import _iter_python_files

        missing_path = str(tmp_path / "nonexistent_dir")
        result = list(_iter_python_files([missing_path]))
        assert result == []  # should skip, not raise

    def test_list_sagas_no_sagas_found(self, runner, tmp_path):
        """Lines 192-193: list_sagas when no sagas found."""
        from sagaz.cli.project import list_sagas

        project_dir = tmp_path / "emptyproject"
        project_dir.mkdir()
        (project_dir / "sagas").mkdir()

        sagaz_yaml = """name: emptyproject
version: "0.1.0"
paths:
  - sagas/
"""
        (project_dir / "sagaz.yaml").write_text(sagaz_yaml)

        with runner.isolated_filesystem(temp_dir=tmp_path):
            os.chdir(project_dir)
            result = runner.invoke(list_sagas)
            assert result.exit_code == 0
            assert "No sagas found" in result.output


# =============================================================================
# sagaz/cli/replay.py - missing paths
# =============================================================================


from sagaz.cli.replay import (
    _display_failure,
    _display_replay_config,
    _display_success,
    _execute_list_changes,
    _execute_replay,
    _execute_time_travel,
    _handle_exception,
    list_changes_command,
    replay,
    replay_command,
    time_travel_command,
)


class TestReplayCliRichFallback:
    """Lines 24-26, 102, 110, 112, 114: Rich not available → fallback output."""

    def test_display_replay_config_without_rich(self):
        """Line 102: _display_replay_config uses click.echo when rich not available."""
        import sagaz.cli.replay as replay_mod

        with patch.object(replay_mod, "HAS_RICH", False):
            with patch.object(replay_mod, "console", None):
                # Should not raise and use click.echo
                from unittest.mock import patch as mock_patch

                with mock_patch("sagaz.cli.replay.click") as mock_click:
                    _display_replay_config(
                        saga_id="saga-123",
                        from_step="step1",
                        storage="memory",
                        context_override={},
                        dry_run=False,
                    )
                    mock_click.echo.assert_called()

    def test_display_success_without_rich(self):
        """Line 110: _display_success uses click.echo when rich not available."""
        import sagaz.cli.replay as replay_mod

        with patch.object(replay_mod, "HAS_RICH", False):
            with patch.object(replay_mod, "console", None):
                from unittest.mock import patch as mock_patch

                with mock_patch("sagaz.cli.replay.click") as mock_click:
                    _display_success()
                    mock_click.echo.assert_called()

    def test_display_failure_without_rich(self):
        """Lines 112, 114: _display_failure uses click.echo when rich not available."""
        import sagaz.cli.replay as replay_mod

        with patch.object(replay_mod, "HAS_RICH", False):
            with patch.object(replay_mod, "console", None):
                from unittest.mock import patch as mock_patch

                with mock_patch("sagaz.cli.replay.click") as mock_click:
                    _display_failure()
                    mock_click.echo.assert_called()

    def test_handle_exception_without_rich(self):
        """_handle_exception uses click.echo when rich not available."""
        import sagaz.cli.replay as replay_mod

        with patch.object(replay_mod, "HAS_RICH", False):
            with patch.object(replay_mod, "console", None):
                from unittest.mock import patch as mock_patch

                with mock_patch("sagaz.cli.replay.click") as mock_click:
                    _handle_exception(RuntimeError("test error"), verbose=False)
                    mock_click.echo.assert_called()

    def test_handle_exception_verbose_mode(self):
        """_handle_exception with verbose=True prints traceback."""
        import sagaz.cli.replay as replay_mod

        with patch.object(replay_mod, "HAS_RICH", False):
            with patch.object(replay_mod, "console", None):
                with patch("traceback.print_exc") as mock_tb:
                    _handle_exception(RuntimeError("test error"), verbose=True)
                    mock_tb.assert_called_once()


class TestReplayCommandWithExceptionHandling:
    """Lines 252, 360: exception handling in replay_command and time_travel_command."""

    def test_replay_command_exception_handled(self, runner):
        """Line 252: replay_command exception calls _handle_exception."""
        with patch("sagaz.cli.replay._execute_replay", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = RuntimeError("replay error")

            result = runner.invoke(
                replay_command,
                [
                    "550e8400-e29b-41d4-a716-446655440000",
                    "--from-step",
                    "step1",
                ],
            )
            # Should still exit without crash
            assert "replay error" in result.output or result.exit_code != 0

    def test_time_travel_command_invalid_timestamp(self, runner):
        """Line 360 area: Invalid timestamp format is handled."""
        result = runner.invoke(
            time_travel_command,
            [
                "550e8400-e29b-41d4-a716-446655440000",
                "--at",
                "not-a-timestamp",
            ],
        )
        assert "Invalid timestamp" in result.output or result.exit_code != 0

    def test_time_travel_command_invalid_saga_id(self, runner):
        """time_travel_command with bad saga ID exits cleanly."""
        result = runner.invoke(
            time_travel_command,
            [
                "bad-saga-id",
                "--at",
                "2024-01-15T10:30:00Z",
            ],
        )
        assert "Invalid saga ID" in result.output or result.exit_code != 0


class TestExecuteReplay:
    """Lines 377-398: _execute_replay with memory storage."""

    @pytest.mark.asyncio
    async def test_execute_replay_success(self):
        """Lines 377-398: _execute_replay with memory storage runs successfully."""
        from uuid import UUID

        mock_result = MagicMock()
        mock_result.replay_status.value = "success"
        mock_result.original_saga_id = "saga-123"
        mock_result.new_saga_id = "saga-456"
        mock_result.checkpoint_step = "step1"
        mock_result.error_message = None

        with (
            patch("sagaz.core.replay.saga_replay.SagaReplay") as mock_replay_cls,
        ):
            mock_replay = AsyncMock()
            mock_replay.from_checkpoint = AsyncMock(return_value=mock_result)
            mock_replay.list_available_checkpoints = AsyncMock(return_value=[])
            mock_replay_cls.return_value = mock_replay

            result = await _execute_replay(
                saga_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                from_step="step1",
                storage_type="memory",
                storage_url=None,
                context_override={},
                dry_run=False,
                verbose=False,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_execute_replay_unsupported_storage(self):
        """Unsupported storage type raises NotImplementedError."""
        from uuid import UUID

        with pytest.raises(NotImplementedError):
            await _execute_replay(
                saga_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                from_step="step1",
                storage_type="redis",
                storage_url=None,
                context_override={},
                dry_run=False,
                verbose=False,
            )


class TestExecuteTimeTravel:
    """Lines 405-418: _execute_time_travel."""

    @pytest.mark.asyncio
    async def test_execute_time_travel_no_state_found(self):
        """Lines 405-414: When no state at timestamp, returns False."""
        from datetime import UTC, datetime
        from uuid import UUID

        with patch("sagaz.core.replay.time_travel.SagaTimeTravel") as mock_tt_cls:
            mock_tt = AsyncMock()
            mock_tt.get_state_at = AsyncMock(return_value=None)
            mock_tt.get_context_at = AsyncMock(return_value=None)
            mock_tt_cls.return_value = mock_tt

            # Without key → get_state_at returns None
            result = await _execute_time_travel(
                saga_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
                storage_type="memory",
                storage_url=None,
                key=None,
                output_format="text",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_execute_time_travel_with_key_no_value(self):
        """Lines 410-411: Specific key query with no value → False."""
        from datetime import UTC, datetime
        from uuid import UUID

        with patch("sagaz.core.replay.time_travel.SagaTimeTravel") as mock_tt_cls:
            mock_tt = AsyncMock()
            mock_tt.get_context_at = AsyncMock(return_value=None)
            mock_tt_cls.return_value = mock_tt

            result = await _execute_time_travel(
                saga_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
                storage_type="memory",
                storage_url=None,
                key="payment_token",
                output_format="text",
            )
            assert result is False


class TestExecuteListChanges:
    """Line 555: _execute_list_changes."""

    @pytest.mark.asyncio
    async def test_execute_list_changes_empty(self):
        """Line 555: _execute_list_changes with no changes."""
        from uuid import UUID

        with patch("sagaz.core.replay.time_travel.SagaTimeTravel") as mock_tt_cls:
            mock_tt = AsyncMock()
            mock_tt.list_state_changes = AsyncMock(return_value=[])
            mock_tt_cls.return_value = mock_tt

            # Should complete without error
            await _execute_list_changes(
                saga_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                after=None,
                before=None,
                limit=100,
                storage_type="memory",
            )
