"""
Sagaz CLI - Command-line interface for saga orchestration.

Deployment Scenarios:
    sagaz init --local        # Local development (Docker Compose)
    sagaz init --selfhost     # Self-hosted/on-premise servers
    sagaz init --k8s          # Kubernetes (cloud-native)
    sagaz init --hybrid       # Hybrid deployment

Operations:
    sagaz dev                 # Start local environment
    sagaz stop                # Stop local environment
    sagaz status              # Check service health
    sagaz logs                # View logs
    sagaz monitor             # Open Grafana dashboard

Benchmarking:
    sagaz benchmark                   # Quick local benchmark
    sagaz benchmark --profile stress  # Stress testing
    sagaz benchmark --profile full    # All benchmarks

This creates the 'sagaz' command via entry point in pyproject.toml.
"""

import click
from rich.console import Console

console = Console()


def main():
    """Main entry point for the sagaz CLI."""
    from sagaz.cli.app import cli
    cli()


if __name__ == "__main__":
    main()

