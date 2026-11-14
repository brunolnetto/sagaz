"""Runtime operation commands for the Sagaz CLI: dev, stop, status, logs and version."""

import subprocess
import sys
from pathlib import Path

import click

try:
    from rich.console import Console
    from rich.table import Table

    console: Console | None = Console()
except ImportError:
    console = None


# ============================================================================
# sagaz dev
# ============================================================================


@click.command()
@click.option("-d", "--detach", is_flag=True, help="Run in background")
def dev_cmd(detach: bool):
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
    subprocess.run(cmd, check=False)


# ============================================================================
# sagaz stop
# ============================================================================


@click.command()
def stop_cmd():
    """Stop local development environment."""
    if not Path("docker-compose.yaml").exists():
        click.echo("docker-compose.yaml not found.")
        sys.exit(1)

    click.echo("Stopping development environment...")
    subprocess.run(["docker", "compose", "down"], check=False)


# ============================================================================
# sagaz status
# ============================================================================


@click.command()
def status_cmd():
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
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
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
        subprocess.run(["docker", "compose", "ps"], check=False)


# ============================================================================
# sagaz logs
# ============================================================================


@click.command()
@click.argument("saga_id", required=False)
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
@click.option("-s", "--service", help="Filter by service name")
def logs_cmd(saga_id: str, follow: bool, service: str):
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
        with subprocess.Popen(cmd, stdout=subprocess.PIPE) as p1:
            with subprocess.Popen(["grep", saga_id], stdin=p1.stdout) as p2:
                p2.wait()
    else:
        subprocess.run(cmd, check=False)


# ============================================================================
# sagaz version
# ============================================================================


@click.command()
def version_cmd():
    """Show version information."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("sagaz")
    except PackageNotFoundError:  # running from a source tree without installing
        installed = "unknown"
    click.echo(f"sagaz version {installed}")
    click.echo("Python " + sys.version.split()[0])
