"""
Sagaz CLI Application - Built with Click.

This module contains the actual CLI commands for all deployment scenarios:
- Local development (Docker Compose)
- Self-hosted (on-premise servers)
- Cloud-native (Kubernetes)
- Hybrid deployments
- Benchmarking

pragma: no cover - CLI is tested via manual/integration testing.
"""
# pragma: no cover

import importlib.resources as pkg_resources
import shutil
import subprocess
import sys
from pathlib import Path

import click

from sagaz.cli import examples as cli_examples
from sagaz.cli.dry_run import simulate_cmd, validate_cmd
from sagaz.cli.project import check as check_cmd, list_sagas
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
    
    # Step 1: Project name
    name = click.prompt("Project name", type=str)
    
    # Step 2: Project path
    default_path = f"./{name}" if name else "."
    path = click.prompt("Project directory", type=str, default=default_path)
    
    project_path = Path(path)
    
    # Check if directory exists and has content
    if project_path.exists() and any(project_path.iterdir()):
        if not click.confirm(f"Directory '{path}' already exists and is not empty. Continue?", default=False):
            click.echo("Aborted.")
            return
    
    project_path.mkdir(parents=True, exist_ok=True)
    
    # Step 3: Include example saga scaffold?
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
        5: "healthcare/procedure_scheduling"
    }
    
    example_template = example_map[example_choice]
    
    if console:
        console.print(
            f"\n[bold green]Creating project: {name}[/bold green]"
        )
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
    
    if console:
        console.print("\n[bold green]Project initialized successfully![/bold green]")
        console.print(f"\nNext steps:")
        console.print(f"  1. cd {project_path if path != '.' else name}")
        console.print(f"  2. Review and edit [bold cyan]sagas/example_saga.py[/bold cyan]")
        console.print(f"  3. Run [bold cyan]sagaz validate[/bold cyan] to validate your sagas")
        console.print(f"  4. Run [bold cyan]sagaz setup[/bold cyan] to configure deployment")
    else:
        click.echo(f"\nProject initialized successfully!")
        click.echo(f"  cd {project_path if path != '.' else name}")
        click.echo(f"  sagaz validate")


# ============================================================================
# sagaz setup
# ============================================================================


