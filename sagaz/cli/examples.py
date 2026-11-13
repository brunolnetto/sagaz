"""
CLI module for discovering and running examples.

Discovery, the interactive menus and example execution live in private sibling
modules; their public names are re-exported here.
"""

from pathlib import Path

import click

from sagaz.cli._examples_discovery import (
    _SUBDOMAIN_TO_DOMAIN_FOLDER,
    DOMAIN_FOLDERS,
    DOMAIN_MAPPING,
    _check_subdomain_for_main_file,
    _collect_examples_by_subdomain,
    _find_example_files,
    discover_examples,
    discover_examples_by_domain,
    get_categories,
    get_domains,
    get_example_description,
    get_examples_dir,
)
from sagaz.cli._examples_menu import (
    TERM_MENU_AVAILABLE,
    TerminalMenu,
    _build_domain_menu,
    _build_example_menu_entries,
    _category_menu_loop,
    _domain_category_menu_loop,
    _examples_menu_loop,
    _format_category_name,
    _handle_menu_selection,
    _run_and_show_result,
    _show_category_header,
)
from sagaz.cli._examples_runner import (
    _check_package_installed,
    _check_requirements,
    _display_missing_packages,
    _execute_example,
    _parse_package_name,
    _prompt_user_continue,
)

try:
    from rich.console import Console
    from rich.table import Table

    console: Console | None = Console()
    TableClass: type[Table] | None = Table
except ImportError:
    console = None
    TableClass = None

__all__ = [
    "DOMAIN_FOLDERS",
    "DOMAIN_MAPPING",
    "TERM_MENU_AVAILABLE",
    "_SUBDOMAIN_TO_DOMAIN_FOLDER",
    "TableClass",
    "TerminalMenu",
    "_build_domain_menu",
    "_build_example_menu_entries",
    "_category_menu_loop",
    "_check_package_installed",
    "_check_requirements",
    "_check_subdomain_for_main_file",
    "_collect_examples_by_subdomain",
    "_display_missing_packages",
    "_domain_category_menu_loop",
    "_examples_menu_loop",
    "_execute_example",
    "_fallback_interactive_simple",
    "_find_example_files",
    "_format_category_name",
    "_handle_menu_selection",
    "_parse_package_name",
    "_prompt_user_continue",
    "_run_and_show_result",
    "_show_category_header",
    "console",
    "discover_examples",
    "discover_examples_by_domain",
    "examples_cli",
    "get_categories",
    "get_domains",
    "get_example_description",
    "get_examples_dir",
    "interactive_cmd",
    "list_examples_cmd",
    "run_example_cmd",
]


# ============================================================================
# CLI Group
# ============================================================================


@click.group(name="examples", invoke_without_command=True)
@click.pass_context
def examples_cli(ctx):
    """
    Explore and run Sagaz examples.
    """
    # If no subcommand provided, default to interactive selector
    if ctx.invoked_subcommand is None:
        interactive_cmd()


# ============================================================================
# Commands
# ============================================================================


@examples_cli.command(name="list")
@click.option("--domain", help="Filter by domain (e.g. Business, Technology)")
def list_examples(domain: str | None = None):
    """List available examples grouped by domain."""
    list_examples_cmd(domain)


@examples_cli.command(name="run")
@click.argument("name")
def run_example(name: str):
    """Run a specific example by name."""
    run_example_cmd(name)


@examples_cli.command(name="select")
@click.option("--category", help="Start in specific category")
def select_example(category: str | None = None):
    """Interactive example browser."""
    interactive_cmd(category)


def list_examples_cmd(domain: str | None = None):
    """List available examples grouped by domain."""
    by_domain = discover_examples_by_domain()

    if not by_domain:
        click.echo("No examples found.")
        return

    # Filter to specific domain if requested
    if domain:
        if domain not in by_domain:
            click.echo(f"Error: domain '{domain}' not found.")
            available = ", ".join(by_domain.keys())
            click.echo(f"Available domains: {available}")
            return
        by_domain = {domain: by_domain[domain]}

    if console and TableClass:
        _display_examples_table(by_domain)
    else:
        _display_examples_plain(by_domain)


