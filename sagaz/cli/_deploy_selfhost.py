"""Self-hosted (on-premise / systemd) deployment initialization."""

from pathlib import Path

import click

try:
    from rich.console import Console

    console: Console | None = Console()
except ImportError:
    console = None


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
    _create_systemd_service(
        "sagaz-worker", "Sagaz Outbox Worker", "python -m sagaz.core.outbox.worker"
    )

    # Create environment file
    env_content = f"""# Sagaz Environment Configuration
# Copy to /etc/sagaz/sagaz.env

# OLTP Database
POSTGRES_URL=postgresql://sagaz:sagaz@localhost:5432/sagaz

# Outbox Database {"(separate)" if separate_outbox else "(same as OLTP)"}
{
        (
            "OUTBOX_URL=postgresql://sagaz:sagaz@localhost:5432/sagaz_outbox"
            if separate_outbox
            else "# OUTBOX_URL=$POSTGRES_URL"
        )
    }

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

    Path("selfhost/sagaz.env").write_text(env_content, encoding="utf-8")
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
