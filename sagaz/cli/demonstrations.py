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

from sagaz.demonstrations import discover_demos, get_demo_description

# ============================================================================
# CLI Group
# ============================================================================


@click.group(name="demo", invoke_without_command=True)
@click.pass_context
def demo_cli(ctx):
    """
    Explore and run built-in Sagaz demonstrations.

    \b
    Commands:
        list      List all available demonstrations
        run       Run a specific demonstration by name

    \b
    Examples:
        sagaz demo                    # Opens interactive menu
        sagaz demo list
        sagaz demo run prometheus
        sagaz demo run idempotency
    """
    if ctx.invoked_subcommand is None:
        interactive_cmd()


# ============================================================================
# Commands
# ============================================================================


@demo_cli.command(name="list")
def list_demos_cmd():
    """List all available built-in demonstrations."""
    list_demos()


@demo_cli.command(name="run")
@click.argument("name")
def run_demo_cmd(name: str):
    """Run a specific demonstration by name."""
    run_demo(name)


# ============================================================================
# Implementation helpers
# ============================================================================


def list_demos():
    """Display available demonstrations."""
    demos = discover_demos()

    if not demos:
        click.echo("No demonstrations found.")
        return

    if console and TableClass:
        table = TableClass(title="Sagaz Built-in Demonstrations")
        table.add_column("Name", style="cyan")
        table.add_column("Description")

        for name, path in demos.items():
            desc = get_demo_description(path)
            table.add_row(name, desc)

        console.print(table)
        console.print("\n[dim]Run a demonstration: sagaz demo run <name>[/dim]")
    else:
        click.echo("Available Demonstrations:")
        for name, path in demos.items():
            desc = get_demo_description(path)
            click.echo(f"  {name:<25} {desc}")
        click.echo("\nRun: sagaz demo run <name>")


def run_demo(name: str):
    """Run a named demonstration."""
    demos = discover_demos()

    if name not in demos:
        click.echo(f"Error: Demonstration '{name}' not found.")
        click.echo("Use 'sagaz demo list' to see available demonstrations.")
        return

    script_path = demos[name]
    if console:
        console.print(f"\n[bold blue]Running demonstration:[/bold blue] [cyan]{name}[/cyan]")
        console.print(f"[dim]Script: {script_path}[/dim]")
        console.print("-" * 60)
    else:
        click.echo(f"Running demonstration: {name}")
        click.echo(f"Script: {script_path}")
        click.echo("-" * 60)

    _execute_demo(script_path)


def interactive_cmd():
    """Interactive demonstration selection and execution."""
    if not TERM_MENU_AVAILABLE:
        _fallback_interactive(None)
        return

    _demos_menu_loop()


def _demos_menu_loop():
    """Interactive menu loop for selecting and running a demonstration."""
    demos = discover_demos()

    if not demos:
        click.echo("No demonstrations found.")
        return

    demo_names = list(demos.keys())

    while True:
        if console:
            console.print("\n[bold blue]  🎬 Sagaz Demonstrations  [/bold blue]")
            console.print("[dim]Use ↑/↓ to navigate, Enter to select, q to quit[/dim]\n")

        menu_entries = []
        for name in demo_names:
            desc = get_demo_description(demos[name])
            menu_entries.append(f"▶  {name:<25} {desc}")
        menu_entries.append("")
        menu_entries.append("❌ Exit")

        menu = TerminalMenu(
            menu_entries,
            menu_cursor="▸ ",
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("bg_gray", "fg_cyan", "bold"),
            cycle_cursor=True,
            clear_screen=False,
            skip_empty_entries=True,
        )

        selected_index = menu.show()

        if selected_index is None or selected_index == len(menu_entries) - 1:
            if console:
                console.print("\n[dim]Goodbye! 👋[/dim]\n")
            return

        selected_name = demo_names[selected_index]
        run_demo(selected_name)

        if not click.confirm("\nRun another demonstration?", default=True):
            if console:
                console.print("\n[dim]Goodbye! 👋[/dim]\n")
            return


def _fallback_interactive(category):
    """Plain-text fallback when simple_term_menu is not available."""
    demos = discover_demos()
    if not demos:
        click.echo("No demonstrations found.")
        return

    list_demos()
    name = click.prompt("\nEnter demonstration name to run (or press Enter to cancel)", default="")
    if name and name in demos:
        run_demo(name)
    elif name:
        click.echo(f"Unknown demonstration: '{name}'")


def _execute_demo(script_path: Path):
    """Execute a demonstration script as a subprocess."""
    cmd = [sys.executable, str(script_path)]
    try:
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            click.echo(f"\nDemonstration exited with code {result.returncode}")
    except KeyboardInterrupt:
        click.echo("\nDemonstration interrupted.")
    except Exception as e:
        click.echo(f"Error running demonstration: {e}")
