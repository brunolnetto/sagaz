"""
Sagaz CLI Application - Built with Click.

This module defines the ``cli`` group and registers the commands for all
deployment scenarios:
- Local development (Docker Compose)
- Self-hosted (on-premise servers)
- Cloud-native (Kubernetes)
- Hybrid deployments
- Benchmarking

Command implementations live in cohesive private modules and are re-exported
here so ``from sagaz.cli.app import <command>`` keeps working.
"""

import subprocess
import sys
from pathlib import Path

import click

from sagaz.cli import examples as cli_examples
from sagaz.cli._benchmark_cmd import benchmark_cmd
from sagaz.cli._dev_cmds import dev_cmd, logs_cmd, status_cmd, stop_cmd, version_cmd
from sagaz.cli._init_handlers import _copy_example_saga
from sagaz.cli._monitor_cmd import (
    _LOOPBACK_HOSTS,
    _WILDCARD_HOSTS,
    _browser_host,
    _echo_worker_setup,
    _is_loopback,
    _maybe_open_browser,
    _require_safe_bind,
    _url_host,
    _worker_host,
    monitor_cmd,
)
from sagaz.cli._project_cmds import (
    _prompt_example_choice,
    _prompt_project_details,
    _validate_project_directory,
    init_cmd,
    setup_cmd,
)
from sagaz.cli._setup_handlers import (
    _check_project_exists,
    _display_configuration_summary,
    _display_setup_header,
    _execute_setup,
    _gather_setup_configuration,
)
from sagaz.cli.demonstrations import demo_cli
from sagaz.cli.dlq import dlq_cli
from sagaz.cli.dry_run import simulate_cmd, validate_cmd
from sagaz.cli.migrate import migrate_cmd
from sagaz.cli.project import check as check_cmd
from sagaz.cli.project import list_sagas
from sagaz.cli.replay import replay
from sagaz.cli.tenant import tenant_cli
from sagaz.cli.visualize import visualize_cmd

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console: Console | None = Console()
except ImportError:
    console = None
    Panel = None  # type: ignore[assignment,misc]

__all__ = [
    "_LOOPBACK_HOSTS",
    "_WILDCARD_HOSTS",
    "OrderedGroup",
    "Panel",
    "Path",
    "Table",
    "_browser_host",
    "_check_project_exists",
    "_copy_example_saga",
    "_display_configuration_summary",
    "_display_setup_header",
    "_echo_worker_setup",
    "_execute_setup",
    "_gather_setup_configuration",
    "_is_loopback",
    "_maybe_open_browser",
    "_prompt_example_choice",
    "_prompt_project_details",
    "_require_safe_bind",
    "_url_host",
    "_validate_project_directory",
    "_worker_host",
    "benchmark_cmd",
    "check_cmd",
    "cli",
    "console",
    "demo_cli",
    "dev_cmd",
    "dlq_cli",
    "examples_cmd",
    "init_cmd",
    "list_sagas",
    "logs_cmd",
    "migrate_cmd",
    "monitor_cmd",
    "replay",
    "setup_cmd",
    "simulate_cmd",
    "status_cmd",
    "stop_cmd",
    "subprocess",
    "sys",
    "validate_cmd",
    "version_cmd",
    "visualize_cmd",
]


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
@click.version_option(package_name="sagaz", prog_name="sagaz")
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
# sagaz examples
# ============================================================================
examples_cmd = cli_examples.examples_cli


# ============================================================================
# Command Registration (Progressive Risk Order)
# ============================================================================
# Commands appear in help in the order they're added to the group.
# We explicitly register all commands here in the desired order.

# Analysis/Validation (Read-only, zero risk)
cli.add_command(validate_cmd, name="validate")
cli.add_command(simulate_cmd, name="simulate")

# Project Management (Structure & Configuration)
cli.add_command(init_cmd, name="init")
cli.add_command(setup_cmd, name="setup")
cli.add_command(check_cmd, name="check")
cli.add_command(list_sagas, name="list")
cli.add_command(examples_cmd, name="examples")
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
cli.add_command(visualize_cmd, name="visualize")

# DLQ Management
cli.add_command(dlq_cli, name="dlq")

# State Modification (Highest Risk)
cli.add_command(migrate_cmd, name="migrate")
cli.add_command(replay, name="replay")
cli.add_command(tenant_cli, name="tenant")

if __name__ == "__main__":
    cli()
