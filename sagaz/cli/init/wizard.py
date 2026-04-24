"""
Interactive wizard for project initialization.
"""

import sys
from pathlib import Path

import click

try:
    from rich.console import Console
    from rich.panel import Panel

    console: Console | None = Console()
except ImportError:
    console = None
    Panel = None

from sagaz.cli._init_handlers import _copy_example_saga


def _prompt_project_details() -> tuple[str, Path]:
    """Prompt user for project name and directory."""
    name = click.prompt("Project name", type=str)
    default_path = f"./{name}" if name else "."
    path = click.prompt("Project directory", type=str, default=default_path)
    return name, Path(path)


def _validate_project_directory(project_path: Path) -> None:
    """Validate and create project directory."""
    if (
        project_path.exists()
        and any(project_path.iterdir())
        and not click.confirm(
            f"Directory '{project_path}' already exists and is not empty. Continue?", default=False
        )
    ):
        click.echo("Aborted.")
        raise SystemExit(0)
    project_path.mkdir(parents=True, exist_ok=True)


def _prompt_example_choice() -> str | None:
    """Prompt user for example saga choice."""
    click.echo("\n[3] Would you like to include an example saga to get started?")
    click.echo("  1. None - Start with empty project")
    click.echo("  2. Simple example - Basic multi-step saga")
    click.echo("  3. E-commerce order - Order processing saga")
    click.echo("  4. Payment processing - Financial transaction saga")
    click.echo("  5. Healthcare procedure - Medical workflow saga")

    example_choice = click.prompt("Choice", type=click.IntRange(1, 5), default=2)
    example_map = {
        1: None,
        2: "simple",
        3: "ecommerce/order_processing",
        4: "fintech/payment_processing",
        5: "healthcare/procedure_scheduling",
    }
    return example_map[example_choice]


