import sys
from pathlib import Path

from . import utils


def init_local(
    broker: str,
    with_observability: bool,
    with_ha: bool = False,
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same",
    dev_mode: bool = False,
):
    """Create local Docker Compose setup."""
    this = sys.modules[__name__]
    this._log_local_init_start(broker, with_ha, oltp_storage, dev_mode)
    this._init_docker_compose(
        broker, with_ha, with_observability, separate_outbox, oltp_storage, outbox_storage, dev_mode
    )
    if with_observability:
        this._init_monitoring(broker, with_ha)
    this._log_local_init_complete(with_observability, with_ha, dev_mode)


def _log_local_init_start(broker: str, with_ha: bool, oltp_storage: str, dev_mode: bool):
    if not utils.console:
        return
    if dev_mode:
        utils.console.print(
            "Creating [bold yellow]in-memory development[/bold yellow] environment..."
        )
    elif with_ha:
        utils.console.print("Creating local HA PostgreSQL environment...")
    else:
        utils.console.print(
            f"Creating local environment (storage: {oltp_storage}, broker: {broker})..."
        )


def _init_docker_compose(
    broker,
    with_ha,
    with_observability=False,
    separate_outbox=False,
    oltp_storage="postgresql",
    outbox_storage="same",
    dev_mode=False,
):
    target = "docker-compose.yaml"
    if Path(target).exists() and not utils.click.confirm(f"{target} already exists. Overwrite?"):
        return
    this = sys.modules[__name__]
    this._copy_docker_compose_files(
        broker, with_ha, with_observability, separate_outbox, oltp_storage, outbox_storage, dev_mode
    )


def _copy_docker_compose_files(
    broker,
    with_ha,
    with_observability=False,
    separate_outbox=False,
    oltp_storage="postgresql",
    outbox_storage="same",
    dev_mode=False,
):
    this = sys.modules[__name__]
    if dev_mode:
        this._create_inmemory_docker_compose(broker)
    elif with_ha:
        utils.copy_resource("local/postgres-ha/docker-compose.yaml", "docker-compose.yaml")
        utils.copy_resource("local/postgres-ha/init-primary.sh", "init-primary.sh")
        utils.copy_dir_resource("local/postgres-ha/partitioning", "partitioning")
    else:
        utils.copy_resource(f"local/{broker}/docker-compose.yaml", "docker-compose.yaml")


def _get_broker_config(broker: str) -> tuple[str, int, str]:
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
    this = sys.modules[__name__]
    image, port, env_config = this._get_broker_config(broker)
    content = f"""version: '3.8'
services:
  {broker}:
    image: {image}
    ports: ["{port}:{port}"]
    environment:
      {env_config}
networks:
  sagaz:
    driver: bridge
"""
    Path("docker-compose.yaml").write_text(content)


def _init_monitoring(broker: str, with_ha: bool):
    path = f"local/{'postgres-ha' if with_ha else broker}/monitoring"
    utils.copy_dir_resource(path, "monitoring")


def _log_local_init_complete(with_observability: bool, with_ha: bool, dev_mode: bool):
    if not utils.console:
        return
    utils.console.print("\n[bold green]Deployment setup complete![/bold green]")
    if dev_mode:
        utils.console.print("  - Local in-memory services are ready.")
    if with_observability:
        utils.console.print("  - Grafana: http://localhost:3000 (admin/admin)")
        utils.console.print("  - Prometheus: http://localhost:9090")
    if with_ha:
        utils.console.print("  - PostgreSQL Primary: localhost:5432")
        utils.console.print("  - PostgreSQL Replica: localhost:5433")
