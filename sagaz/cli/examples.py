"""
CLI module for discovering and running examples.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

try:
    from rich.console import Console
    from rich.table import Table

    console = Console()
except ImportError:  # pragma: no cover
    console = None
    Table = None

try:
    from simple_term_menu import TerminalMenu

    TERM_MENU_AVAILABLE = True
except ImportError:  # pragma: no cover
    TERM_MENU_AVAILABLE = False
    TerminalMenu = None


def get_examples_dir() -> Path:
    """
    Get the directory containing examples.
    
    Priority:
    1. Current working directory (for development)
    2. Packaged examples inside sagaz.examples
    """
    import importlib.resources as pkg_resources
    
    # First check CWD for development
    cwd_examples = Path.cwd() / "examples"
    if cwd_examples.exists() and cwd_examples.is_dir():
        return cwd_examples  # pragma: no cover
    
    # Fall back to packaged examples
    try:
        return Path(str(pkg_resources.files("sagaz.examples")))
    except (ModuleNotFoundError, TypeError):  # pragma: no cover
        return cwd_examples  # Fallback if package not found


def get_categories() -> list[str]:
    """Get list of available example categories (top-level directories)."""
    examples_dir = get_examples_dir()
    if not examples_dir.exists():
        return []

    categories = []
    for item in examples_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            for _root, _, files in os.walk(item):
                if "main.py" in files:
                    categories.append(item.name)
                    break

    return sorted(categories)


def discover_examples(category: str | None = None) -> dict[str, Path]:
    """
    Scan examples directory for valid examples.

    Args:
        category: Optional category filter (e.g., 'ecommerce', 'fintech')

    Returns: Dict[example_name, path_to_main_py]
    """
    examples_dir = get_examples_dir()
    if not examples_dir.exists():
        return {}

    found = {}

    if category:
        search_dir = examples_dir / category
        if not search_dir.exists():
            return {}
    else:
        search_dir = examples_dir

    for root, _, files in os.walk(search_dir):
        if "main.py" in files:
            path = Path(root)
            try:
                rel_path = path.relative_to(examples_dir)
                name = str(rel_path).replace(os.sep, "/")
                found[name] = path / "main.py"
            except ValueError:  # pragma: no cover
                continue

    return found


def get_example_description(path: Path) -> str:
    """Extract description from example's main.py docstring."""
    try:
        with open(path) as f:
            first_line = f.readline().strip()
            if first_line.startswith(('"""', "'''")):
                desc = first_line.strip("\"'- ").strip()
                if not desc:
                    second_line = f.readline().strip()
                    desc = second_line
                return desc if desc else "No description"
    except Exception:
        pass
    return "No description"


def list_examples_cmd(category: str | None = None):
    """List available examples."""
    examples = discover_examples(category)

    if not examples:
        _show_no_examples_message(category)
        return

    if console and Table:
        _display_examples_table(examples, category)
    else:
        _display_examples_plain(examples)


def _show_no_examples_message(category: str | None) -> None:
    """Show message when no examples are found."""
    if category:
        click.echo(f"No examples found in category '{category}'.")
        categories = get_categories()
        if categories:
            click.echo(f"Available categories: {', '.join(categories)}")
    else:
        click.echo("No examples found. Run this command from the sagaz repository root.")


def _display_examples_table(examples: dict[str, Path], category: str | None) -> None:
    """Display examples as a rich table."""
    title = f"Sagaz Examples - {category}" if category else "Sagaz Examples"
    table = Table(title=title)
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    for name, path in sorted(examples.items()):
        desc = get_example_description(path)
        table.add_row(name, desc)

    console.print(table)

    categories = get_categories()
    if categories and not category:
        console.print(f"\n[dim]Filter by category: --category {{{','.join(categories)}}}[/dim]")


def _display_examples_plain(examples: dict[str, Path]) -> None:
    """Display examples as plain text."""
    click.echo("Available Examples:")
    for name in sorted(examples.keys()):
        click.echo(f"  - {name}")


def run_example_cmd(name: str):
    """Run a specific example."""
    examples = discover_examples()

    if name not in examples:
        click.echo(f"Error: Example '{name}' not found.")
        click.echo("Use 'sagaz examples list' to see available examples.")
        return

    script_path = examples[name]
    click.echo(f"Running example: {name}...")
    click.echo(f"Script: {script_path}")
    click.echo("-" * 60)

    _execute_example(script_path)


