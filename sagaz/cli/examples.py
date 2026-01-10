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

    console: Console | None = Console()
    TableClass: type[Table] | None = Table
except ImportError:  # pragma: no cover
    console = None
    TableClass = None

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


# Domain-to-category mapping for consolidated navigation
DOMAIN_MAPPING = {
    "Business": [
        "ecommerce",
        "fintech",
        "travel",
        "logistics",
        "real_estate",
    ],
    "Technology": [
        "ai_agents",
        "data_engineering",
        "ml",
        "iot",
    ],
    "Healthcare": ["healthcare"],
    "Infrastructure": [
        "energy",
        "manufacturing",
        "telecom",
    ],
    "Public Services": [
        "government",
        "education",
    ],
    "Digital Media": [
        "media",
        "gaming",
    ],
    "Platform": [
        "replay",
        "monitoring",
        "integrations",
    ],
}


def get_categories() -> list[str]:
    """Get list of available example categories (top-level directories)."""
    examples_dir = get_examples_dir()
    if not examples_dir.exists():
        return []

    categories = []
    for item in examples_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            for _root, _, files in os.walk(item):
                if "main.py" in files or "demo.py" in files:
                    categories.append(item.name)
                    break

    return sorted(categories)


def get_domains() -> dict[str, list[str]]:
    """Get consolidated domain groups with their categories."""
    available_cats = set(get_categories())
    domains = {}

    for domain, categories in DOMAIN_MAPPING.items():
        # Only include domains that have at least one available category
        present_cats = [cat for cat in categories if cat in available_cats]
        if present_cats:
            domains[domain] = present_cats

    return domains


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
        if "main.py" in files or "demo.py" in files:
            path = Path(root)
            try:
                rel_path = path.relative_to(examples_dir)
                name = str(rel_path).replace(os.sep, "/")
                # Prefer demo.py for integrations, otherwise use main.py
                if "demo.py" in files and "integrations" in name:
                    found[name] = path / "demo.py"
                elif "main.py" in files:
                    found[name] = path / "main.py"
            except ValueError:  # pragma: no cover
                continue

    return found


def get_example_description(path: Path) -> str:
    """Extract description from example's main.py docstring."""
    try:
        with path.open() as f:
            for line in f:
                stripped = line.strip()
                # Skip shebang and empty lines
                if stripped.startswith("#!") or not stripped:
                    continue
                # Found docstring
                if stripped.startswith(('"""', "'''")):
                    desc = stripped.strip("\"'- ").strip()
                    if not desc:
                        # Multi-line docstring, read next line
                        desc = f.readline().strip()
                    return desc if desc else "No description"
                # No docstring found
                break
    except Exception:
        pass
    return "No description"


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
@click.option("--category", help="Filter by category (e.g. ecommerce)")
def list_examples(category: str | None = None):
    """List available examples."""
    list_examples_cmd(category)


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


def list_examples_cmd(category: str | None = None):
    """List available examples."""
    examples = discover_examples(category)

    if not examples:
        _show_no_examples_message(category)
        return

    if console and TableClass:
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

    if console:
        console.print(table)

    categories = get_categories()
    if categories and not category and console:
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


def _format_category_name(category: str) -> str:
    """Format category name with proper capitalization."""
    # Special cases for acronyms
    special_cases = {
        "iot": "IoT",
        "ml": "ML",
        "ai_agents": "AI Agents",
    }

    if category.lower() in special_cases:
        return special_cases[category.lower()]

    # Default: replace underscores with spaces and title case each word
    return " ".join(word.capitalize() for word in category.split("_"))


def _category_menu_loop():  # pragma: no cover
    """Main domain selection loop (consolidated categories)."""
    domains = get_domains()

    if not domains:
        click.echo("No examples found. Run this command from the sagaz repository root.")
        return

    while True:
        if console:
            console.print("\n[bold blue]  📦 Sagaz Examples  [/bold blue]")
            console.print("[dim]Use ↑/↓ to navigate, Enter to select, q to quit[/dim]\n")

        # Build domain menu with example counts
        menu_entries = []
        domain_list = list(domains.keys())
        for domain in domain_list:
            categories = domains[domain]
            # Count total examples across all categories in domain
            total_count = sum(len(discover_examples(cat)) for cat in categories)
            menu_entries.append(f"📁 {domain}  ({total_count} examples)")

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

        # Open category submenu for selected domain
        selected_domain = domain_list[selected_index]
        result = _domain_category_menu_loop(selected_domain, domains[selected_domain])

        if result == "exit":
            if console:
                console.print("\n[dim]Goodbye! 👋[/dim]\n")
            return
        # Otherwise, loop back to domain menu


