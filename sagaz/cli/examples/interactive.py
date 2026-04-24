"""
Interactive menu logic for Sagaz examples.
"""

from pathlib import Path
import click

try:
    from rich.console import Console
    console: Console | None = Console()
except ImportError:
    console = None

try:
    from simple_term_menu import TerminalMenu
    TERM_MENU_AVAILABLE = True
except ImportError:
    TERM_MENU_AVAILABLE = False
    TerminalMenu = None

from .discovery import (
    get_domains, 
    discover_examples, 
    get_example_description
)
from .execution import execute_example


def _format_category_name(category: str) -> str:
    """Format category name with proper capitalization."""
    special_cases = {"iot": "IoT", "ml": "ML", "ai_agents": "AI Agents"}
    if category.lower() in special_cases:
        return special_cases[category.lower()]
    return " ".join(word.capitalize() for word in category.split("_"))


def interactive_cmd(category: str | None = None):
    """Interactive example selection and execution."""
    if not TERM_MENU_AVAILABLE:
        _fallback_interactive_simple(category)
        return

    if category:
        _examples_menu_loop(category)
    else:
        _category_menu_loop()


def _category_menu_loop():
    """Main domain selection loop."""
    domains = get_domains()
    if not domains:
        click.echo("No examples found.")
        return

    while True:
        if console:
            console.print("\n[bold blue]  📦 Sagaz Examples  [/bold blue]")
            console.print("[dim]Use ↑/↓ to navigate, Enter to select, q to quit[/dim]\n")

        menu_entries = []
        domain_list = list(domains.keys())
        for domain in domain_list:
            categories = domains[domain]
            total_count = sum(len(discover_examples(cat)) for cat in categories)
            menu_entries.append(f"📁 {domain}  ({total_count} examples)")
        menu_entries.append("")
        menu_entries.append("❌ Exit")

        menu = TerminalMenu(menu_entries, cycle_cursor=True, clear_screen=True)
        selected_index = menu.show()

        if selected_index is None or selected_index == len(menu_entries) - 1:
            return

        selected_domain = domain_list[selected_index]
        result = _domain_category_menu_loop(selected_domain, domains[selected_domain])
        if result == "exit":
            return


def _domain_category_menu_loop(domain: str, categories: list[str]) -> str:
    """Category selection loop for a domain."""
    while True:
        if console:
            console.print(f"\n[bold blue]  📁 {domain} Domain  [/bold blue]")

        menu_entries = []
        for cat in categories:
            count = len(discover_examples(cat))
            menu_entries.append(f"📂 {_format_category_name(cat)}  ({count} examples)")
        menu_entries.append("")
        menu_entries.append("← Back to domains")
        menu_entries.append("❌ Exit")

        menu = TerminalMenu(menu_entries, cycle_cursor=True, clear_screen=True)
        selected_index = menu.show()

        if selected_index == len(menu_entries) - 2: return "back"
        if selected_index is None or selected_index == len(menu_entries) - 1: return "exit"

        result = _examples_menu_loop(categories[selected_index])
        if result == "exit": return "exit"


def _prepare_example_menu_entries(sorted_examples: list[tuple[str, Path]]) -> list[str]:
    """Prepare menu entries for example selection."""
    menu_entries = []
    for name, path in sorted_examples:
        desc = get_example_description(path)
        display_name = name.split("/")[-1] if "/" in name else name
        menu_entries.append(f"▶ {display_name}  │  {desc[:37] + '...' if len(desc) > 40 else desc}")
    menu_entries.append("")
    menu_entries.append("← Back to categories")
    menu_entries.append("❌ Exit")
    return menu_entries


def _execute_selected_example(name: str, path: Path) -> None:
    """Execute the selected example and wait for user input."""
    if console:
        console.print(f"\n[bold green]▸ Running:[/bold green] {name}")
    execute_example(path)
    input("\nPress Enter to return to menu...")


def _examples_menu_loop(category: str) -> str:
    """Example selection loop for a category."""
    while True:
        examples = discover_examples(category)
        sorted_examples = sorted(examples.items())
        if not sorted_examples:
            return "back"

        if console:
            console.print(f"\n[bold blue]  📁 {_format_category_name(category)} Examples  [/bold blue]")

        menu_entries = _prepare_example_menu_entries(sorted_examples)
        menu = TerminalMenu(menu_entries, cycle_cursor=True, clear_screen=True)
        selected_index = menu.show()

        if selected_index is None or selected_index == len(menu_entries) - 2:
            return "back"
        if selected_index == len(menu_entries) - 1:
            return "exit"

        name, path = sorted_examples[selected_index]
        _execute_selected_example(name, path)


def _fallback_interactive_simple(category: str | None = None):
    """Fallback numbered menu."""
    examples = discover_examples(category)
    if not examples:
        click.echo("No examples found.")
        return

    sorted_examples = sorted(examples.items())
    while True:
        click.echo("\nAvailable Examples:")
        for idx, (name, path) in enumerate(sorted_examples, 1):
            click.echo(f"  {idx}. {name}")
        click.echo("\n  0. Exit")

        try:
            choice = click.prompt("\nEnter number to run", type=int, default=0)
            if choice == 0: return
            if 1 <= choice <= len(sorted_examples):
                name, path = sorted_examples[choice - 1]
                execute_example(path)
                input("\nPress Enter to continue...")
        except (ValueError, click.Abort):
            return