@click.command()
def setup_cmd():
    """
    Setup deployment environment interactively.
    
    \b
    Interactive wizard to configure:
    - Deployment mode (local/k8s/selfhost/hybrid)
    - OLTP storage (PostgreSQL with optional HA)
    - Message broker (redis/rabbitmq/kafka)
    - Outbox storage (same OLTP or separate)
    - Observability (Prometheus/Grafana/Jaeger)
    
    \b
    Example:
        sagaz setup  # Interactive wizard
    """
    # Check if we're in a sagaz project
    if not Path("sagaz.yaml").exists():
        click.echo("Error: Not in a Sagaz project directory.")
        click.echo("   Run 'sagaz init' first to create a project.")
        sys.exit(1)
    
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

    # Step 1: Deployment mode
    click.echo("\n[1/7] Select deployment mode:")
    click.echo("  1. local      - Docker Compose for development (recommended)")
    click.echo("  2. k8s        - Kubernetes for cloud-native")
    click.echo("  3. selfhost   - Systemd for on-premise servers")
    click.echo("  4. hybrid     - Local services + cloud broker")
    
    mode_choice = click.prompt("Choice", type=click.IntRange(1, 4), default=1)
    mode = ["local", "k8s", "selfhost", "hybrid"][mode_choice - 1]

    # Step 2: OLTP Storage
    click.echo("\n[2/9] Select OLTP storage (transaction data):")
    click.echo("  1. postgresql - Production-ready RDBMS (recommended)")
    click.echo("  2. in-memory  - Fast, no persistence (dev/testing only)")
    click.echo("  3. sqlite     - Simple file-based database")
    
    oltp_choice = click.prompt("Choice", type=click.IntRange(1, 3), default=1)
    oltp_storage = ["postgresql", "in-memory", "sqlite"][oltp_choice - 1]
    
    # Step 2b: HA for PostgreSQL
    with_ha = False
    if oltp_storage == "postgresql" and mode in ["k8s", "selfhost"]:
        with_ha = click.confirm("  Enable high-availability (primary + replicas + PgBouncer)?", default=False)
    
    # Step 3: Message broker
    click.echo("\n[3/9] Select message broker:")
    click.echo("  1. redis      - Fast, simple (recommended)")
    click.echo("  2. rabbitmq   - Flexible routing, reliable")
    click.echo("  3. kafka      - High-throughput, event streaming")
    
    broker_choice = click.prompt("Choice", type=click.IntRange(1, 3), default=1)
    broker = ["redis", "rabbitmq", "kafka"][broker_choice - 1]
    
    # Step 4: Outbox storage
    click.echo("\n[4/9] Select outbox storage (for reliable messaging):")
    click.echo("  1. same       - Use same database as OLTP (simplest)")
    click.echo("  2. postgresql - Separate PostgreSQL database")
    click.echo("  3. in-memory  - No persistence (dev/testing only)")
    
    outbox_choice = click.prompt("Choice", type=click.IntRange(1, 3), default=1)
    outbox_storage = ["same", "postgresql", "in-memory"][outbox_choice - 1]
    separate_outbox = (outbox_storage != "same")
    
    # Step 5: Observability - Metrics
    click.echo("\n[5/9] Observability - Metrics:")
    with_metrics = click.confirm("  Include Prometheus + Grafana for metrics?", default=True)
    
    # Step 6: Observability - Tracing
    click.echo("\n[6/9] Observability - Tracing:")
    with_tracing = click.confirm("  Include Jaeger for distributed tracing?", default=True)
    
    # Step 7: Observability - Logging
    click.echo("\n[7/9] Observability - Logging:")
    with_logging = click.confirm("  Include Loki + Promtail for log aggregation?", default=True)
    
    # Step 8: Benchmarks
    click.echo("\n[8/9] Benchmarks:")
    with_benchmarks = click.confirm("  Include benchmark configuration?", default=False)
    
    # Step 9: Development mode
    click.echo("\n[9/9] Development mode:")
    dev_mode = False
    if oltp_storage == "in-memory" or outbox_storage == "in-memory":
        dev_mode = True
        click.echo("  [yellow]⚠ In-memory storage detected - enabling development mode[/yellow]")
    else:
        dev_mode = click.confirm("  Enable in-memory mode (no external dependencies)?", default=False)

    # Summary
    with_observability = with_metrics or with_tracing or with_logging
    
    if console:
        storage_label = oltp_storage
        if oltp_storage == "postgresql" and with_ha:
            storage_label = "postgresql (HA)"
        
        outbox_label = outbox_storage if outbox_storage != "same" else f"same as OLTP ({oltp_storage})"
        
        console.print(
            f"\n[bold green]Configuration Summary:[/bold green]\n"
            f"  Mode: [cyan]{mode}[/cyan]\n"
            f"  OLTP Storage: [yellow]{storage_label}[/yellow]\n"
            f"  Broker: [yellow]{broker}[/yellow]\n"
            f"  Outbox Storage: [yellow]{outbox_label}[/yellow]\n"
            f"  Metrics: {'[green]Yes[/green]' if with_metrics else '[dim]No[/dim]'}\n"
            f"  Tracing: {'[green]Yes[/green]' if with_tracing else '[dim]No[/dim]'}\n"
            f"  Logging: {'[green]Yes[/green]' if with_logging else '[dim]No[/dim]'}\n"
            f"  Benchmarks: {'[green]Yes[/green]' if with_benchmarks else '[dim]No[/dim]'}\n"
            f"  Dev Mode: {'[yellow]Yes[/yellow]' if dev_mode else '[dim]No[/dim]'}"
        )
    else:
        click.echo(
            f"\nConfiguration: mode={mode}, oltp={oltp_storage}, "
            f"outbox={outbox_storage}, broker={broker}, "
            f"observability={with_observability}, dev_mode={dev_mode}"
        )

    if not click.confirm("\nProceed with setup?", default=True):
        click.echo("Aborted.")
        return

    # Execute initialization
    if mode == "local":
        _init_local(
            broker, 
            with_observability, 
            with_ha, 
            separate_outbox, 
            oltp_storage,
            outbox_storage,
            dev_mode
        )
    elif mode == "selfhost":
        _init_selfhost(broker, with_observability, separate_outbox, oltp_storage, outbox_storage)
    elif mode == "k8s":
        _init_k8s(with_observability, with_benchmarks, with_ha, separate_outbox, oltp_storage, outbox_storage)
    elif mode == "hybrid":
        _init_hybrid(broker, oltp_storage, outbox_storage)

    if with_benchmarks and mode not in ["k8s"]:
        _init_benchmarks()


