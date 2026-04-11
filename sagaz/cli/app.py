"""
Sagaz CLI Application - Built with Click.

This module contains the actual CLI commands for all deployment scenarios:
- Local development (Docker Compose)
- Self-hosted (on-premise servers)
- Cloud-native (Kubernetes)
- Hybrid deployments
- Benchmarking
"""

import importlib.resources as pkg_resources
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

from sagaz.cli import examples as cli_examples
from sagaz.cli._init_handlers import (
    _copy_dir_resource,
    _copy_example_saga,
    _copy_resource,
    _init_benchmarks,
    _init_hybrid,
    _init_k8s,
    _init_local,
    _init_selfhost,
)
from sagaz.cli.dry_run import simulate_cmd, validate_cmd
from sagaz.cli.project import check as check_cmd
from sagaz.cli.project import list_sagas
from sagaz.cli.replay import replay

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    console: Console | None = Console()
except ImportError:
    console = None
    Panel = None  # type: ignore[assignment,misc]


# ============================================================================
# CLI Group
# ============================================================================


class OrderedGroup(click.Group):
    """Click Group that lists commands in the order they were added."""

    def list_commands(self, ctx):
        return list(self.commands.keys())

    def format_commands(self, ctx, formatter):
        """Override to hide the automatic Commands section."""
        # Do nothing - this prevents Click from adding the Commands list


@click.group(cls=OrderedGroup)
@click.version_option(version="1.0.3", prog_name="sagaz")
def cli():
    """
    Sagaz - Production-ready Saga Pattern Orchestration.

    \b
    Commands by Progressive Risk:

    \b
    Library demo:
      examples         Explore examples


    \b
    Project Management:
      init             Initialize new project
      setup            Setup deployment environment
      check            Validate project structure
      list             List discovered sagas
      validate         Validate project sagas
      simulate         Analyze execution DAG


    \b
    Runtime Operations:
      dev              Start local environment
      status           Check service health
      logs             View logs
      monitor          Open monitoring dashboard
      stop             Stop services
      replay           Replay/modify saga state
      benchmark        Run performance tests
    """


# ============================================================================
# sagaz init
# ============================================================================


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


@click.command()
def init_cmd():
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
    if console:
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


# ============================================================================
# sagaz setup
# ============================================================================


@click.command()
def setup_cmd():
    """Setup deployment environment interactively."""
    _check_project_exists()
    _display_setup_header()

    config = _gather_setup_configuration()
    _display_configuration_summary(config)

    if not click.confirm("\nProceed with setup?", default=True):
        click.echo("Aborted.")
        return

    _execute_setup(config)


def _check_project_exists():
    """Check if we're in a Sagaz project directory."""
    if not Path("sagaz.yaml").exists():
        click.echo("Error: Not in a Sagaz project directory.")
        click.echo("   Run 'sagaz init' first to create a project.")
        sys.exit(1)


def _display_setup_header():
    """Display setup wizard header."""
    if console:
        console.print(
            Panel.fit(
                "[bold blue]Sagaz Deployment Environment Setup[/bold blue]\n"
                "Interactive wizard to configure your deployment",
                border_style="blue",
            )
        )
    else:
        click.echo("=== Sagaz Deployment Environment Setup ===\n")


def _gather_setup_configuration() -> dict:
    """Gather configuration from user interactively."""
    config: dict[str, Any] = {}

    config["mode"] = _prompt_deployment_mode()
    config["oltp_storage"], config["with_ha"] = _prompt_oltp_storage(config["mode"])
    config["broker"] = _prompt_message_broker()
    config["outbox_storage"], config["separate_outbox"] = _prompt_outbox_storage()
    config["with_metrics"] = _prompt_metrics()
    config["with_tracing"] = _prompt_tracing()
    config["with_logging"] = _prompt_logging()
    config["with_benchmarks"] = _prompt_benchmarks()
    config["dev_mode"] = _determine_dev_mode(config["oltp_storage"], config["outbox_storage"])
    config["with_observability"] = (
        config["with_metrics"] or config["with_tracing"] or config["with_logging"]
    )

    return config


def _prompt_deployment_mode() -> str:
    """Prompt for deployment mode."""
    click.echo("\n[1/9] Select deployment mode:")
    click.echo("  1. local      - Docker Compose for development (recommended)")
    click.echo("  2. k8s        - Kubernetes for cloud-native")
    click.echo("  3. selfhost   - Systemd for on-premise servers")
    click.echo("  4. hybrid     - Local services + cloud broker")

    mode_choice: int = click.prompt("Choice", type=click.IntRange(1, 4), default=1)
    return ["local", "k8s", "selfhost", "hybrid"][mode_choice - 1]


