"""
Deployment initialization handlers for the Sagaz CLI.

Contains helper functions for initialising each supported deployment mode:
- Local  (Docker Compose)
- Self-hosted (on-premise / systemd)
- Kubernetes
- Hybrid (local storage + cloud broker)
- Benchmarks
- Resource copy utilities
"""

import importlib.resources as pkg_resources
import shutil
from pathlib import Path

import click

try:
    from rich.console import Console

    console: Console | None = Console()
except ImportError:
    console = None


def _init_local(
    broker: str,
    with_observability: bool,
    with_ha: bool = False,
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same",
    dev_mode: bool = False,
):
    """Create local Docker Compose setup."""
    _log_local_init_start(broker, with_ha, oltp_storage, dev_mode)

    # 1. Create docker-compose.yaml
    _init_docker_compose(
        broker, with_ha, with_observability, separate_outbox, oltp_storage, outbox_storage, dev_mode
    )

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
    dev_mode: bool = False,
):
    """Initialize docker-compose.yaml with optional overwrite confirmation."""
    target = "docker-compose.yaml"

    if Path(target).exists() and not click.confirm(f"{target} already exists. Overwrite?"):
        click.echo(f"Skipping {target}")
        return

    _copy_docker_compose_files(
        broker, with_ha, with_observability, separate_outbox, oltp_storage, outbox_storage, dev_mode
    )


def _copy_docker_compose_files(
    broker: str,
    with_ha: bool,
    with_observability: bool = True,
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same",
    dev_mode: bool = False,
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


def _get_broker_config(broker: str) -> tuple[str, int, str]:
    """Get broker-specific Docker configuration."""
    configs = {
        "redis": ("redis:7-alpine", 6379, "ALLOW_ANONYMOUS_LOGIN: 'yes'"),
        "rabbitmq": (
            "rabbitmq:3-management",
            5672,
            "RABBITMQ_DEFAULT_USER: sagaz\n      RABBITMQ_DEFAULT_PASS: sagaz",
        ),
        "kafka": (
            "confluentinc/cp-kafka:latest",
            9092,
            "KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092\n      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181",
        ),
    }
    return configs.get(broker, configs["redis"])


def _create_inmemory_docker_compose(broker: str):
    """Create a minimal docker-compose for in-memory development."""
    image, port, env_config = _get_broker_config(broker)

    content = f"""version: '3.8'

services:
  # Message broker only - everything else runs in-memory
  {broker}:
    image: {image}
    ports:
      - "{port}:{port}"
    environment:
      {env_config}

networks:
  sagaz:
    driver: bridge
"""
    Path("docker-compose.yaml").write_text(content)
    click.echo("  CREATE docker-compose.yaml")


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
    outbox_storage: str = "same",
):
    """Create self-hosted/on-premise server setup."""
    if console:
        console.print("Creating self-hosted deployment files...")

    # Create selfhost directory
    Path("selfhost").mkdir(exist_ok=True)

    # Create systemd service files
    _create_systemd_service("sagaz-worker", "Sagaz Outbox Worker", "python -m sagaz.core.outbox.worker")

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
    outbox_storage: str = "same",
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
    console.print(
        f"Copying Kubernetes manifests{ha_msg} (storage: [bold cyan]{oltp_storage}[/bold cyan]) to [bold cyan]./k8s[/bold cyan]..."
    )


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


def _copy_k8s_manifests(
    with_ha: bool, separate_outbox: bool = False, oltp_storage: str = "postgresql"
):
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
      BROKER_TYPE: {broker}
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
        if broker == "kafka"
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
            click.echo("           Creating simple example instead")
            _copy_example_saga("simple", target_dir)

    except Exception as e:
        click.echo(f"  ERROR: {e}")
        click.echo("  Creating empty project")


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