def _init_local(
    broker: str, 
    with_observability: bool, 
    with_ha: bool = False, 
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same",
    dev_mode: bool = False
):
    """Create local Docker Compose setup."""
    _log_local_init_start(broker, with_ha, oltp_storage, dev_mode)

    # 1. Create docker-compose.yaml
    _init_docker_compose(broker, with_ha, with_observability, separate_outbox, oltp_storage, outbox_storage, dev_mode)

    # 2. Copy monitoring folder if enabled
    if with_observability:
        _init_monitoring(broker, with_ha)

    _log_local_init_complete(with_observability, with_ha, dev_mode)


def _log_local_init_start(broker: str, with_ha: bool, oltp_storage: str, dev_mode: bool):
    """Log the start of local initialization."""
    if not console:
        return
    
    if dev_mode:
        console.print(
            "Creating [bold yellow]in-memory development[/bold yellow] environment (no external dependencies)..."
        )
    elif with_ha:
        console.print(
            "Creating local HA PostgreSQL environment with [bold green]primary + replica + PgBouncer[/bold green]..."
        )
    else:
        console.print(
            f"Creating local development environment (storage: [bold green]{oltp_storage}[/bold green], broker: [bold green]{broker}[/bold green])..."
        )


def _init_docker_compose(
    broker: str, 
    with_ha: bool, 
    with_observability: bool = True, 
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same",
    dev_mode: bool = False
):
    """Initialize docker-compose.yaml with optional overwrite confirmation."""
    target = "docker-compose.yaml"

    if Path(target).exists() and not click.confirm(f"{target} already exists. Overwrite?"):
        click.echo(f"Skipping {target}")
        return

    _copy_docker_compose_files(broker, with_ha, with_observability, separate_outbox, oltp_storage, outbox_storage, dev_mode)


def _copy_docker_compose_files(
    broker: str, 
    with_ha: bool, 
    with_observability: bool = True, 
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same",
    dev_mode: bool = False
):
    """Copy the appropriate docker-compose files."""
    if dev_mode:
        # Create minimal in-memory docker-compose
        _create_inmemory_docker_compose(broker)
    elif with_ha:
        _copy_resource("local/postgres-ha/docker-compose.yaml", "docker-compose.yaml")
        _copy_resource("local/postgres-ha/init-primary.sh", "init-primary.sh")
        _copy_dir_resource("local/postgres-ha/partitioning", "partitioning")
    else:
        _copy_resource(f"local/{broker}/docker-compose.yaml", "docker-compose.yaml")
    
    # TODO: Add observability services to docker-compose if with_observability
    # TODO: Add separate outbox database if separate_outbox