def _show_no_examples_message(domain: str | None) -> None:
    """Show message when no examples are found."""
    if domain:
        click.echo(f"No examples found in domain '{domain}'.")
        domains = discover_examples_by_domain()
        if domains:
            click.echo(f"Available domains: {', '.join(domains.keys())}")
    else:
        click.echo("No examples found. Run this command from the sagaz repository root.")


def _example_display_parts(name: str) -> tuple[str, str]:
    """Extract the subdomain and display name from an example identifier."""
    parts = name.split("/")
    if len(parts) >= 3:
        return parts[1], parts[2]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return "", name


def _add_examples_table_rows(
    table,
    by_domain: dict[str, dict[str, Path]],
) -> None:
    """Add sorted example rows, grouping each domain under its first row."""
    for domain_name, examples in by_domain.items():
        first = True
        for name, path in sorted(examples.items()):
            subdomain, example_name = _example_display_parts(name)
            description = get_example_description(path)
            table.add_row(
                domain_name if first else "",
                subdomain,
                example_name,
                description,
            )
            first = False


def _display_examples_table(by_domain: dict[str, dict[str, Path]]) -> None:
    """Display examples grouped by domain in a rich table."""
    if TableClass is None:
        _display_examples_plain(by_domain)
        return

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

    _add_examples_table_rows(table, by_domain)

    if console:
        console.print(table)
        domains = discover_examples_by_domain()
        if domains:
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
            # name is domain_folder/subdomain/example
            parts = name.split("/")
            subdomain = parts[1] if len(parts) >= 3 else (parts[0] if len(parts) >= 2 else "")
            example_name = parts[2] if len(parts) >= 3 else (parts[-1] if "/" in name else name)
            click.echo(f"  {domain_col:<18}  {subdomain:<17}  {example_name:<20}  {desc}")
            first = False


def run_example_cmd(name: str):
    """Run a specific example."""
    by_domain = discover_examples_by_domain()

    # Flatten domain-grouped examples to search for name
    all_examples: dict[str, Path] = {}
    for examples in by_domain.values():
        all_examples.update(examples)

    if name not in all_examples:
        click.echo(f"Error: Example '{name}' not found.")
        click.echo("Use 'sagaz examples list' to see available examples.")
        return

    script_path = all_examples[name]
    click.echo(f"Running example: {name}...")
    click.echo(f"Script: {script_path}")
    click.echo("-" * 60)

    _execute_example(script_path)


def interactive_cmd(category: str | None = None):
    """Interactive example selection and execution with cascaded menus."""
    if not TERM_MENU_AVAILABLE:
        _fallback_interactive_simple(category)
        return

    if category:
        # Direct to examples in category
        _examples_menu_loop(category)
    else:
        # Start with category selection
        _category_menu_loop()


def _fallback_interactive_simple(category: str | None = None):
    """Fallback numbered menu when simple-term-menu is not available."""
    examples = discover_examples(category)
    if not examples:
        click.echo("No examples found.")
        return

    sorted_examples = sorted(examples.items())

    while True:
        click.echo("\n" + "=" * 50)
        click.echo("Available Examples:")
        click.echo("=" * 50)

        for idx, (name, path) in enumerate(sorted_examples, 1):
            desc = get_example_description(path)
            click.echo(f"  {idx}. {name}")
            click.echo(f"     {desc}")

        click.echo("\n  0. Exit")

        try:
            choice = click.prompt("\nEnter number to run", type=int, default=0)

            if choice == 0:
                click.echo("Goodbye!")
                return

            if 1 <= choice <= len(sorted_examples):
                name, path = sorted_examples[choice - 1]
                click.echo(f"\nRunning: {name}")
                click.echo("-" * 60)
                _execute_example(path)
                input("\nPress Enter to continue...")
            else:
                click.echo(f"Please enter a number between 0 and {len(sorted_examples)}")
        except (ValueError, click.Abort):
            return
