"""
UI helpers for displaying examples in the CLI.
"""

from pathlib import Path

import click

try:
    from rich.console import Console
    from rich.table import Table
    console: Console | None = Console()
    TableClass: type[Table] | None = Table
except ImportError:
    console = None
    TableClass = None

from .discovery import discover_examples_by_domain, get_example_description


def display_examples(by_domain: dict[str, dict[str, Path]]):
    """Display examples in a table or plain text."""
    if console and TableClass:
        _display_examples_table(by_domain)
    else:
        _display_examples_plain(by_domain)


def _display_examples_table(by_domain: dict[str, dict[str, Path]]) -> None:
    """Display examples grouped by domain in a rich table."""
    table = TableClass(
        title="Sagaz Examples",
        show_header=True,
        header_style="bold magenta",
        expand=False,
    )
    table.add_column("Domain", style="bold", no_wrap=True, min_width=16)
    table.add_column("Subdomain", style="yellow", no_wrap=True, min_width=14)
    table.add_column("Name", style="cyan", no_wrap=True, min_width=20)
    table.add_column("Description", no_wrap=True, overflow="ellipsis")

    for domain_name, examples in by_domain.items():
        first = True
        for name, path in sorted(examples.items()):
            desc = get_example_description(path)
            parts = name.split("/")
            subdomain = parts[1] if len(parts) >= 3 else (parts[0] if len(parts) >= 2 else "")
            example_name = parts[2] if len(parts) >= 3 else (parts[-1] if "/" in name else name)
            table.add_row(domain_name if first else "", subdomain, example_name, desc)
            first = False

    if console:
        console.print(table)
        console.print(
            "[dim]Run an example: sagaz examples run <domain_folder>/<subdomain>/<name>[/dim]"
        )


def _display_examples_plain(by_domain: dict[str, dict[str, Path]]) -> None:
    """Display examples grouped by domain as plain text."""
    click.echo("  Domain              Subdomain         Name                  Description")
    click.echo("  " + "─" * 85)
    for domain_name, examples in by_domain.items():
        first = True
        for name, path in sorted(examples.items()):
            desc = get_example_description(path)
            domain_col = domain_name if first else ""
            parts = name.split("/")
            subdomain = parts[1] if len(parts) >= 3 else (parts[0] if len(parts) >= 2 else "")
            example_name = parts[2] if len(parts) >= 3 else (parts[-1] if "/" in name else name)
            click.echo(f"  {domain_col:<18}  {subdomain:<17}  {example_name:<20}  {desc}")
            first = False
