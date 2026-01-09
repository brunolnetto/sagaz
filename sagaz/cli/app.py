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

import click

from sagaz.cli import examples as cli_examples

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


@click.group()
@click.version_option(version="1.0.3", prog_name="sagaz")
def cli():
    """
    Sagaz - Production-ready Saga Pattern Orchestration.

    \b
    Deployment Scenarios:
        sagaz init --local        # Local development (Docker Compose)
        sagaz init --selfhost     # Self-hosted servers
        sagaz init --k8s          # Kubernetes (cloud-native)
        sagaz init --hybrid       # Hybrid deployment

    \b
    Operations:
        sagaz dev                 # Start local environment
        sagaz status              # Check health
        sagaz benchmark           # Run performance tests
        sagaz benchmark --stress  # Run stress tests

    Documentation: https://github.com/brunolnetto/sagaz
    """


# ============================================================================
# sagaz init
# ============================================================================


@cli.command()
@click.option(
    "--local",
    "mode",
    flag_value="local",
    default=True,
    help="Docker Compose setup for local development",
)
@click.option(
    "--selfhost", "mode", flag_value="selfhost", help="Setup for self-hosted/on-premise servers"
)
@click.option(
    "--k8s", "mode", flag_value="k8s", help="Kubernetes manifests for cloud-native deployment"
)
@click.option(
    "--hybrid",
    "mode",
    flag_value="hybrid",
    help="Hybrid deployment (local services + cloud broker)",
)
@click.option(
    "--preset",
    type=click.Choice(["redis", "kafka", "rabbitmq", "postgres"]),
    default="redis",
    help="Message broker preset (default: redis), use 'postgres' for HA setup",
)
@click.option(
    "--with-monitoring",
    is_flag=True,
    default=True,
    help="Include Prometheus/Grafana monitoring stack (default: yes)",
)
@click.option(
    "--with-benchmarks",
    is_flag=True,
    default=False,
    help="Include benchmark configuration (optional)",
)
@click.option(
    "--with-ha",
    is_flag=True,
    default=False,
    help="Enable High-Availability PostgreSQL (primary + replicas + PgBouncer)",
)
def init(mode: str, preset: str, with_monitoring: bool, with_benchmarks: bool, with_ha: bool):
    """
    Initialize a new Sagaz project for your deployment scenario.

    \b
    Deployment Modes:
        --local       Docker Compose for development (default)
        --selfhost    Systemd services for on-premise servers
        --k8s         Kubernetes manifests for cloud-native
        --hybrid      Mix of local and cloud services

    \b
    Examples:
        sagaz init                              #Local + Redis (simplest)
        sagaz init --preset kafka               # Local + Kafka
        sagaz init --with-ha                    # HA PostgreSQL (local)
        sagaz init --k8s                        # Kubernetes manifests
        sagaz init --k8s --with-ha              # K8s with HA PostgreSQL
        sagaz init --k8s --with-benchmarks      # K8s with benchmark configs
        sagaz init --selfhost                   # Systemd service files
        sagaz init --hybrid                     # Hybrid deployment
    """
    if console:
        console.print(
            Panel.fit(
                f"[bold blue]Sagaz Project Initialization[/bold blue]\n"
                f"Mode: [cyan]{mode}[/cyan] | Broker: [green]{preset}[/green]"
                + (" | HA: [yellow]enabled[/yellow]" if with_ha else ""),
                border_style="blue",
            )
        )

    # Override preset to 'postgres' if --with-ha is used
    if with_ha:
        preset = "postgres"

    if mode == "local":
        _init_local(preset, with_monitoring, with_ha)
    elif mode == "selfhost":
        _init_selfhost(preset, with_monitoring)
    elif mode == "k8s":
        _init_k8s(with_monitoring, with_benchmarks, with_ha)
    elif mode == "hybrid":
        _init_hybrid(preset)

    if with_benchmarks and mode not in ["k8s"]:
        _init_benchmarks()


def _init_local(preset: str, with_monitoring: bool, with_ha: bool = False):
    """Create local Docker Compose setup."""
    _log_local_init_start(preset, with_ha)

    is_postgres = with_ha or preset == "postgres"

    # 1. Create docker-compose.yaml
    _init_docker_compose(preset, is_postgres)

    # 2. Copy monitoring folder if enabled
    if with_monitoring:
        _init_monitoring(preset, is_postgres)

    # 3. Create sagaz.yaml
    _init_sagaz_yaml(preset)

    _log_local_init_complete(with_monitoring, is_postgres)


def _log_local_init_start(preset: str, with_ha: bool):
    """Log the start of local initialization."""
    if not console:
        return
    if with_ha:
        console.print(
            "Creating local HA PostgreSQL environment with [bold green]primary + replica + PgBouncer[/bold green]..."
        )
    else:
        console.print(
            f"Creating local development environment (preset: [bold green]{preset}[/bold green])..."
        )


