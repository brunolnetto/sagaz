"""
CLI group for discovery and running Sagaz examples.
Modified to maintain backward compatibility with tests (v1.6.1).
"""

import logging

import click

from .discovery import (
    discover_examples,
    discover_examples_by_domain,
    get_categories,
    get_domains,
    get_example_description,
    get_examples_dir,
)
from .execution import execute_example
from .interactive import (
    _category_menu_loop,
    _examples_menu_loop,
    _fallback_interactive_simple,
    interactive_cmd,
)
from .ui import TableClass, console, display_examples

logger = logging.getLogger(__name__)


# Aliases for backward compatibility with tests
_execute_example = execute_example


@click.group(name="examples", invoke_without_command=True)
@click.pass_context
def examples_cli(ctx):
    """Explore and run Sagaz examples."""
    if ctx.invoked_subcommand is None:
        interactive_cmd()


@examples_cli.command(name="list")
@click.option("--domain", help="Filter by domain (e.g. Business, Technology)")
def list_examples(domain: str | None = None):
    """List available examples grouped by domain."""
    list_examples_cmd(domain)


def list_examples_cmd(domain: str | None = None):
    """Internal implementation of list-examples for testing and reuse."""
    by_domain = discover_examples_by_domain()
    if not by_domain:
        click.echo("No examples found.")
        return

    if domain:
        if domain not in by_domain:
            click.echo(f"Error: domain '{domain}' not found.")
            return
        by_domain = {domain: by_domain[domain]}

    display_examples(by_domain)


@examples_cli.command(name="run")
@click.argument("name")
def run_example(name: str):
    """Run a specific example by name."""
    run_example_cmd(name)


def run_example_cmd(name: str):
    """Internal implementation of run-example for testing and reuse."""
    by_domain = discover_examples_by_domain()
    all_examples = {}
    for examples in by_domain.values():
        all_examples.update(examples)

    if name not in all_examples:
        click.echo(f"Error: Example '{name}' not found.")
        return

    script_path = all_examples[name]
    click.echo(f"Running example: {name}...")
    execute_example(script_path)


@examples_cli.command(name="select")
@click.option("--category", help="Start in specific category")
def select_example(category: str | None = None):
    """Interactive example browser."""
    interactive_cmd(category)