def _domain_category_menu_loop(domain: str, categories: list[str]) -> str:  # pragma: no cover
    """Category selection loop for a specific domain. Returns 'back' or 'exit'."""
    while True:
        if console:
            console.print(f"\n[bold blue]  📁 {domain} Domain  [/bold blue]")
            console.print("[dim]Use ↑/↓ to navigate, Enter to select, q to quit[/dim]\n")

        # Build category menu
        menu_entries = []
        for cat in categories:
            examples = discover_examples(cat)
            count = len(examples)
            formatted_name = _format_category_name(cat)
            menu_entries.append(f"📂 {formatted_name}  ({count} examples)")

        menu_entries.append("")  # Separator
        menu_entries.append("← Back to domains")
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

        # Handle back to domains
        if selected_index == len(menu_entries) - 2:
            return "back"

        # Handle exit
        if selected_index is None or selected_index == len(menu_entries) - 1:
            return "exit"

        # Open examples menu for selected category
        selected_category = categories[selected_index]
        result = _examples_menu_loop(selected_category)

        if result == "exit":
            return "exit"
        # Otherwise, loop back to category selection


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
        formatted_name = _format_category_name(category)
        console.print(f"\n[bold blue]  📁 {formatted_name} Examples  [/bold blue]")
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


def _handle_menu_selection(
    menu_entries: list[str], sorted_examples: list
) -> str:  # pragma: no cover
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


def _check_requirements(requirements_file: Path, script_path: Path) -> None:
    """Check if required packages are installed and warn user."""
    import importlib.util

    # Map package names to import names
    package_to_import = {
        "python-dotenv": "dotenv",
        "pillow": "PIL",
        "opencv-python": "cv2",
        "scikit-learn": "sklearn",
        "beautifulsoup4": "bs4",
        "python-dateutil": "dateutil",
    }

    # Read requirements and extract package names
    try:
        with requirements_file.open() as f:
            reqs = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    except Exception:  # pragma: no cover
        return

    missing_packages = []
    for req in reqs:
        # Extract package name (handle versions like 'package>=1.0.0')
        if req.startswith("sagaz"):
            continue  # Skip sagaz itself
        pkg_name = req.split(">=")[0].split("==")[0].split("<")[0].split(">")[0].strip()

        # Convert package name to import name
        import_name = package_to_import.get(pkg_name, pkg_name)

        if importlib.util.find_spec(import_name) is None:
            missing_packages.append(pkg_name)

    if missing_packages and console:
        console.print("\n[yellow]⚠️  This example requires additional dependencies:[/yellow]")
        for pkg in missing_packages:
            console.print(f"   • {pkg}")
        console.print(f"\n[cyan]📦 Install with:[/cyan] pip install -r {requirements_file}")
        response = input("\nContinue anyway? (y/N): ").strip().lower()
        if response not in ("y", "yes"):
            raise KeyboardInterrupt
    elif missing_packages:
        click.echo(f"\n⚠️  Missing dependencies: {', '.join(missing_packages)}")
        click.echo(f"Install with: pip install -r {requirements_file}")
        response = input("\nContinue anyway? (y/N): ").strip().lower()
        if response not in ("y", "yes"):
            raise KeyboardInterrupt


def _execute_example(script_path: Path):
    """Execute an example script."""
    # Check for requirements.txt and show installation hint if present
    requirements_file = script_path.parent / "requirements.txt"
    if requirements_file.exists():
        try:
            _check_requirements(requirements_file, script_path)
        except KeyboardInterrupt:
            if console:
                console.print("\n[yellow]Skipped example.[/yellow]")
            else:
                click.echo("\nSkipped example.")
            return

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
        if requirements_file.exists():
            click.echo("\n💡 This example may require additional dependencies.")
            click.echo(f"   Install them with: pip install -r {requirements_file}")
    except KeyboardInterrupt:  # pragma: no cover
        click.echo("\nInterrupted.")
