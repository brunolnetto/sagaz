"""
Setup wizard helper functions extracted from app.py.

Contains all interactive prompt and configuration helpers for the
`sagaz setup` command.
"""

import sys
from pathlib import Path
from typing import Any

import click

from sagaz.cli._init_handlers import (
    _init_benchmarks,
    _init_hybrid,
    _init_k8s,
    _init_local,
    _init_selfhost,
)

try:
    from rich.console import Console
    from rich.panel import Panel

    console: Console | None = Console()
except ImportError:
    console = None
    Panel = None  # type: ignore[assignment,misc]


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
            f"  Benchmarks: {'[green]Yes[/green]' if config['with_benchmarks'] else '[dim]No[/dim]'}\n"  # noqa: E501
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
