"""
CLI module for discovering and running built-in demonstrations.
"""

from __future__ import annotations

import subprocess
import sys
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

try:
    from simple_term_menu import TerminalMenu

    TERM_MENU_AVAILABLE = True
except ImportError:
    TERM_MENU_AVAILABLE = False
    TerminalMenu = None

from sagaz.demonstrations import (
    discover_demos,
    discover_demos_by_domain,
    discover_domains,
    get_demo_description,
    get_domain_for_demo,
)

# ============================================================================
# CLI Group
# ============================================================================


@click.group(name="demo", invoke_without_command=True)
@click.pass_context
def demo_cli(ctx):
    """
    Explore and run built-in Sagaz demonstrations.

    \b
    Demonstrations are organised into six domains:
        1  Core Patterns            — saga basics, parallelism, compensation
        2  Developer Experience     — dry-run, visualisation, lifecycle hooks
        3  Reliability & Recovery   — idempotency, snapshots, replay
        4  Orchestration & Config   — orchestrator, storage, event triggers
        5  Schema Evolution         — context migration, step versioning
        6  Framework Integrations   — FastAPI, outbox, metrics, Kubernetes

    \b
    Commands:
        list              List all demonstrations grouped by domain
        list --domain N   List only demonstrations in domain N (1-6)
        run <name>        Run a specific demonstration by name

    \b
    Examples:
        sagaz demo
        sagaz demo list
        sagaz demo list --domain core_patterns
        sagaz demo run basic_saga
        sagaz demo run context_migration
    """
    if ctx.invoked_subcommand is None:
        interactive_cmd()


# ============================================================================
# Commands
# ============================================================================


@demo_cli.command(name="list")
@click.option(
    "--domain",
    default=None,
    help="Filter to a specific domain folder name (e.g. core_patterns).",
)
def list_demos_cmd(domain: str | None):
    """List all available built-in demonstrations."""
    list_demos(filter_domain=domain)


@demo_cli.command(name="run")
@click.argument("name")
def run_demo_cmd(name: str):
    """Run a specific demonstration by name."""
    run_demo(name)


# ============================================================================
# Implementation helpers
# ============================================================================


def _domain_meta_index() -> dict[str, dict]:
    """Return {domain_name: metadata_dict} for fast look-ups."""
    return {m["name"]: m for m in discover_domains()}


def _validate_and_filter_domain(by_domain: dict, filter_domain: str | None) -> dict | None:
    """Validate filter_domain and return filtered domain dict, or None to exit."""
    if not filter_domain:
        return by_domain

    if filter_domain not in by_domain:
        click.echo(f"Error: domain '{filter_domain}' not found.")
        available = ", ".join(by_domain)
        click.echo(f"Available domains: {available}")
        return None

    return {filter_domain: by_domain[filter_domain]}


def _display_demos_table(by_domain: dict, meta_index: dict) -> None:
    """Display demonstrations using rich table format."""
    table = TableClass(
        title="Sagaz Demonstrations",
        show_header=True,
        header_style="bold magenta",
        expand=False,
    )
    table.add_column("Domain", style="bold", no_wrap=True, min_width=16)
    table.add_column("Name", style="cyan", no_wrap=True, min_width=24)
    table.add_column("Description", no_wrap=True, overflow="ellipsis")

    for domain_name, demos in by_domain.items():
        label = meta_index.get(domain_name, {}).get("short_label", domain_name)
        first = True
        for name, path in demos.items():
            desc = get_demo_description(path)
            table.add_row(label if first else "", name, desc)
            first = False

    console.print(table)
    console.print("[dim]Run a demonstration: sagaz demo run <name>[/dim]")


def _display_demos_plain(by_domain: dict, meta_index: dict) -> None:
    """Display demonstrations using plain text format."""
    click.echo(f"  {'Domain':<18}  {'Name':<25}  Description")
    click.echo("  " + "─" * 70)
    for domain_name, demos in by_domain.items():
        label = meta_index.get(domain_name, {}).get("short_label", domain_name)
        first = True
        for name, path in demos.items():
            desc = get_demo_description(path)
            domain_col = label if first else ""
            click.echo(f"  {domain_col:<18}  {name:<25}  {desc}")
            first = False
    click.echo("\nRun: sagaz demo run <name>")


def list_demos(filter_domain: str | None = None) -> None:
    """Display demonstrations grouped by domain."""
    by_domain = discover_demos_by_domain()

    if not by_domain:
        click.echo("No demonstrations found.")
        return

    by_domain = _validate_and_filter_domain(by_domain, filter_domain)
    if by_domain is None:
        return

    meta_index = _domain_meta_index()

    if console and TableClass:
        _display_demos_table(by_domain, meta_index)
    else:
        _display_demos_plain(by_domain, meta_index)


