"""Environment configuration template generation."""

from pathlib import Path
from typing import Any


def create_env_template(
    target_path: Path | str, config_data: dict[str, Any], include_examples: bool = True
) -> None:
    """
    Create a .env.template file from configuration data.

    Args:
        target_path: Path to write .env.template
        config_data: Configuration dictionary
        include_examples: Include example values
    """
    path = Path(target_path)

    lines = [
        "# Sagaz Environment Configuration",
        "# Copy this file to .env and fill in your values",
        "# DO NOT commit .env to version control!",
        "",
        "# Project Settings",
        "SAGAZ_ENV=development  # development, staging, production",
        "",
    ]

    # Extract configuration sections
    storage_type = config_data.get("storage", {}).get("type", "postgresql")
    broker_type = config_data.get("broker", {}).get("type", "redis")

    # Storage configuration
    lines.extend(
        [
            "# Storage Configuration",
            f"SAGAZ_STORAGE_TYPE={storage_type}",
        ]
    )

    if storage_type == "postgresql":
        lines.extend(
            [
                "SAGAZ_STORAGE_HOST=localhost",
                "SAGAZ_STORAGE_PORT=5432",
                "SAGAZ_STORAGE_DB=sagaz",
                "SAGAZ_STORAGE_USER=postgres",
                "SAGAZ_STORAGE_PASSWORD=  # Set your password",
                "# Or use full URL:",
                "# SAGAZ_STORAGE_URL=postgresql://user:pass@host:port/db",
            ]
        )
    elif storage_type == "redis":
        lines.extend(
            [
                "SAGAZ_STORAGE_URL=redis://localhost:6379/0",
            ]
        )

    lines.append("")

    # Broker configuration
    lines.extend(
        [
            "# Message Broker Configuration",
            f"SAGAZ_BROKER_TYPE={broker_type}",
        ]
    )

    if broker_type == "kafka":
        lines.extend(
            [
                "SAGAZ_BROKER_HOST=localhost",
                "SAGAZ_BROKER_PORT=9092",
                "# Or use full URL:",
                "# SAGAZ_BROKER_URL=kafka://localhost:9092",
            ]
        )
    elif broker_type == "rabbitmq":
        lines.extend(
            [
                "SAGAZ_BROKER_HOST=localhost",
                "SAGAZ_BROKER_PORT=5672",
                "SAGAZ_BROKER_USER=guest",
                "SAGAZ_BROKER_PASSWORD=guest",
                "# Or use full URL:",
                "# SAGAZ_BROKER_URL=amqp://guest:guest@localhost:5672/",
            ]
        )
    elif broker_type == "redis":
        lines.extend(
            [
                "SAGAZ_BROKER_URL=redis://localhost:6379/1",
            ]
        )

    lines.append("")

    # Observability
    obs_config = config_data.get("observability", {})
    if obs_config.get("prometheus", {}).get("enabled"):
        lines.extend(
            [
                "# Observability",
                "SAGAZ_METRICS_ENABLED=true",
                "SAGAZ_METRICS_PORT=9090",
            ]
        )

    if obs_config.get("tracing", {}).get("enabled"):
        lines.extend(
            [
                "SAGAZ_TRACING_ENABLED=true",
                "SAGAZ_TRACING_ENDPOINT=http://localhost:4317",
            ]
        )

    lines.extend(
        [
            "",
            "# Logging",
            "SAGAZ_LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR",
            "",
        ]
    )

    # Outbox configuration
    lines.extend(
        [
            "# Outbox Worker Configuration (if using separate outbox database)",
            "# SAGAZ_OUTBOX_STORAGE_URL=postgresql://user:pass@host:port/outbox_db",
            "# SAGAZ_OUTBOX_BATCH_SIZE=100",
            "# SAGAZ_OUTBOX_POLL_INTERVAL=1.0",
            "",
        ]
    )

    path.write_text("\n".join(lines))