def _create_inmemory_docker_compose(broker: str):
    """Create a minimal docker-compose for in-memory development."""
    content = f"""version: '3.8'

services:
  # Message broker only - everything else runs in-memory
  {broker}:
    image: {"redis:7-alpine" if broker == "redis" else "rabbitmq:3-management" if broker == "rabbitmq" else "confluentinc/cp-kafka:latest"}
    ports:
      - "{6379 if broker == 'redis' else 5672 if broker == 'rabbitmq' else 9092}:{6379 if broker == 'redis' else 5672 if broker == 'rabbitmq' else 9092}"
    environment:
      {"ALLOW_ANONYMOUS_LOGIN: 'yes'" if broker == 'redis' else "RABBITMQ_DEFAULT_USER: sagaz" if broker == 'rabbitmq' else "KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092"}
      {"" if broker == 'redis' else "RABBITMQ_DEFAULT_PASS: sagaz" if broker == 'rabbitmq' else "KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181"}

networks:
  sagaz:
    driver: bridge
"""
    Path("docker-compose.yaml").write_text(content)
    click.echo(f"  CREATE docker-compose.yaml")


def _init_monitoring(broker: str, with_ha: bool):
    """Copy monitoring configuration."""
    if with_ha:
        _copy_dir_resource("local/postgres-ha/monitoring", "monitoring")
    else:
        _copy_dir_resource(f"local/{broker}/monitoring", "monitoring")


def _log_local_init_complete(with_observability: bool, with_ha: bool, dev_mode: bool):
    """Log completion message for local initialization."""
    if not console:
        return

    console.print("\n[bold green]Deployment setup complete![/bold green]")
    
    if dev_mode:
        console.print("\n[bold yellow]Development Mode Active:[/bold yellow]")
        console.print("  - OLTP and Outbox storage run [bold]in-memory[/bold]")
        console.print("  - No data persistence between restarts")
        console.print("  - Fastest startup, ideal for testing")
    
    console.print("\nNext steps:")
    console.print("  1. Run [bold cyan]sagaz dev[/bold cyan] to start the services")
    console.print("  2. Check status with [bold cyan]sagaz status[/bold cyan]")
    if with_observability:
        console.print("  3. Open monitoring at http://localhost:3000")
    if with_ha:
        console.print("\n[bold yellow]HA PostgreSQL Info:[/bold yellow]")
        console.print("  - Primary (writes): localhost:5432")
        console.print("  - Replica (reads): localhost:5433")
        console.print("  - PgBouncer-RW: localhost:6432")
        console.print("  - PgBouncer-RO: localhost:6433")


def _init_selfhost(
    broker: str, 
    with_observability: bool, 
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same"
):
    """Create self-hosted/on-premise server setup."""
    if console:
        console.print("Creating self-hosted deployment files...")

    # Create selfhost directory
    Path("selfhost").mkdir(exist_ok=True)

    # Create systemd service files
    _create_systemd_service("sagaz-worker", "Sagaz Outbox Worker", "python -m sagaz.outbox.worker")

    # Create environment file
    env_content = f"""# Sagaz Environment Configuration
# Copy to /etc/sagaz/sagaz.env

# OLTP Database
POSTGRES_URL=postgresql://sagaz:sagaz@localhost:5432/sagaz

# Outbox Database {"(separate)" if separate_outbox else "(same as OLTP)"}
{"OUTBOX_URL=postgresql://sagaz:sagaz@localhost:5432/sagaz_outbox" if separate_outbox else "# OUTBOX_URL=$POSTGRES_URL"}

# Broker ({broker})
BROKER_TYPE={broker}
"""
    if broker == "redis":
        env_content += "REDIS_URL=redis://localhost:6379\n"
    elif broker == "kafka":
        env_content += "KAFKA_BOOTSTRAP_SERVERS=localhost:9092\n"
    elif broker == "rabbitmq":
        env_content += "RABBITMQ_URL=amqp://guest:guest@localhost:5672\n"

    env_content += """
# Observability
SAGAZ_METRICS_PORT=8000
SAGAZ_LOG_LEVEL=INFO
SAGAZ_LOG_JSON=true
"""
    
    if with_observability:
        env_content += "SAGAZ_TRACING_ENDPOINT=http://localhost:14268/api/traces\n"

    Path("selfhost/sagaz.env").write_text(env_content)
    click.echo("  CREATE selfhost/sagaz.env")

    # Create installation script
    install_script = """#!/bin/bash
# Sagaz Self-Hosted Installation Script

set -e

echo "Installing Sagaz..."

# Create directories
sudo mkdir -p /etc/sagaz
sudo mkdir -p /var/log/sagaz

# Copy environment file
sudo cp sagaz.env /etc/sagaz/

# Copy systemd services
sudo cp *.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable sagaz-worker

echo "Installation complete!"
echo "Start with: sudo systemctl start sagaz-worker"
"""
    Path("selfhost/install.sh").write_text(install_script)
    Path("selfhost/install.sh").chmod(0o755)
    click.echo("  CREATE selfhost/install.sh")

    if with_observability:
        _create_selfhost_monitoring()

    if console:
        console.print("\n[bold green]Self-hosted setup complete![/bold green]")
        console.print("Next steps:")
        console.print("  1. Edit [bold cyan]selfhost/sagaz.env[/bold cyan]")
        console.print("  2. Run [bold cyan]cd selfhost && ./install.sh[/bold cyan]")


