"""
Sagaz CLI Application - Built with Click.

This module contains the main entry point and group registration.
Commands are organized into sub-modules for maintainability.
"""

import sys
import click

from sagaz.cli import examples as cli_examples
from sagaz.cli.benchmark import benchmark_cmd
from sagaz.cli.demonstrations import demo_cli
from sagaz.cli.dlq import dlq_cli
from sagaz.cli.dry_run import simulate_cmd, validate_cmd
from sagaz.cli.init.wizard import init_wizard_cmd
from sagaz.cli.migrate import migrate_cmd
from sagaz.cli.ops import dev_cmd, logs_cmd, monitor_cmd, status_cmd, stop_cmd
from sagaz.cli.project import check as check_cmd
from sagaz.cli.project import list_sagas
from sagaz.cli.replay import replay
from sagaz.cli.setup import setup_cmd

# ============================================================================
# CLI Group
# ============================================================================


class OrderedGroup(click.Group):
    """Click Group that lists commands in the order they were added."""

    def list_commands(self, ctx):
        return list(self.commands.keys())

    def format_commands(self, ctx, formatter):
        """Override to hide the automatic Commands section."""
        # Do nothing - this prevents Click from adding the Commands list


@click.group(cls=OrderedGroup)
@click.version_option(version="1.0.3", prog_name="sagaz")
def cli():
    """
    Sagaz - Production-ready Saga Pattern Orchestration.

    \b
    Commands by Progressive Risk:

    \b
    Library demo:
      examples         Explore examples
      demo             Run built-in demonstrations


    \b
    Project Management:
      init             Initialize new project
      setup            Setup deployment environment
      check            Validate project structure
      list             List discovered sagas
      validate         Validate project sagas
      simulate         Analyze execution DAG


    \b
    Runtime Operations:
      dev              Start local environment
      status           Check service health
      logs             View logs
      monitor          Open monitoring dashboard
      stop             Stop services
      replay           Replay/modify saga state
      benchmark        Run performance tests
    """


# ============================================================================
# sagaz version
# ============================================================================


@click.command()
def version_cmd():
    """Show version information."""
    click.echo("sagaz version 1.0.3")
    click.echo("Python " + sys.version.split()[0])


# ============================================================================
# Command Registration (Progressive Risk Order)
# ============================================================================
# Commands appear in help in the order they're added to the group.
# We explicitly register all commands here in the desired order.

# Analysis/Validation (Read-only, zero risk)
cli.add_command(validate_cmd, name="validate")
cli.add_command(simulate_cmd, name="simulate")

# Project Management (Structure & Configuration)
cli.add_command(init_wizard_cmd, name="init")
cli.add_command(setup_cmd, name="setup")
cli.add_command(check_cmd, name="check")
cli.add_command(list_sagas, name="list")
cli.add_command(cli_examples.examples_cli, name="examples")
cli.add_command(demo_cli, name="demo")

# Development (Runtime Operations)
cli.add_command(dev_cmd, name="dev")
cli.add_command(status_cmd, name="status")
cli.add_command(logs_cmd, name="logs")
cli.add_command(monitor_cmd, name="monitor")
cli.add_command(stop_cmd, name="stop")

# Testing
cli.add_command(benchmark_cmd, name="benchmark")

# Utilities
cli.add_command(version_cmd, name="version")

# DLQ Management
cli.add_command(dlq_cli, name="dlq")

# State Modification (Highest Risk)
cli.add_command(migrate_cmd, name="migrate")
cli.add_command(replay, name="replay")

if __name__ == "__main__":
    cli()
