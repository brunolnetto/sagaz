"""
Interactive setup for deployment environments.
"""

import click
from sagaz.cli._setup_handlers import (
    _check_project_exists,
    _display_configuration_summary,
    _display_setup_header,
    _execute_setup,
    _gather_setup_configuration,
)


@click.command(name="setup")
def setup_cmd():
    """Setup deployment environment interactively."""
    _check_project_exists()
    _display_setup_header()

    config = _gather_setup_configuration()
    _display_configuration_summary(config)

    if not click.confirm("\nProceed with setup?", default=True):
        click.echo("Aborted.")
        return

    _execute_setup(config)