def _create_systemd_service(name: str, description: str, exec_start: str):
    """Create a systemd service file."""
    service = f"""[Unit]
Description={description}
After=network.target postgresql.service

[Service]
Type=simple
User=sagaz
Group=sagaz
EnvironmentFile=/etc/sagaz/sagaz.env
ExecStart=/usr/local/bin/{exec_start}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    Path(f"selfhost/{name}.service").write_text(service)
    click.echo(f"  CREATE selfhost/{name}.service")


def _create_selfhost_monitoring():
    """Create monitoring config for self-hosted setup."""
    # Prometheus config
    prom_config = """global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'sagaz'
    static_configs:
      - targets: ['localhost:8000']
"""
    Path("selfhost/prometheus.yml").write_text(prom_config)
    click.echo("  CREATE selfhost/prometheus.yml")


def _init_k8s(
    with_observability: bool, 
    with_benchmarks: bool, 
    with_ha: bool = False, 
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same"
):
    """Copy Kubernetes manifests from the library to the current directory."""
    _log_k8s_init_start(with_ha, oltp_storage)

    if not _prepare_k8s_directory():
        return

    try:
        _copy_k8s_manifests(with_ha, separate_outbox, oltp_storage)
        _copy_k8s_observability(with_observability)
        _copy_k8s_benchmarks(with_benchmarks)
        _log_k8s_init_complete(with_ha)
    except Exception as e:
        click.echo(f"Error copying manifests: {e}")


def _log_k8s_init_start(with_ha: bool, oltp_storage: str):
    """Log the start of K8s initialization."""
    if not console:
        return
    ha_msg = " with [bold yellow]HA PostgreSQL[/bold yellow]" if with_ha else ""
    console.print(f"Copying Kubernetes manifests{ha_msg} (storage: [bold cyan]{oltp_storage}[/bold cyan]) to [bold cyan]./k8s[/bold cyan]...")


def _prepare_k8s_directory() -> bool:
    """Prepare k8s directory, prompting for overwrite if exists. Returns False to abort."""
    if Path("k8s").exists():
        if not click.confirm(
            "Directory [bold yellow]k8s/[/bold yellow] already exists. Overwrite?"
        ):
            click.echo("Aborted.")
            return False
        shutil.rmtree("k8s")
    Path("k8s").mkdir(exist_ok=True)
    return True


def _copy_k8s_manifests(with_ha: bool, separate_outbox: bool = False, oltp_storage: str = "postgresql"):
    """Copy base Kubernetes manifests."""
    if oltp_storage == "postgresql":
        if with_ha:
            _copy_resource("k8s/postgresql-ha.yaml", "k8s/postgresql-ha.yaml")
            _copy_resource("k8s/pgbouncer.yaml", "k8s/pgbouncer.yaml")
            click.echo("  CREATE k8s/postgresql-ha.yaml (StatefulSet with replicas)")
            click.echo("  CREATE k8s/pgbouncer.yaml (Connection pooling)")
            Path("k8s/partitioning").mkdir(exist_ok=True)
            _copy_dir_resource("local/postgres/partitioning", "k8s/partitioning")
        else:
            _copy_resource("k8s/postgresql.yaml", "k8s/postgresql.yaml")
    elif oltp_storage == "in-memory":
        click.echo("  SKIP postgresql (using in-memory storage)")
    
    # Separate outbox database if requested
    if separate_outbox:
        _copy_resource("k8s/outbox-postgresql.yaml", "k8s/outbox-postgresql.yaml")
        click.echo("  CREATE k8s/outbox-postgresql.yaml (Separate outbox database)")

    # Copy base manifests
    for manifest in [
        "outbox-worker.yaml",
        "configmap.yaml",
        "secrets-example.yaml",
        "migration-job.yaml",
    ]:
        _copy_resource(f"k8s/{manifest}", f"k8s/{manifest}")


def _copy_k8s_observability(with_observability: bool):
    """Copy K8s observability manifests if enabled."""
    if with_observability:
        _copy_resource("k8s/prometheus-monitoring.yaml", "k8s/prometheus-monitoring.yaml")
        _copy_resource("k8s/jaeger-tracing.yaml", "k8s/jaeger-tracing.yaml")
        _copy_dir_resource("k8s/monitoring", "k8s/monitoring")
    else:
        click.echo("  SKIP k8s/monitoring (observability disabled)")


def _copy_k8s_benchmarks(with_benchmarks: bool):
    """Copy K8s benchmark configs if enabled."""
    if with_benchmarks:
        _create_k8s_benchmark_config()
    else:
        click.echo("  SKIP k8s/benchmark (use --with-benchmarks to include)")


def _log_k8s_init_complete(with_ha: bool):
    """Log completion message for K8s initialization."""
    if not console:
        return

    console.print("[bold green]Kubernetes manifests copied successfully![/bold green]")
    if with_ha:
        console.print("\n[bold yellow]HA PostgreSQL Services:[/bold yellow]")
        console.print("  - postgresql-primary:5432 (write traffic)")
        console.print("  - postgresql-read:5432 (read traffic, load-balanced)")
        console.print("  - pgbouncer-rw:6432 (write pool)")
        console.print("  - pgbouncer-ro:6433 (read pool)")


def _create_k8s_benchmark_config():
    """Create Kubernetes benchmark job configuration."""
    Path("k8s/benchmark").mkdir(parents=True, exist_ok=True)

    benchmark_job = """apiVersion: batch/v1