def run_demo(name: str) -> None:
    """Run a named demonstration."""
    demos = discover_demos()

    if name not in demos:
        click.echo(f"Error: Demonstration '{name}' not found.")
        click.echo("Use 'sagaz demo list' to see available demonstrations.")
        return

    script_path = demos[name]
    domain = get_domain_for_demo(name)
    domain_label = (
        _domain_meta_index().get(domain, {}).get("label", domain) if domain else "unknown"
    )

    if console:
        console.print(f"\n[bold blue]Running demonstration:[/bold blue] [cyan]{name}[/cyan]")
        console.print(f"[dim]Domain: {domain_label}[/dim]")
        console.print(f"[dim]Script: {script_path}[/dim]")
        console.print("-" * 60)
    else:
        click.echo(f"Running demonstration: {name}")
        click.echo(f"Domain: {domain_label}")
        click.echo(f"Script: {script_path}")
        click.echo("-" * 60)

    _execute_demo(script_path)


def interactive_cmd() -> None:
    """Interactive domain → demonstration selection."""
    if not TERM_MENU_AVAILABLE:
        _fallback_interactive()
        return
    _domain_menu_loop()


def _show_domain_menu(ordered_domains: list, by_domain: dict, meta_index: dict) -> int | None:
    """Show domain selection menu. Returns domain index or None if exiting."""
    if console:
        console.print("\n[bold blue]  🎬 Sagaz Demonstrations  [/bold blue]")
        console.print("[dim]Select a domain to explore[/dim]\n")

    domain_entries = []
    for domain in ordered_domains:
        label = meta_index.get(domain, {}).get("label", domain)
        count = len(by_domain[domain])
        domain_entries.append(f"  {label}  ({count} demos)")
    domain_entries.append("")
    domain_entries.append("❌ Exit")

    domain_menu = TerminalMenu(
        domain_entries,
        menu_cursor="▸ ",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("bg_gray", "fg_cyan", "bold"),
        cycle_cursor=True,
        clear_screen=False,
        skip_empty_entries=True,
    )
    return domain_menu.show()


def _show_demo_menu(demo_names: list, demos_in_domain: dict) -> int | None:
    """Show demo selection menu. Returns demo index or None if going back."""
    demo_entries = []
    for name in demo_names:
        desc = get_demo_description(demos_in_domain[name])
        demo_entries.append(f"  ▶  {name:<30} {desc}")
    demo_entries.append("")
    demo_entries.append("← Back to domains")

    demo_menu = TerminalMenu(
        demo_entries,
        menu_cursor="▸ ",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("bg_gray", "fg_cyan", "bold"),
        cycle_cursor=True,
        clear_screen=False,
        skip_empty_entries=True,
    )
    return demo_menu.show()


def _handle_domain_and_demo_selection(
    ordered_domains: list, by_domain: dict, meta_index: dict
) -> bool:
    """Handle one iteration: select domain, then demo. Returns True to continue, False to exit."""
    selected_domain_idx = _show_domain_menu(ordered_domains, by_domain, meta_index)

    if selected_domain_idx is None or selected_domain_idx >= len(ordered_domains):
        if console:
            console.print("\n[dim]Goodbye! 👋[/dim]\n")
        return False  # Exit

    domain = ordered_domains[selected_domain_idx]
    demos_in_domain = by_domain[domain]
    demo_names = list(demos_in_domain.keys())

    if console:
        label = meta_index.get(domain, {}).get("label", domain)
        console.print(f"\n[bold]{label}[/bold]")

    selected_demo_idx = _show_demo_menu(demo_names, demos_in_domain)

    if selected_demo_idx is None or selected_demo_idx >= len(demo_names):
        return True  # Back to domain selection

    run_demo(demo_names[selected_demo_idx])

    if not click.confirm("\nRun another demonstration?", default=True):
        if console:
            console.print("\n[dim]Goodbye! 👋[/dim]\n")
        return False  # Exit

    return True  # Continue


def _domain_menu_loop() -> None:
    """Two-level interactive menu: pick a domain then a demo."""
    by_domain = discover_demos_by_domain()
    if not by_domain:
        click.echo("No demonstrations found.")
        return

    meta_index = _domain_meta_index()
    ordered_domains = list(by_domain.keys())

    while _handle_domain_and_demo_selection(ordered_domains, by_domain, meta_index):
        pass


def _fallback_interactive() -> None:
    """Plain-text fallback when simple_term_menu is unavailable."""
    list_demos()
    name = click.prompt("\nEnter demonstration name to run (or press Enter to cancel)", default="")
    if name and name in discover_demos():
        run_demo(name)
    elif name:
        click.echo(f"Unknown demonstration: '{name}'")


def _execute_demo(script_path: Path) -> None:
    """Execute a demonstration script as a subprocess."""
    cmd = [sys.executable, str(script_path)]
    try:
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            click.echo(f"\nDemonstration exited with code {result.returncode}")
            raise SystemExit(result.returncode)
    except KeyboardInterrupt:
        click.echo("\nDemonstration interrupted.")
    except Exception as e:
        click.echo(f"Error running demonstration: {e}")
