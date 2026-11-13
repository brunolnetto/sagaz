"""
Sagaz CLI Application - Built with Click.

This module contains the actual CLI commands for all deployment scenarios:
- Local development (Docker Compose)
- Self-hosted (on-premise servers)
- Cloud-native (Kubernetes)
- Hybrid deployments
- Benchmarking
"""

import subprocess
import sys
from pathlib import Path

import click

from sagaz.cli import examples as cli_examples
from sagaz.cli._init_handlers import _copy_example_saga
from sagaz.cli._setup_handlers import (
    _check_project_exists,
    _display_configuration_summary,
    _display_setup_header,
    _execute_setup,
    _gather_setup_configuration,
)
from sagaz.cli.demonstrations import demo_cli
from sagaz.cli.dlq import dlq_cli
from sagaz.cli.dry_run import simulate_cmd, validate_cmd
from sagaz.cli.migrate import migrate_cmd
from sagaz.cli.project import check as check_cmd
from sagaz.cli.project import list_sagas
from sagaz.cli.replay import replay
from sagaz.cli.visualize import visualize_cmd

try:
    from rich.console import Console
    from rich.panel import Panel
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
@click.version_option(package_name="sagaz", prog_name="sagaz")
def cli():
    """
    Sagaz - Production-ready Saga Pattern Orchestration.

    \b
    Commands by Progressive Risk:

    \b
    Library demo:
      examples         Explore examples
      demo             Run built-in demonstrations


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
    subprocess.run(cmd, check=False)


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
    subprocess.run(["docker", "compose", "down"], check=False)


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
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
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
        subprocess.run(["docker", "compose", "ps"], check=False)


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
    result = subprocess.run(cmd, capture_output=output is not None, check=False)

    if output and result.returncode == 0:
        Path(output).write_text(result.stdout.decode() if result.stdout else "", encoding="utf-8")
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
        with subprocess.Popen(cmd, stdout=subprocess.PIPE) as p1:
            with subprocess.Popen(["grep", saga_id], stdin=p1.stdout) as p2:
                p2.wait()
    else:
        subprocess.run(cmd, check=False)


# ============================================================================
# sagaz monitor
# ============================================================================

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::"})  # nosec B104 - used to detect wildcard binds


def _is_loopback(host: str) -> bool:
    return host.lower() in _LOOPBACK_HOSTS


def _url_host(host: str) -> str:
    """Bracket a bare IPv6 address for use inside an http:// URL."""
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


@click.command()
@click.option(
    "--ui",
    type=click.Choice(["web", "grafana"], case_sensitive=False),
    default="web",
    show_default=True,
    help="Dashboard backend.",
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Web dashboard bind address.",
)
@click.option(
    "--port",
    type=click.IntRange(1, 65535),
    default=7070,
    show_default=True,
    help="Web dashboard port.",
)
@click.option(
    "--advertise-host",
    default=None,
    metavar="HOST",
    help=(
        "Address advertised to Saga workers in export instructions. "
        "Defaults to the bind address (127.0.0.1 for wildcards)."
    ),
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Start the server without opening a browser.",
)
@click.option(
    "--storage-url",
    envvar="SAGAZ_STORAGE_URL",
    default=None,
    metavar="URL",
    help=(
        "Saga storage the /api/v1/analytics/* reports read from (read-only), e.g. "
        "postgresql://... or sqlite:///sagas.db. Requires sagaz[analytics]. "
        "Env: SAGAZ_STORAGE_URL."
    ),
)
@click.option(
    "--unsafe-expose",
    is_flag=True,
    help=(
        "Required when binding to a non-loopback address. Read endpoints remain unauthenticated."
    ),
)
def monitor_cmd(
    ui: str,
    host: str,
    port: int,
    advertise_host: str | None,
    no_browser: bool,
    unsafe_expose: bool,
    storage_url: str | None = None,
) -> None:
    """Start the Saga visualization dashboard or open Grafana."""
    import os
    import secrets

    if ui == "grafana":
        grafana_url = "http://localhost:3000"
        click.echo(f"Grafana dashboard: {grafana_url}")
        _maybe_open_browser(grafana_url, no_browser, announce=False)
        return

    _require_safe_bind(host, unsafe_expose)

    # Import here so the core CLI remains usable without visualization extras.
    from sagaz.visualization.server import run_server

    configured_token = os.environ.get("SAGAZ_VISUALIZATION_TOKEN")
    token = configured_token or secrets.token_urlsafe(32)
    dashboard_url = f"http://{_browser_host(host)}:{port}/"

    if not _is_loopback(host):
        click.echo(
            "WARNING: Read endpoints (dashboard, SSE stream, REST) are unauthenticated. "
            "Do not expose this server to untrusted networks without additional controls."
        )

    click.echo(f"Sagaz visualization dashboard: {dashboard_url}")

    if configured_token:
        click.echo(
            "SAGAZ_VISUALIZATION_TOKEN is already configured. "
            "Saga workers must inherit the same token."
        )
    else:
        _echo_worker_setup(host, port, advertise_host, token)

    _maybe_open_browser(dashboard_url, no_browser)
    run_server(host=host, port=port, event_token=token, analytics_storage_url=storage_url)


