import os
import sys
from pathlib import Path
from typing import Any

import click
import yaml

try:
    from rich.console import Console

    console = Console()
except ImportError:
    console = None


def echo(message: str, **kwargs):
    """Safe echo that renders rich markup if available, or falls back to click.echo."""
    if console:
        console.print(message, **kwargs)
    else:
        # Simple fallback: strip simple markup or just print
        # For now, just print using click (markup will be visible as text if rich is missing)
        click.echo(message)


# ============================================================================
# Constants & Templates
# ============================================================================

DEFAULT_SAGAZ_YAML = """name: {project_name}
version: "0.1.0"
profile: default

paths:
  - sagas/

config:
  default_timeout: 60
  failure_strategy: FAIL_FAST_WITH_GRACE
"""

DEFAULT_PROFILES_YAML = """default:
  target: dev

dev:
  storage_url: "postgresql://user:pass@localhost:5432/dev_db"
  broker_url: "redis://localhost:6379/0"

prod:
  storage_url: "{{ env_var('SAGAZ_STORAGE_URL') }}"
  broker_url: "{{ env_var('SAGAZ_BROKER_URL') }}"
"""

EXAMPLE_SAGA_PY = """from sagaz import Saga, action, SagaContext

class ExampleSaga(Saga):
    \"\"\"
    Example saga demonstrating a simple multi-step workflow.

    Steps:
    1. step_one: Prints a message
    2. step_two: Depends on step_one
    \"\"\"
    def __init__(self):
        super().__init__()

    @action("step_one")
    def step_one(self, ctx: SagaContext):
        print("Executing step one")
        return {"result": "success"}

    @action("step_two", depends_on=["step_one"])
    def step_two(self, ctx: SagaContext):
        print("Executing step two")
        return {"final": "done"}
"""

# ============================================================================
# Commands (Top-level, not in a group)
# ============================================================================


def _is_valid_saga_class(name: str, obj: Any) -> bool:
    """Check if object is a valid Saga subclass."""
    import inspect

    from sagaz import Saga

    return inspect.isclass(obj) and issubclass(obj, Saga) and obj is not Saga


def _inspect_module(module_name: str, file_path: Path) -> list[dict[str, Any]]:
    """Helper to inspect a module for Saga classes."""
    import importlib.util
    import inspect

    from sagaz import Saga

    discovered = []
    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if not (spec and spec.loader):
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        for name, obj in inspect.getmembers(module):
            if _is_valid_saga_class(name, obj):
                doc = inspect.getdoc(obj) or ""
                if doc == inspect.getdoc(Saga):
                    doc = "No description"

                first_line = doc.split("\n")[0] if doc else "No description"

                discovered.append(
                    {"name": name, "file": str(file_path), "doc": first_line, "class": obj}
                )
    except Exception:
        pass
    return discovered


def _iter_python_files(paths: list[str]):
    """Yield all valid Python files from given paths."""
    for path_str in paths:
        p = Path(path_str)
        if not p.exists():
            continue

        for file_path in p.rglob("*.py"):
            if not file_path.name.startswith("__"):
                yield file_path


def _discover_sagas(paths: list[str]) -> list[dict[str, Any]]:
    """
    Discover Saga classes in given paths.
    Returns a list of dicts with metadata.
    """
    discovered = []
    for file_path in _iter_python_files(paths):
        module_name = f"sagaz_user_code.{file_path.stem}"
        discovered.extend(_inspect_module(module_name, file_path))

    return discovered


@click.command()
def check():
    """
    Validate the Sagaz project structure and configuration.
    """
    if not Path("sagaz.yaml").exists():
        click.echo("Error: sagaz.yaml not found. Are you in a Sagaz project root?")
        sys.exit(1)

    try:
        config = yaml.safe_load(Path("sagaz.yaml").read_text())
    except Exception as e:
        click.echo(f"Error parsing sagaz.yaml: {e}")
        sys.exit(1)

    project_name = config.get("name", "unnamed")
    version = config.get("version", "0.0.0")
    echo(f"Checking project [bold cyan]{project_name}[/bold cyan] v{version}...")

    paths = config.get("paths", ["sagas/"])

    # 1. Check paths existence
    for path_str in paths:
        if not Path(path_str).exists():
            echo(f"  [yellow]Warning[/yellow]: Path '{path_str}' does not exist.")

    # 2. Try discovery
    sagas = _discover_sagas(paths)

    for s in sagas:
        echo(f"  - Found Saga: [green]{s['name']}[/green] in {s['file']}")

    echo(f"\n[bold green]Check complete![/bold green] Found {len(sagas)} sagas.")


@click.command(name="list")
def list_sagas():
    """
    List all discovered sagas in the project.
    """
    if not Path("sagaz.yaml").exists():
        click.echo("Error: sagaz.yaml not found.")
        sys.exit(1)

    config = yaml.safe_load(Path("sagaz.yaml").read_text())
    paths = config.get("paths", ["sagas/"])

    sagas = _discover_sagas(paths)

    if not sagas:
        click.echo("No sagas found.")
        return

    # Use Rich table if available
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()

        table = Table(title=f"Sagas in {config.get('name', 'Project')}")
        table.add_column("Saga Name", style="cyan")
        table.add_column("File", style="dim")
        table.add_column("Description")

        for s in sagas:
            table.add_row(s["name"], s["file"], s["doc"])

        console.print(table)
    except ImportError:
        # Fallback
        click.echo(f"{'SAGA NAME':<30} {'FILE':<40} {'DESCRIPTION'}")
        click.echo("-" * 100)
        for s in sagas:
            click.echo(f"{s['name']:<30} {s['file']:<40} {s['doc']}")
