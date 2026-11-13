"""Cascaded ``simple-term-menu`` browser for the Sagaz examples."""

from pathlib import Path

import click

from sagaz.cli._examples_discovery import discover_examples, get_domains, get_example_description
from sagaz.cli._examples_runner import _execute_example

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