def _require_safe_bind(host: str, unsafe_expose: bool) -> None:
    if not _is_loopback(host) and not unsafe_expose:
        msg = (
            f"Binding to {host!r} exposes the dashboard beyond loopback. "
            "Read endpoints (dashboard, SSE stream, REST) are unauthenticated. "
            "Pass --unsafe-expose to acknowledge this limitation."
        )
        raise click.UsageError(msg)


def _browser_host(host: str) -> str:
    """Browser address: loopback for wildcard binds, bracketed for bare IPv6."""
    return "127.0.0.1" if host in _WILDCARD_HOSTS else _url_host(host)


def _worker_host(host: str, advertise_host: str | None) -> str:
    """Address advertised to Saga workers (distinct from the browser address)."""
    if advertise_host is not None:
        return _url_host(advertise_host)
    return _browser_host(host)


def _echo_worker_setup(host: str, port: int, advertise_host: str | None, token: str) -> None:
    if host in _WILDCARD_HOSTS and advertise_host is None:
        click.echo(
            "NOTE: Server binds to all interfaces. "
            "Workers on other hosts should use --advertise-host to override the URL below."
        )
    click.echo("Generated an event-ingestion token for this monitor process.")
    click.echo("Configure Saga workers with:")
    click.echo(f"export SAGAZ_VISUALIZATION_URL=http://{_worker_host(host, advertise_host)}:{port}")
    click.echo(f"export SAGAZ_VISUALIZATION_TOKEN={token}")
    click.echo("Then register VisualizationSagaListener.from_env() on each Saga class.")


def _maybe_open_browser(url: str, no_browser: bool, *, announce: bool = True) -> None:
    import webbrowser

    if not no_browser:
        webbrowser.open(url)
    elif announce:
        click.echo("Browser launch disabled.")


# ============================================================================
# sagaz version
# ============================================================================


@click.command()
def version_cmd():
    """Show version information."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("sagaz")
    except PackageNotFoundError:  # running from a source tree without installing
        installed = "unknown"
    click.echo(f"sagaz version {installed}")
    click.echo("Python " + sys.version.split()[0])


# ============================================================================
# sagaz examples
# ============================================================================
examples_cmd = cli_examples.examples_cli


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
cli.add_command(demo_cli, name="demo")

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
cli.add_command(visualize_cmd, name="visualize")

# DLQ Management
cli.add_command(dlq_cli, name="dlq")

# State Modification (Highest Risk)
cli.add_command(migrate_cmd, name="migrate")
cli.add_command(replay, name="replay")

if __name__ == "__main__":
    cli()
