"""
CLI module for discovering and running examples.
"""

import os
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


def get_examples_dir() -> Path:
    """
    Get the directory containing examples.

    Priority:
    1. Installed package (sagaz.examples) — works in both editable and
       regular installs.
    2. ``sagaz/examples/`` relative to the repository root detected from
       the current working directory — fallback for unusual setups.
    """
    import importlib.resources as pkg_resources

    # Prefer the installed package so discovery always finds all examples
    # regardless of where the user invokes the CLI from.
    try:
        pkg_path = Path(str(pkg_resources.files("sagaz.examples")))
        if pkg_path.exists() and any(
            p.is_dir() and not p.name.startswith("_") for p in pkg_path.iterdir()
        ):
            return pkg_path
    except (ModuleNotFoundError, TypeError):
        pass

    # Last resort: sagaz/examples/ relative to CWD (covers editable installs
    # where importlib.resources may resolve to a namespace package path).
    for candidate in (
        Path.cwd() / "sagaz" / "examples",
        Path.cwd() / "examples",
    ):
        if candidate.exists() and candidate.is_dir():
            return candidate

    return Path.cwd() / "sagaz" / "examples"  # non-existent; caller handles it


# Domain-to-category mapping — keys are the folder names under sagaz/examples/.
DOMAIN_MAPPING = {
    "Business": [
        "commerce",
        "finance",
    ],
    "Technology": [
        "ai",
        "data",
        "telecom",
        "iot",
    ],
    "Healthcare": [
        "healthcare",
    ],
    "Infrastructure": [
        "operations",
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
        "integrations",
        "monitoring",
        "visualization",
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


def _find_example_files(search_dir: Path, examples_dir: Path) -> dict[str, Path]:
    """Find example files in directory."""
    found = {}
    for root, _, files in os.walk(search_dir):
        if "main.py" in files or "demo.py" in files:
            path = Path(root)
            try:
                rel_path = path.relative_to(examples_dir)
                name = str(rel_path).replace(os.sep, "/")
                if "demo.py" in files and "integrations" in name:
                    found[name] = path / "demo.py"
                elif "main.py" in files:
                    found[name] = path / "main.py"
            except ValueError:
                continue
    return found


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

    search_dir = examples_dir / category if category else examples_dir
    if category and not search_dir.exists():
        return {}

    return _find_example_files(search_dir, examples_dir)


def discover_examples_by_domain() -> dict[str, dict[str, Path]]:
    """
    Discover all examples grouped by domain.

    Returns: {domain_name: {example_name: path_to_main_py}}
    """
    examples_dir = get_examples_dir()
    if not examples_dir.exists():
        return {}

    # Find all examples by category first
    all_examples: dict[str, list[tuple[str, Path]]] = {}
    for root, _, files in os.walk(examples_dir):
        if "main.py" in files or "demo.py" in files:
            path = Path(root)
            try:
                rel_path = path.relative_to(examples_dir)
                parts = rel_path.parts
                if len(parts) >= 2:
                    category = parts[0]
                    if category not in all_examples:
                        all_examples[category] = []

                    name = str(rel_path).replace(os.sep, "/")
                    if "demo.py" in files and "integrations" in name:
                        all_examples[category].append((name, path / "demo.py"))
                    elif "main.py" in files:
                        all_examples[category].append((name, path / "main.py"))
            except ValueError:
                continue

    # Group by domain
    by_domain: dict[str, dict[str, Path]] = {}
    for domain, categories in DOMAIN_MAPPING.items():
        domain_examples: dict[str, Path] = {}
        for category in categories:
            if category in all_examples:
                for name, path in all_examples[category]:
                    domain_examples[name] = path

        if domain_examples:
            by_domain[domain] = domain_examples

    return by_domain


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
            # Extract subdomain from name (part before the /)
            subdomain = name.split("/")[0] if "/" in name else ""
            # Extract example name (part after the /)
            example_name = name.split("/")[1] if "/" in name else name
            table.add_row(domain_name if first else "", subdomain, example_name, desc)
            first = False

    if console:
        console.print(table)
        domains = discover_examples_by_domain()
        if domains:
            console.print("[dim]Run an example: sagaz examples run <domain>/<category>/<name>[/dim]")


def _display_examples_plain(by_domain: dict[str, dict[str, Path]]) -> None:
    """Display examples grouped by domain as plain text."""
    click.echo("  Domain              Subdomain         Name                  Description")
    click.echo("  " + "─" * 85)
    for domain_name, examples in by_domain.items():
        first = True
        for name, path in sorted(examples.items()):
            desc = get_example_description(path)
            domain_col = domain_name if first else ""
            # Extract subdomain and name from full path
            subdomain = name.split("/")[0] if "/" in name else ""
            example_name = name.split("/")[1] if "/" in name else name
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


def _build_domain_menu(domains: dict) -> tuple[list[str], list[str]]:
    """Build domain menu entries."""
    menu_entries = []
    domain_list = list(domains.keys())
    for domain in domain_list:
        categories = domains[domain]
        total_count = sum(len(discover_examples(cat)) for cat in categories)
        menu_entries.append(f"📁 {domain}  ({total_count} examples)")

    menu_entries.append("")
    menu_entries.append("❌ Exit")
    return menu_entries, domain_list


def _category_menu_loop():
    """Main domain selection loop (consolidated categories)."""
    domains = get_domains()

    if not domains:
        click.echo("No examples found. Run this command from the sagaz repository root.")
        return

    while True:
        if console:
            console.print("\n[bold blue]  📦 Sagaz Examples  [/bold blue]")
            console.print("[dim]Use ↑/↓ to navigate, Enter to select, q to quit[/dim]\n")

        menu_entries, domain_list = _build_domain_menu(domains)

        menu = TerminalMenu(
            menu_entries,
            menu_cursor="▸ ",
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("bg_gray", "fg_cyan", "bold"),
            cycle_cursor=True,
            clear_screen=True,
            skip_empty_entries=True,
        )

        selected_index = menu.show()

        if selected_index is None or selected_index == len(menu_entries) - 1:
            if console:
                console.print("\n[dim]Goodbye! 👋[/dim]\n")
            return

        selected_domain = domain_list[selected_index]
        result = _domain_category_menu_loop(selected_domain, domains[selected_domain])

        if result == "exit":
            if console:
                console.print("\n[dim]Goodbye! 👋[/dim]\n")
            return


def _domain_category_menu_loop(domain: str, categories: list[str]) -> str:
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
            clear_screen=True,
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


def _examples_menu_loop(category: str) -> str:
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


def _show_category_header(category: str) -> None:
    """Display category header."""
    if console:
        formatted_name = _format_category_name(category)
        console.print(f"\n[bold blue]  📁 {formatted_name} Examples  [/bold blue]")
        console.print("[dim]Use ↑/↓ to navigate, Enter to select, q to quit[/dim]\n")


def _build_example_menu_entries(sorted_examples: list) -> list[str]:
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


def _handle_menu_selection(menu_entries: list[str], sorted_examples: list) -> str:
    """Handle menu selection. Returns 'back', 'exit', or 'continue'."""
    menu = TerminalMenu(
        menu_entries,
        menu_cursor="▸ ",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("bg_gray", "fg_cyan", "bold"),
        cycle_cursor=True,
        clear_screen=True,
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


def _run_and_show_result(name: str, path: Path) -> None:
    """Run example and show completion message."""
    if console:
        console.print(f"\n[bold green]▸ Running:[/bold green] {name}")
        console.print("─" * 60)

    _execute_example(path)

    if console:
        console.print("\n[dim]" + "─" * 60 + "[/dim]")
        console.print("[bold cyan]Example completed![/bold cyan]")

    input("\nPress Enter to return to menu...")


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


def _parse_package_name(req: str) -> str:
    """Extract package name from requirement string."""
    return req.split(">=")[0].split("==")[0].split("<")[0].split(">")[0].strip()


def _check_package_installed(pkg_name: str) -> bool:
    """Check if a package is installed."""
    import importlib.util

    package_to_import = {
        "python-dotenv": "dotenv",
        "pillow": "PIL",
        "opencv-python": "cv2",
        "scikit-learn": "sklearn",
        "beautifulsoup4": "bs4",
        "python-dateutil": "dateutil",
    }

    import_name = package_to_import.get(pkg_name, pkg_name)
    return importlib.util.find_spec(import_name) is not None


def _prompt_user_continue() -> bool:
    """Prompt user to continue despite missing packages."""
    response = input("\nContinue anyway? (y/N): ").strip().lower()
    return response in ("y", "yes")


def _display_missing_packages(missing_packages: list[str], requirements_file: Path):
    """Display missing packages to user."""
    if console:
        console.print("\n[yellow]⚠️  This example requires additional dependencies:[/yellow]")
        for pkg in missing_packages:
            console.print(f"   • {pkg}")
        console.print(f"\n[cyan]📦 Install with:[/cyan] pip install -r {requirements_file}")
    else:
        click.echo(f"\n⚠️  Missing dependencies: {', '.join(missing_packages)}")
        click.echo(f"Install with: pip install -r {requirements_file}")


def _check_requirements(requirements_file: Path, script_path: Path) -> None:
    """Check if required packages are installed and warn user."""
    try:
        with requirements_file.open() as f:
            reqs = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    except Exception:
        return

    missing_packages = []
    for req in reqs:
        if req.startswith("sagaz"):
            continue
        pkg_name = _parse_package_name(req)
        if not _check_package_installed(pkg_name):
            missing_packages.append(pkg_name)

    if not missing_packages:
        return

    _display_missing_packages(missing_packages, requirements_file)

    if not _prompt_user_continue():
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
    except KeyboardInterrupt:
        click.echo("\nInterrupted.")