def _prompt_oltp_storage(mode: str) -> tuple[str, bool]:
    """Prompt for OLTP storage and HA configuration."""
    click.echo("\n[2/9] Select OLTP storage (transaction data):")
    click.echo("  1. postgresql - Production-ready RDBMS (recommended)")
    click.echo("  2. in-memory  - Fast, no persistence (dev/testing only)")
    click.echo("  3. sqlite     - Simple file-based database")

    oltp_choice = click.prompt("Choice", type=click.IntRange(1, 3), default=1)
    oltp_storage = ["postgresql", "in-memory", "sqlite"][oltp_choice - 1]

    with_ha = False
    if oltp_storage == "postgresql" and mode in ["k8s", "selfhost"]:
        with_ha = click.confirm(
            "  Enable high-availability (primary + replicas + PgBouncer)?", default=False
        )

    return oltp_storage, with_ha


def _prompt_message_broker() -> str:
    """Prompt for message broker."""
    click.echo("\n[3/9] Select message broker:")
    click.echo("  1. redis      - Fast, simple (recommended)")
    click.echo("  2. rabbitmq   - Flexible routing, reliable")
    click.echo("  3. kafka      - High-throughput, event streaming")

    broker_choice: int = click.prompt("Choice", type=click.IntRange(1, 3), default=1)
    return ["redis", "rabbitmq", "kafka"][broker_choice - 1]


def _prompt_outbox_storage() -> tuple[str, bool]:
    """Prompt for outbox storage."""
    click.echo("\n[4/9] Select outbox storage (for reliable messaging):")
    click.echo("  1. same       - Use same database as OLTP (simplest)")
    click.echo("  2. postgresql - Separate PostgreSQL database")
    click.echo("  3. in-memory  - No persistence (dev/testing only)")

    outbox_choice = click.prompt("Choice", type=click.IntRange(1, 3), default=1)
    outbox_storage = ["same", "postgresql", "in-memory"][outbox_choice - 1]
    separate_outbox = outbox_storage != "same"

    return outbox_storage, separate_outbox


def _prompt_metrics() -> bool:
    """Prompt for metrics observability."""
    click.echo("\n[5/9] Observability - Metrics:")
    return click.confirm("  Include Prometheus + Grafana for metrics?", default=True)


def _prompt_tracing() -> bool:
    """Prompt for tracing observability."""
    click.echo("\n[6/9] Observability - Tracing:")
    return click.confirm("  Include Jaeger for distributed tracing?", default=True)


def _prompt_logging() -> bool:
    """Prompt for logging observability."""
    click.echo("\n[7/9] Observability - Logging:")
    return click.confirm("  Include Loki + Promtail for log aggregation?", default=True)


def _prompt_benchmarks() -> bool:
    """Prompt for benchmarks."""
    click.echo("\n[8/9] Benchmarks:")
    return click.confirm("  Include benchmark configuration?", default=False)


def _determine_dev_mode(oltp_storage: str, outbox_storage: str) -> bool:
    """Determine if development mode should be enabled."""
    click.echo("\n[9/9] Development mode:")
    if oltp_storage == "in-memory" or outbox_storage == "in-memory":
        click.echo("  [yellow]⚠ In-memory storage detected - enabling development mode[/yellow]")
        return True
    return click.confirm("  Enable in-memory mode (no external dependencies)?", default=False)


def _display_configuration_summary(config: dict):
    """Display configuration summary."""
    storage_label = config["oltp_storage"]
    if config["oltp_storage"] == "postgresql" and config["with_ha"]:
        storage_label = "postgresql (HA)"

    outbox_label = config["outbox_storage"]
    if config["outbox_storage"] == "same":
        outbox_label = f"same as OLTP ({config['oltp_storage']})"

    if console:
        console.print(
            f"\n[bold green]Configuration Summary:[/bold green]\n"
            f"  Mode: [cyan]{config['mode']}[/cyan]\n"
            f"  OLTP Storage: [yellow]{storage_label}[/yellow]\n"
            f"  Broker: [yellow]{config['broker']}[/yellow]\n"
            f"  Outbox Storage: [yellow]{outbox_label}[/yellow]\n"
            f"  Metrics: {'[green]Yes[/green]' if config['with_metrics'] else '[dim]No[/dim]'}\n"
            f"  Tracing: {'[green]Yes[/green]' if config['with_tracing'] else '[dim]No[/dim]'}\n"
            f"  Logging: {'[green]Yes[/green]' if config['with_logging'] else '[dim]No[/dim]'}\n"
            f"  Benchmarks: {'[green]Yes[/green]' if config['with_benchmarks'] else '[dim]No[/dim]'}\n"
            f"  Dev Mode: {'[yellow]Yes[/yellow]' if config['dev_mode'] else '[dim]No[/dim]'}"
        )
    else:
        click.echo(
            f"\nConfiguration: mode={config['mode']}, oltp={config['oltp_storage']}, "
            f"outbox={config['outbox_storage']}, broker={config['broker']}, "
            f"observability={config['with_observability']}, dev_mode={config['dev_mode']}"
        )