@click.command(name="init")
def init_wizard_cmd():
    """
    Initialize a new Sagaz project interactively.

    Interactive wizard to create a new project:
      - Project name and location
      - Optional example saga scaffold
      - Project structure (sagaz.yaml, profiles.yaml, sagas/, tests/)

    \b
    Example:
        sagaz init  # Interactive wizard
    """
    if console and Panel:
        console.print(
            Panel.fit(
                "[bold blue]Sagaz Project Initialization[/bold blue]\n"
                "Interactive wizard to create your project",
                border_style="blue",
            )
        )
    else:
        click.echo("=== Sagaz Project Initialization ===\n")

    name, project_path = _prompt_project_details()
    _validate_project_directory(project_path)
    example_template = _prompt_example_choice()

    if console:
        console.print(f"\n[bold green]Creating project: {name}[/bold green]")
    else:
        click.echo(f"\n=== Creating Project: {name} ===\n")

    # Create sagaz.yaml
    sagaz_yaml_content = f"""name: {name}
version: "0.1.0"
profile: default

paths:
  - sagas/

config:
  default_timeout: 60
  failure_strategy: FAIL_FAST_WITH_GRACE

observability:
  metrics:
    enabled: true
    port: 8000
  tracing:
    enabled: true
    exporter: jaeger
  logging:
    level: INFO
    format: json
"""
    (project_path / "sagaz.yaml").write_text(sagaz_yaml_content)
    click.echo(f"  CREATE {project_path / 'sagaz.yaml'}")

    # Create profiles.yaml
    profiles_yaml_content = """default:
  target: dev

dev:
  storage_url: "postgresql://sagaz:sagaz@localhost:5432/sagaz_dev"
  broker_url: "redis://localhost:6379/0"
  outbox_url: "postgresql://sagaz:sagaz@localhost:5432/sagaz_outbox"

  observability:
    metrics_port: 8000
    tracing_endpoint: "http://localhost:14268/api/traces"

dev_inmemory:
  storage_url: "memory://"
  broker_url: "redis://localhost:6379/0"
  outbox_url: "memory://"

  observability:
    metrics_port: 8000
    tracing_endpoint: "http://localhost:14268/api/traces"

prod:
  storage_url: "{{ env_var('SAGAZ_STORAGE_URL') }}"
  broker_url: "{{ env_var('SAGAZ_BROKER_URL') }}"
  outbox_url: "{{ env_var('SAGAZ_OUTBOX_URL') }}"

  observability:
    metrics_port: 8000
    tracing_endpoint: "{{ env_var('SAGAZ_TRACING_ENDPOINT') }}"
"""
    (project_path / "profiles.yaml").write_text(profiles_yaml_content)
    click.echo(f"  CREATE {project_path / 'profiles.yaml'}")

    # Create sagas/ directory with optional example
    sagas_dir = project_path / "sagas"
    sagas_dir.mkdir(exist_ok=True)
    (sagas_dir / "__init__.py").write_text("")
    click.echo(f"  CREATE {sagas_dir / '__init__.py'}")

    # Copy example saga if requested
    if example_template:
        _copy_example_saga(example_template, sagas_dir)
    else:
        # Create minimal placeholder
        placeholder = """from sagaz import Saga, action, SagaContext


class MySaga(Saga):
    \"\"\"
    Your saga implementation goes here.

    Define steps using @action decorator with dependencies.
    \"\"\"

    @action("step_one")
    async def step_one(self, ctx: SagaContext):
        \"\"\"Implement your first step.\"\"\"
        pass
"""
        (sagas_dir / "my_saga.py").write_text(placeholder)
        click.echo(f"  CREATE {sagas_dir / 'my_saga.py'}")

    # Create tests/ directory
    tests_dir = project_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("")
    click.echo(f"  CREATE {tests_dir / '__init__.py'}")

    test_example_content = """import pytest
from sagas.example_saga import ExampleSaga


@pytest.mark.asyncio
async def test_example_saga():
    \"\"\"Test the example saga.\"\"\"
    saga = ExampleSaga()
    result = await saga.run({})
    assert result["final"] == "done"
"""
    (tests_dir / "test_example_saga.py").write_text(test_example_content)
    click.echo(f"  CREATE {tests_dir / 'test_example_saga.py'}")

    # Create README.md
    readme_content = f"""# {name}

Sagaz project for orchestrating distributed transactions.

## Structure

```
{name}/
├── sagaz.yaml          # Project configuration
├── profiles.yaml       # Environment profiles (dev/prod)
├── sagas/              # Saga definitions
│   └── example_saga.py
└── tests/              # Test files
    └── test_example_saga.py
```

## Quick Start

1. **Validate sagas**: `sagaz validate`
2. **Simulate execution**: `sagaz simulate`
3. **Setup deployment**: `sagaz setup` (creates Docker Compose, K8s manifests, etc.)
4. **Start development**: `sagaz dev`

## Next Steps

- Edit `sagas/example_saga.py` or create new sagas
- Run `sagaz setup` to configure deployment environment
- Check `sagaz --help` for all commands
"""
    (project_path / "README.md").write_text(readme_content)
    click.echo(f"  CREATE {project_path / 'README.md'}")

    # Create .gitignore
    gitignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/

# Sagaz
.sagaz/
logs/

# Docker
docker-compose.override.yaml

# IDE
.vscode/
.idea/
*.swp
"""
    (project_path / ".gitignore").write_text(gitignore_content)
    click.echo(f"  CREATE {project_path / '.gitignore'}")

    display_path = project_path if str(project_path) != "." else name
    if console:
        console.print("\n[bold green]Project initialized successfully![/bold green]")
        console.print("\nNext steps:")
        console.print(f"  1. cd {display_path}")
        console.print("  2. Review and edit [bold cyan]sagas/example_saga.py[/bold cyan]")
        console.print("  3. Run [bold cyan]sagaz validate[/bold cyan] to validate your sagas")
        console.print("  4. Run [bold cyan]sagaz setup[/bold cyan] to configure deployment")
    else:
        click.echo("\nProject initialized successfully!")
        click.echo(f"  cd {display_path}")
        click.echo("  sagaz validate")