def interactive_cmd(category: str | None = None):
    """Interactive example selection and execution with cascaded menus."""
    if not TERM_MENU_AVAILABLE:  # pragma: no cover
        _fallback_interactive_simple(category)
        return

    if category:  # pragma: no cover
        # Direct to examples in category
        _examples_menu_loop(category)
    else:  # pragma: no cover
        # Start with category selection
        _category_menu_loop()


def _category_menu_loop():  # pragma: no cover
    """Main category selection loop."""
    categories = get_categories()

    if not categories:
        click.echo("No examples found. Run this command from the sagaz repository root.")
        return

    while True:
        if console:
            console.print("\n[bold blue]  📦 Sagaz Examples  [/bold blue]")
            console.print("[dim]Use ↑/↓ to navigate, Enter to select, q to quit[/dim]\n")

        # Build category menu with example counts
        menu_entries = []
        for cat in categories:
            examples = discover_examples(cat)
            count = len(examples)
            menu_entries.append(f"📁 {cat.title()}  ({count} examples)")

        menu_entries.append("")  # Separator
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
            # Exit selected or Ctrl+C
            if console:
                console.print("\n[dim]Goodbye! 👋[/dim]\n")
            return

        # Open examples submenu for selected category
        selected_category = categories[selected_index]
        result = _examples_menu_loop(selected_category)

        if result == "exit":
            if console:
                console.print("\n[dim]Goodbye! 👋[/dim]\n")
            return
        # Otherwise, loop back to category menu


def _examples_menu_loop(category: str) -> str:  # pragma: no cover
    """Examples selection loop for a specific category. Returns 'back' or 'exit'."""
    while True:
        examples = discover_examples(category)
        sorted_examples = sorted(examples.items())

        if not sorted_examples:
            if console:
                console.print(f"[yellow]No examples in {category}[/yellow]")
            return "back"

        _show_category_header(category)
        menu_entries = _build_example_menu_entries(sorted_examples)

        result = _handle_menu_selection(menu_entries, sorted_examples)
        if result in ("back", "exit"):
            return result
        # Loop continues after example runs


def _show_category_header(category: str) -> None:  # pragma: no cover
    """Display category header."""
    if console:
        console.print(f"\n[bold blue]  📁 {category.title()} Examples  [/bold blue]")
        console.print("[dim]Use ↑/↓ to navigate, Enter to select, q to quit[/dim]\n")


def _build_example_menu_entries(sorted_examples: list) -> list[str]:  # pragma: no cover
    """Build menu entries from examples."""
    menu_entries = []
    for name, path in sorted_examples:
        desc = get_example_description(path)
        if len(desc) > 40:
            desc = desc[:37] + "..."
        display_name = name.split("/")[-1] if "/" in name else name
        menu_entries.append(f"▶ {display_name}  │  {desc}")

    menu_entries.append("")  # Separator
    menu_entries.append("← Back to categories")
    menu_entries.append("❌ Exit")
    return menu_entries


def _handle_menu_selection(menu_entries: list[str], sorted_examples: list) -> str:  # pragma: no cover
    """Handle menu selection. Returns 'back', 'exit', or 'continue'."""
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

    if selected_index is None:
        return "back"
    if selected_index == len(menu_entries) - 2:
        return "back"
    if selected_index == len(menu_entries) - 1:
        return "exit"

    # Run selected example
    name, path = sorted_examples[selected_index]
    _run_and_show_result(name, path)
    return "continue"


def _run_and_show_result(name: str, path: Path) -> None:  # pragma: no cover
    """Run example and show completion message."""
    if console:
        console.print(f"\n[bold green]▸ Running:[/bold green] {name}")
        console.print("─" * 60)

    _execute_example(path)

    if console:
        console.print("\n[dim]" + "─" * 60 + "[/dim]")
        console.print("[bold cyan]Example completed![/bold cyan]")

    input("\nPress Enter to return to menu...")


def _fallback_interactive_simple(category: str | None = None):  # pragma: no cover
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


def _execute_example(script_path: Path):
    """Execute an example script."""
    env = os.environ.copy()
    cwd = Path.cwd()
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{cwd}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = str(cwd)

    try:
        subprocess.run([sys.executable, str(script_path)], env=env, check=True)
    except subprocess.CalledProcessError as e:
        click.echo(f"\nExample failed with exit code {e.returncode}")
    except KeyboardInterrupt:  # pragma: no cover
        click.echo("\nInterrupted.")
