"""Data-source options are named ``--<thing>-url``; former spellings still work (#572)."""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from sagaz.cli.app import cli

RENAMED = [
    (("analytics", "export"), "--saga-log-url", "--saga-log"),
    (("choreography", "status"), "--saga-log-url", "--saga-log"),
    (("monitor",), "--saga-log-url", "--saga-log"),
    (("event-log",), "--event-store-url", "--store-url"),
]


def command_at(path: tuple[str, ...]) -> click.Command:
    command: click.Command = cli
    for name in path:
        assert isinstance(command, click.Group)
        found = command.get_command(click.Context(command), name)
        assert found is not None, name
        command = found
    return command


@pytest.mark.parametrize(("path", "new", "old"), RENAMED)
def test_help_shows_only_the_new_name(path, new, old):
    result = CliRunner().invoke(cli, [*path, "--help"])
    assert result.exit_code == 0, result.output
    assert new in result.output
    assert f"{old} " not in result.output
    assert f"{old}," not in result.output


@pytest.mark.parametrize(("path", "new", "old"), RENAMED)
def test_both_names_set_the_same_option(path, new, old):
    (option,) = [p for p in command_at(path).params if new in getattr(p, "opts", [])]
    assert old in option.opts
