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

Install:
    pip install sagaz[cli]

This creates the 'sagaz' command via entry point in pyproject.toml.
"""

import sys

# Check for optional CLI dependencies
try:
    import click

    HAS_CLICK = True
except ImportError:
    HAS_CLICK = False

try:
    from rich.console import Console
    from rich.panel import Panel

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def main():
    """Main entry point for the sagaz CLI."""
    if not HAS_CLICK:
        sys.exit(1)

    # Import and run the CLI app
    from sagaz.cli.app import cli

    cli()


def main_fallback():
    """Fallback when click is not installed - show help."""
    sys.exit(1)


if __name__ == "__main__":
    main()
