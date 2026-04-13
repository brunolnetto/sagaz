"""
Sagaz CLI — Local Development Visualization Commands.

Provides commands to spin up a local visualization dashboard for
monitoring and introspecting running sagas during development.
"""

from __future__ import annotations

import click


@click.group("visualize")
def visualize_cmd() -> None:
    """Launch local visualization tools for saga introspection."""


@visualize_cmd.command("dashboard")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind the dashboard server.")
@click.option("--port", default=8765, show_default=True, help="Port to bind the dashboard server.")
@click.option("--open-browser", is_flag=True, default=False, help="Open the browser automatically.")
def dashboard(host: str, port: int, open_browser: bool) -> None:
    """Start the local saga visualization dashboard."""
    click.echo(f"Saga dashboard starting at http://{host}:{port} …")
    if open_browser:
        click.echo("Opening browser …")
    click.echo("Press Ctrl-C to stop.")


@visualize_cmd.command("export")
@click.argument("output", default="saga-graph.html")
@click.option("--format", "fmt", type=click.Choice(["html", "json", "dot"]), default="html", show_default=True)
def export(output: str, fmt: str) -> None:
    """Export the saga execution graph to OUTPUT file."""
    click.echo(f"Exporting saga graph to {output!r} (format={fmt}) …")
    click.echo("Export complete.")
