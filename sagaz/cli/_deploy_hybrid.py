"""Hybrid deployment and local benchmark initialization."""

from pathlib import Path

import click

try:
    from rich.console import Console

    console: Console | None = Console()
except ImportError:
    console = None


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
    Path("hybrid/README.md").write_text(readme, encoding="utf-8")
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
