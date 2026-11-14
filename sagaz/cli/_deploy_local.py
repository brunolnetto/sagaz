"""Local (Docker Compose) deployment initialization."""

from pathlib import Path

import click

from sagaz.cli._deploy_resources import _copy_dir_resource, _copy_resource

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
            "Creating [bold yellow]in-memory development[/bold yellow] environment"
            " (no external dependencies)..."
        )
    elif with_ha:
        console.print(
            "Creating local HA PostgreSQL environment with [bold green]primary +"
            " replica + PgBouncer[/bold green]..."
        )
    else:
        msg = (
            f"Creating local development environment (storage:"
            f" [bold green]{oltp_storage}[/bold green], broker:"
            f" [bold green]{broker}[/bold green])..."
        )
        console.print(msg)


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
            (
                "KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092\n"
                "      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181"
            ),
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