def _execute_setup(config: dict):
    """Execute setup based on configuration."""
    mode = config["mode"]

    if mode == "local":
        _init_local(
            config["broker"],
            config["with_observability"],
            config["with_ha"],
            config["separate_outbox"],
            config["oltp_storage"],
            config["outbox_storage"],
            config["dev_mode"],
        )
    elif mode == "selfhost":
        _init_selfhost(
            config["broker"],
            config["with_observability"],
            config["separate_outbox"],
            config["oltp_storage"],
            config["outbox_storage"],
        )
    elif mode == "k8s":
        _init_k8s(
            config["with_observability"],
            config["with_benchmarks"],
            config["with_ha"],
            config["separate_outbox"],
            config["oltp_storage"],
            config["outbox_storage"],
        )
    elif mode == "hybrid":
        _init_hybrid(config["broker"], config["oltp_storage"], config["outbox_storage"])

    if config["with_benchmarks"] and mode not in ["k8s"]:
        _init_benchmarks()


# ============================================================================
# sagaz dev
# ============================================================================


@click.command()
@click.option("-d", "--detach", is_flag=True, help="Run in background")
def dev_cmd(detach: bool):
    """
    Start local development environment.

    Requires docker-compose.yaml in current directory.
    Run 'sagaz init --local' first.
    """
    if not Path("docker-compose.yaml").exists():
        click.echo("docker-compose.yaml not found.")
        click.echo("   Run 'sagaz init --local' first.")
        sys.exit(1)

    cmd = ["docker", "compose", "up"]
    if detach:
        cmd.append("-d")

    click.echo("Starting development environment...")
    subprocess.run(cmd)


# ============================================================================
# sagaz stop
# ============================================================================


@click.command()
def stop_cmd():
    """Stop local development environment."""
    if not Path("docker-compose.yaml").exists():
        click.echo("docker-compose.yaml not found.")
        sys.exit(1)

    click.echo("Stopping development environment...")
    subprocess.run(["docker", "compose", "down"])


# ============================================================================
# sagaz status
# ============================================================================


@click.command()
def status_cmd():
    """Check health of all services."""
    click.echo("Checking service health...")
    click.echo("")

    if console:
        table = Table(title="Service Status")
        table.add_column("Service", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details")

        # Check Docker Compose services
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"], capture_output=True, text=True
        )

        if result.returncode == 0 and result.stdout.strip():
            import json

            try:
                services = json.loads(f"[{result.stdout.replace('}{', '},{')}]")
                for svc in services:
                    name = svc.get("Service", svc.get("Name", "unknown"))
                    state = svc.get("State", "unknown")
                    status_icon = "[green]●[/green]" if state == "running" else "[red]○[/red]"
                    table.add_row(name, f"{status_icon} {state}", "")
            except json.JSONDecodeError:
                table.add_row("docker-compose", "[yellow]○ parse error[/yellow]", "")
        else:
            table.add_row("docker-compose", "[red]○ not running[/red]", "Run 'sagaz dev'")

        console.print(table)
    else:
        subprocess.run(["docker", "compose", "ps"])


# ============================================================================
# sagaz benchmark
# ============================================================================


@click.command()
@click.option(
    "--profile",
    type=click.Choice(["local", "production", "stress", "full"]),
    default="local",
    help="Benchmark profile",
)
@click.option("--output", type=click.Path(), help="Output file for results (JSON)")
@click.option("--quick", is_flag=True, help="Quick sanity check (minimal iterations)")
def benchmark_cmd(profile: str, output: str, quick: bool):
    """
    Run performance benchmarks.

    \b
    Profiles:
        local       Fast tests for development (default)
        production  Comprehensive tests with production config
        stress      High concurrency and endurance tests
        full        All benchmark tests

    \b
    Examples:
        sagaz benchmark                  # Quick local tests
        sagaz benchmark --profile stress # Stress testing
        sagaz benchmark --output out.json # Save results
    """
    if console:
        console.print(
            Panel.fit(
                f"[bold blue]Sagaz Performance Benchmark[/bold blue]\n"
                f"Profile: [cyan]{profile}[/cyan]",
                border_style="blue",
            )
        )

    # Build pytest command
    cmd = ["python", "-m", "pytest", "tests/test_performance.py", "-v", "--tb=short"]

    if profile == "local":
        cmd.extend(["-m", "performance and not slow"])
    elif profile == "production":
        cmd.extend(["-m", "performance"])
    elif profile == "stress":
        cmd.extend(["-m", "stress"])
    # full = no marker filter

    if quick:
        # Override to minimal test
        cmd = [
            "python",
            "-c",
            """
import asyncio
from sagaz import Saga, action

class TestSaga(Saga):
    saga_name = "benchmark-quick"

    @action("step1")
    async def step1(self, ctx):
        return {"done": True}

async def main():
    import time
    start = time.perf_counter()
    for _ in range(10):
        saga = TestSaga()
        await saga.run({})
    elapsed = time.perf_counter() - start
    throughput = 10 / elapsed
    print(f"Quick benchmark: {throughput:.1f} sagas/sec")

asyncio.run(main())
""",
        ]

    # Run benchmark
    result = subprocess.run(cmd, capture_output=output is not None)

    if output and result.returncode == 0:
        Path(output).write_text(result.stdout.decode() if result.stdout else "")
        click.echo(f"Results saved to {output}")

    return result.returncode