def _init_docker_compose(preset: str, is_postgres: bool):
    """Initialize docker-compose.yaml with optional overwrite confirmation."""
    target = "docker-compose.yaml"

    if Path(target).exists() and not click.confirm(f"{target} already exists. Overwrite?"):
        click.echo(f"Skipping {target}")
        return

    _copy_docker_compose_files(preset, is_postgres)


def _copy_docker_compose_files(preset: str, is_postgres: bool):
    """Copy the appropriate docker-compose files."""
    if is_postgres:
        _copy_resource("local/postgres/docker-compose.yaml", "docker-compose.yaml")
        _copy_resource("local/postgres/init-primary.sh", "init-primary.sh")
        _copy_dir_resource("local/postgres/partitioning", "partitioning")
    else:
        _copy_resource(f"local/{preset}/docker-compose.yaml", "docker-compose.yaml")


def _init_monitoring(preset: str, is_postgres: bool):
    """Copy monitoring configuration."""
    if is_postgres:
        _copy_dir_resource("local/postgres/monitoring", "monitoring")
    else:
        _copy_dir_resource(f"local/{preset}/monitoring", "monitoring")


def _init_sagaz_yaml(preset: str):
    """Initialize sagaz.yaml with optional overwrite confirmation."""
    if Path("sagaz.yaml").exists():
        if not click.confirm("sagaz.yaml already exists. Overwrite?"):
            click.echo("Skipping sagaz.yaml")
            return
    _create_sagaz_config(preset)


def _log_local_init_complete(with_monitoring: bool, is_postgres: bool):
    """Log completion message for local initialization."""
    if not console:
        return

    console.print("\n[bold green]Initialization complete![/bold green]")
    console.print("Next steps:")
    console.print("  1. Run [bold cyan]sagaz dev[/bold cyan] to start the services")
    console.print("  2. Check status with [bold cyan]sagaz status[/bold cyan]")
    if with_monitoring:
        console.print("  3. Open monitoring at http://localhost:3000")
    if is_postgres:
        console.print("\n[bold yellow]HA PostgreSQL Info:[/bold yellow]")
        console.print("  - Primary (writes): localhost:5432")
        console.print("  - Replica (reads): localhost:5433")
        console.print("  - PgBouncer-RW: localhost:6432")
        console.print("  - PgBouncer-RO: localhost:6433")



def _init_selfhost(preset: str, with_monitoring: bool):
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

# Database
POSTGRES_URL=postgresql://sagaz:sagaz@localhost:5432/sagaz

# Broker ({preset})
BROKER_TYPE={preset}
"""
    if preset == "redis":
        env_content += "REDIS_URL=redis://localhost:6379\n"
    elif preset == "kafka":
        env_content += "KAFKA_BOOTSTRAP_SERVERS=localhost:9092\n"
    elif preset == "rabbitmq":
        env_content += "RABBITMQ_URL=amqp://guest:guest@localhost:5672\n"

    env_content += """
# Observability
SAGAZ_METRICS_PORT=8000
SAGAZ_LOG_LEVEL=INFO
SAGAZ_LOG_JSON=true
"""

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

    if with_monitoring:
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


def _init_k8s(with_monitoring: bool, with_benchmarks: bool, with_ha: bool = False):
    """Copy Kubernetes manifests from the library to the current directory."""
    _log_k8s_init_start(with_ha)

    if not _prepare_k8s_directory():
        return

    try:
        _copy_k8s_manifests(with_ha)
        _copy_k8s_monitoring(with_monitoring)
        _copy_k8s_benchmarks(with_benchmarks)
        _log_k8s_init_complete(with_ha)
    except Exception as e:
        click.echo(f"Error copying manifests: {e}")


def _log_k8s_init_start(with_ha: bool):
    """Log the start of K8s initialization."""
    if not console:
        return
    ha_msg = " with [bold yellow]HA PostgreSQL[/bold yellow]" if with_ha else ""
    console.print(f"Copying Kubernetes manifests{ha_msg} to [bold cyan]./k8s[/bold cyan]...")


def _prepare_k8s_directory() -> bool:
    """Prepare k8s directory, prompting for overwrite if exists. Returns False to abort."""
    if Path("k8s").exists():
        if not click.confirm("Directory [bold yellow]k8s/[/bold yellow] already exists. Overwrite?"):
            click.echo("Aborted.")
            return False
        shutil.rmtree("k8s")
    Path("k8s").mkdir(exist_ok=True)
    return True


def _copy_k8s_manifests(with_ha: bool):
    """Copy base Kubernetes manifests."""
    if with_ha:
        _copy_resource("k8s/postgresql-ha.yaml", "k8s/postgresql-ha.yaml")
        _copy_resource("k8s/pgbouncer.yaml", "k8s/pgbouncer.yaml")
        click.echo("  CREATE k8s/postgresql-ha.yaml (StatefulSet with replicas)")
        click.echo("  CREATE k8s/pgbouncer.yaml (Connection pooling)")
        Path("k8s/partitioning").mkdir(exist_ok=True)
        _copy_dir_resource("local/postgres/partitioning", "k8s/partitioning")
    else:
        _copy_resource("k8s/postgresql.yaml", "k8s/postgresql.yaml")

    # Copy base manifests
    for manifest in ["outbox-worker.yaml", "configmap.yaml", "secrets-example.yaml", "migration-job.yaml"]:
        _copy_resource(f"k8s/{manifest}", f"k8s/{manifest}")


def _copy_k8s_monitoring(with_monitoring: bool):
    """Copy K8s monitoring manifests if enabled."""
    if with_monitoring:
        _copy_resource("k8s/prometheus-monitoring.yaml", "k8s/prometheus-monitoring.yaml")
        _copy_dir_resource("k8s/monitoring", "k8s/monitoring")
    else:
        click.echo("  SKIP k8s/monitoring (--no-monitoring)")


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


def _init_hybrid(preset: str):
    """Create hybrid deployment configuration."""
    if console:
        console.print("Creating hybrid deployment configuration...")

    Path("hybrid").mkdir(exist_ok=True)

    # Create hybrid config explaining the setup
    readme = f"""# Hybrid Deployment Configuration