kind: Job
metadata:
  name: sagaz-benchmark
  namespace: sagaz
spec:
  template:
    spec:
      containers:
      - name: benchmark
        image: sagaz/sagaz:latest
        command: ["python", "-m", "pytest"]
        args:
          - "tests/test_performance.py"
          - "-v"
          - "-m"
          - "performance"
          - "--tb=short"
        env:
        - name: POSTGRES_URL
          valueFrom:
            secretKeyRef:
              name: sagaz-secrets
              key: postgres-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: sagaz-secrets
              key: redis-url
      restartPolicy: Never
  backoffLimit: 1
"""
    Path("k8s/benchmark/job.yaml").write_text(benchmark_job)
    click.echo("  CREATE k8s/benchmark/job.yaml")

    # Create stress test job
    stress_job = """apiVersion: batch/v1
kind: Job
metadata:
  name: sagaz-stress-test
  namespace: sagaz
spec:
  template:
    spec:
      containers:
      - name: stress
        image: sagaz/sagaz:latest
        command: ["python", "-m", "pytest"]
        args:
          - "tests/test_performance.py"
          - "-v"
          - "-m"
          - "stress"
          - "--tb=short"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2"
      restartPolicy: Never
  backoffLimit: 1
"""
    Path("k8s/benchmark/stress-job.yaml").write_text(stress_job)
    click.echo("  CREATE k8s/benchmark/stress-job.yaml")


def _init_hybrid(broker: str, oltp_storage: str = "postgresql", outbox_storage: str = "same"):
    """Create hybrid deployment configuration."""
    if console:
        console.print("Creating hybrid deployment configuration...")

    Path("hybrid").mkdir(exist_ok=True)

    # Create hybrid config explaining the setup
    readme = f"""# Hybrid Deployment Configuration