# ============================================================================
# sagaz logs
# ============================================================================


@click.command()
@click.argument("saga_id", required=False)
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
@click.option("-s", "--service", help="Filter by service name")
def logs_cmd(saga_id: str, follow: bool, service: str):
    """
    View saga and service logs.

    \b
    Examples:
        sagaz logs              # All logs
        sagaz logs -f           # Follow logs
        sagaz logs -s worker    # Worker service only
        sagaz logs abc123       # Logs for specific saga ID
    """
    cmd = ["docker", "compose", "logs"]

    if follow:
        cmd.append("-f")

    if service:
        cmd.append(service)

    if saga_id:
        # Filter logs by saga ID using grep
        click.echo(f"Searching for saga: {saga_id}")
        p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        p2 = subprocess.Popen(["grep", saga_id], stdin=p1.stdout)
        p2.wait()
    else:
        subprocess.run(cmd)


# ============================================================================
# sagaz monitor
# ============================================================================


@click.command()
def monitor_cmd():
    """Open Grafana dashboard in browser."""
    import webbrowser

    grafana_url = "http://localhost:3000"
    click.echo(f"Opening Grafana: {grafana_url}")
    webbrowser.open(grafana_url)


# ============================================================================
# sagaz version
# ============================================================================


@click.command()
def version_cmd():
    """Show version information."""
    click.echo("sagaz version 1.0.3")
    click.echo("Python " + sys.version.split()[0])


# ============================================================================
# sagaz examples
# ============================================================================


@click.group(invoke_without_command=True)
@click.pass_context
def examples_cmd(ctx):
    """
    Manage and run examples.

    \b
    Commands:
        list      List all available examples
        run       Run a specific example by name

    \b
    Examples:
        sagaz examples                    # Opens interactive menu
        sagaz examples list
        sagaz examples list --category fintech
        sagaz examples run ecommerce/order_processing
    """
    if ctx.invoked_subcommand is None:
        cli_examples.interactive_cmd()


@examples_cmd.command("list")
@click.option(
    "--category",
    "-c",
    help="Filter by category (e.g., ecommerce, fintech, iot, ml)",
)
def list_examples(category: str):
    """
    List available examples.

    \b
    Examples:
        sagaz examples list
        sagaz examples list --category fintech
        sagaz examples list -c iot
    """
    cli_examples.list_examples_cmd(category)


@examples_cmd.command("run")
@click.argument("name")
def run_example(name: str):
    """
    Run a specific example by name.

    \b
    Example:
        sagaz examples run ecommerce/order_processing
        sagaz examples run monitoring
    """


# ============================================================================
# Command Registration (Progressive Risk Order)
# ============================================================================
# Commands appear in help in the order they're added to the group.
# We explicitly register all commands here in the desired order.

# Analysis/Validation (Read-only, zero risk)
cli.add_command(validate_cmd, name="validate")
cli.add_command(simulate_cmd, name="simulate")

# Project Management (Structure & Configuration)
cli.add_command(init_cmd, name="init")
cli.add_command(setup_cmd, name="setup")
cli.add_command(check_cmd, name="check")
cli.add_command(list_sagas, name="list")
cli.add_command(examples_cmd, name="examples")

# Development (Runtime Operations)
cli.add_command(dev_cmd, name="dev")
cli.add_command(status_cmd, name="status")
cli.add_command(logs_cmd, name="logs")
cli.add_command(monitor_cmd, name="monitor")
cli.add_command(stop_cmd, name="stop")

# Testing
cli.add_command(benchmark_cmd, name="benchmark")

# Utilities
cli.add_command(version_cmd, name="version")

# State Modification (Highest Risk)
cli.add_command(replay, name="replay")

if __name__ == "__main__":
    cli()