This directory contains configuration for a hybrid Sagaz deployment where:
- **PostgreSQL**: Runs locally or on-premise
- **Message Broker ({preset})**: Cloud-managed service
- **Workers**: Kubernetes or local Docker

## Architecture

```
┌─────────────────┐     ┌─────────────────────────┐
│  On-Premise     │     │        Cloud            │
│                 │     │                         │
│  ┌───────────┐  │     │  ┌─────────────────┐    │
│  │ PostgreSQL│◄─┼─────┼──│  Message Broker │    │
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

    # Create hybrid docker-compose
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
        if preset == "redis"
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


def _create_sagaz_config(preset: str):
    """Create sagaz.yaml based on the preset."""
    try:
        template = (
            pkg_resources.files("sagaz.resources").joinpath("sagaz.yaml.template").read_text()
        )

        # Simple replacements (no jinja2 yet for v1.0 simplicity)
        ports = {"redis": 6379, "kafka": 9092, "rabbitmq": 5672}

        content = template.replace("{{ broker_type }}", preset)
        content = content.replace("{{ broker_port }}", str(ports.get(preset, 6379)))

        Path("sagaz.yaml").write_text(content)
        click.echo("  CREATE sagaz.yaml")
    except Exception as e:
        click.echo(f"  ERROR creating sagaz.yaml: {e}")


# ============================================================================
# sagaz dev
# ============================================================================


@cli.command()
@click.option("-d", "--detach", is_flag=True, help="Run in background")
def dev(detach: bool):
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


@cli.command()
def stop():
    """Stop local development environment."""
    if not Path("docker-compose.yaml").exists():
        click.echo("docker-compose.yaml not found.")
        sys.exit(1)

    click.echo("Stopping development environment...")
    subprocess.run(["docker", "compose", "down"])


# ============================================================================
# sagaz status
# ============================================================================


@cli.command()
def status():
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


@cli.command()
@click.option(
    "--profile",
    type=click.Choice(["local", "production", "stress", "full"]),
    default="local",
    help="Benchmark profile",
)
@click.option("--output", type=click.Path(), help="Output file for results (JSON)")
@click.option("--quick", is_flag=True, help="Quick sanity check (minimal iterations)")
def benchmark(profile: str, output: str, quick: bool):
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


@cli.command()
@click.argument("saga_id", required=False)
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
@click.option("-s", "--service", help="Filter by service name")
def logs(saga_id: str, follow: bool, service: str):
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


@cli.command()
def monitor():
    """Open Grafana dashboard in browser."""
    import webbrowser

    grafana_url = "http://localhost:3000"
    click.echo(f"Opening Grafana: {grafana_url}")
    webbrowser.open(grafana_url)


# ============================================================================
# sagaz version
# ============================================================================


@cli.command()
def version():
    """Show version information."""
    click.echo("sagaz version 1.0.3")
    click.echo("Python " + sys.version.split()[0])


# ============================================================================
# sagaz examples
# ============================================================================


@cli.group(invoke_without_command=True)
@click.pass_context
def examples(ctx):
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


@examples.command("list")
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


@examples.command("run")
@click.argument("name")
def run_example(name: str):
    """
    Run a specific example by name.

    \b
    Example:
        sagaz examples run ecommerce/order_processing
        sagaz examples run monitoring
    """
    cli_examples.run_example_cmd(name)


if __name__ == "__main__":
    cli()