This directory contains configuration for a hybrid Sagaz deployment where:
- **OLTP Storage ({oltp_storage})**: Runs locally or on-premise
- **Message Broker ({broker})**: Cloud-managed service
- **Workers**: Kubernetes or local Docker

## Architecture

```
┌─────────────────┐     ┌─────────────────────────┐
│  On-Premise     │     │        Cloud            │
│                 │     │                         │
│  ┌───────────┐  │     │  ┌─────────────────┐    │
│  │ {oltp_storage:11s}│◄─┼─────┼──│  Message Broker │    │
│  └───────────┘  │     │  │  (managed)      │    │
│                 │     │  └────────┬────────┘    │
│  ┌───────────┐  │     │           │             │
│  │  Workers  │◄─┼─────┼───────────┘             │
│  │  (Docker) │  │     │                         │
│  └───────────┘  │     │  ┌─────────────────┐    │
│                 │     │  │  Kubernetes GKE │    │
│                 │     │  │  Workers (opt)  │    │
│                 │     │  └─────────────────┘    │
└─────────────────┘     └─────────────────────────┘
```

## Configuration

Edit `hybrid.env` with your cloud broker credentials.
"""
    Path("hybrid/README.md").write_text(readme)
    click.echo("  CREATE hybrid/README.md")

    # Create hybrid docker-compose based on storage type
    if oltp_storage == "postgresql":
        compose = f"""version: '3.8'

# Hybrid: Local Postgres + Cloud Broker
# Set BROKER_URL in environment

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: sagaz
      POSTGRES_PASSWORD: sagaz
      POSTGRES_DB: sagaz
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  worker:
    build: .
    environment:
      POSTGRES_URL: postgresql://sagaz:sagaz@postgres:5432/sagaz
      BROKER_TYPE: {preset}
      BROKER_URL: ${{BROKER_URL}}  # Set from environment
      SAGAZ_METRICS_PORT: 8000
    depends_on:
      - postgres
    ports:
      - "8000:8000"

volumes:
  postgres_data:
"""
    Path("hybrid/docker-compose.yaml").write_text(compose)
    click.echo("  CREATE hybrid/docker-compose.yaml")

    # Create environment template
    env = f"""# Hybrid Deployment Environment
# Cloud-managed broker credentials

BROKER_URL={
        "redis://your-cloud-redis:6379"
        if broker == "redis"
        else "kafka://your-cloud-kafka:9092"
        if preset == "kafka"
        else "amqp://user:pass@your-cloud-rabbitmq:5672"
    }
"""
    Path("hybrid/hybrid.env").write_text(env)
    click.echo("  CREATE hybrid/hybrid.env")

    if console:
        console.print("\n[bold green]Hybrid setup complete![/bold green]")
        console.print("Next steps:")
        console.print("  1. Edit [bold cyan]hybrid/hybrid.env[/bold cyan] with cloud credentials")
        console.print("  2. Run [bold cyan]cd hybrid && docker compose up[/bold cyan]")


def _init_benchmarks():
    """Create local benchmark configuration."""
    Path("benchmarks").mkdir(exist_ok=True)

    benchmark_script = """#!/bin/bash
# Sagaz Benchmark Runner

set -e

echo "=============================================="
echo "       Sagaz Performance Benchmark"
echo "=============================================="

# Parse arguments
PROFILE="${1:-local}"

case $PROFILE in
    local)
        echo "Running LOCAL profile (fast, development)"
        pytest tests/test_performance.py -v -m "performance and not slow" --tb=short
        ;;
    production)
        echo "Running PRODUCTION profile (comprehensive)"
        pytest tests/test_performance.py -v -m "performance" --tb=short
        ;;
    stress)
        echo "Running STRESS profile (high concurrency)"
        pytest tests/test_performance.py -v -m "stress" --tb=short
        ;;
    full)
        echo "Running FULL profile (all tests)"
        pytest tests/test_performance.py -v --tb=short
        ;;
    *)
        echo "Usage: $0 {local|production|stress|full}"
        exit 1
        ;;
esac

echo ""
echo "Benchmark complete!"
"""
    Path("benchmarks/run.sh").write_text(benchmark_script)
    Path("benchmarks/run.sh").chmod(0o755)
    click.echo("  CREATE benchmarks/run.sh")


def _copy_example_saga(example_template: str, target_dir: Path):
    """Copy an example saga from the package to the target directory."""
    try:
        import shutil
        from pathlib import Path
        
        # Map simple name to full path
        if example_template == "simple":
            # Create simple inline example
            simple_content = """from sagaz import Saga, action, SagaContext


class ExampleSaga(Saga):
    \"\"\"
    Simple example saga demonstrating basic multi-step workflow.
    
    This saga shows:
    - Sequential step execution with dependencies
    - Context passing between steps
    - Compensation handlers for rollback
    \"\"\"
    
    @action("initialize")
    async def initialize(self, ctx: SagaContext):
        \"\"\"Initialize the workflow.\"\"\"
        print("Initializing workflow")
        return {"initialized": True}
    
    @action("process", depends_on=["initialize"])
    async def process(self, ctx: SagaContext):
        \"\"\"Main processing step.\"\"\"
        print("Processing data")
        return {"processed": True}
    
    @action("finalize", depends_on=["process"])
    async def finalize(self, ctx: SagaContext):
        \"\"\"Finalize the workflow.\"\"\"
        print("Finalizing workflow")
        return {"completed": True}
"""
            (target_dir / "example_saga.py").write_text(simple_content)
            click.echo(f"  CREATE {target_dir / 'example_saga.py'}")
            return
        
        # Try to copy from package examples
        source_path = pkg_resources.files("sagaz.examples").joinpath(example_template)
        
        # Copy main.py if it exists
        try:
            main_py = source_path.joinpath("main.py")
            content = main_py.read_text()
            
            # Extract saga class name from path for filename
            saga_filename = example_template.split("/")[-1] + "_saga.py"
            (target_dir / saga_filename).write_text(content)
            click.echo(f"  CREATE {target_dir / saga_filename}")
        except Exception:
            click.echo(f"  WARNING: Could not copy example '{example_template}'")
            click.echo(f"           Creating simple example instead")
            _copy_example_saga("simple", target_dir)
            
    except Exception as e:
        click.echo(f"  ERROR: {e}")
        click.echo(f"  Creating empty project")


def _copy_dir_resource(resource_dir: str, target_dir: str) -> None:
    """Recursively copy a directory from the package resources."""
    try:
        traversable_dir = pkg_resources.files("sagaz.resources").joinpath(resource_dir)
        # Check if directory exists (Traversable may not have exists())
        try:
            list(traversable_dir.iterdir())  # Will raise if doesn't exist
        except (FileNotFoundError, TypeError):
            return

        Path(target_dir).mkdir(parents=True, exist_ok=True)
        for item in traversable_dir.iterdir():
            if item.is_dir():
                _copy_dir_resource(f"{resource_dir}/{item.name}", f"{target_dir}/{item.name}")
            else:
                try:
                    text_content = item.read_text()
                    Path(target_dir, item.name).write_text(text_content)
                except UnicodeDecodeError:
                    binary_content = item.read_bytes()
                    Path(target_dir, item.name).write_bytes(binary_content)
                click.echo(f"  CREATE {target_dir}/{item.name}")
    except Exception:
        # Silently fail if dir doesn't exist, it's optional for some presets
        pass


def _copy_resource(resource_path: str, target_path: str):
    """Copy a resource file from the package to the target path."""
    try:
        content = pkg_resources.files("sagaz.resources").joinpath(resource_path).read_text()
        Path(target_path).write_text(content)
        click.echo(f"  CREATE {target_path}")
    except Exception as e:
        click.echo(f"  ERROR copying {resource_path}: {e}")


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
