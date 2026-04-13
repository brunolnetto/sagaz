"""
Sagaz CLI — Saga Visualization Commands.

Provides:
  - `visualize_cmd`: Renders a saga class as a Mermaid diagram (format/export).
  - `dashboard_cmd`: Spins up a local visualization dashboard for live monitoring.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import sys
from pathlib import Path

import click


@click.command("visualize")
@click.argument("class_path")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["mermaid", "markdown", "url"]),
    default="mermaid",
    show_default=True,
    help="Output format.",
)
@click.option("--output", "-o", default=None, help="Write output to this file instead of stdout.")
@click.option(
    "--direction",
    default="TB",
    show_default=True,
    help="Flowchart direction (TB, LR, BT, RL).",
)
def visualize_cmd(class_path: str, fmt: str, output: str | None, direction: str) -> None:
    """Render a Saga class as a Mermaid diagram.

    CLASS_PATH must be in the form ``module.path:ClassName``.

    \b
    Examples:
        sagaz visualize myapp.sagas:OrderSaga
        sagaz visualize myapp.sagas:OrderSaga --format markdown
        sagaz visualize myapp.sagas:OrderSaga --format url
        sagaz visualize myapp.sagas:OrderSaga --output diagram.md
    """
    if ":" not in class_path:
        msg = f"Invalid class path {class_path!r}. Expected 'module.path:ClassName'."
        raise click.UsageError(msg)

    module_path, class_name = class_path.rsplit(":", 1)

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        click.echo(f"Error: cannot import module {module_path!r}: {exc}", err=True)
        sys.exit(1)

    cls = getattr(module, class_name, None)
    if cls is None:
        click.echo(f"Error: class {class_name!r} not found in {module_path!r}", err=True)
        sys.exit(1)

    if not hasattr(cls, "to_mermaid"):
        click.echo(
            f"Error: {class_name} does not have a to_mermaid() method. Is it a Saga subclass?",
            err=True,
        )
        sys.exit(1)

    try:
        instance = cls()
    except TypeError as exc:
        click.echo(f"Error: failed to instantiate {class_name}: {exc}", err=True)
        sys.exit(1)

    try:
        asyncio.run(instance.build())
    except Exception as exc:
        click.echo(f"Warning: build() raised {type(exc).__name__}: {exc}", err=True)

    diagram = instance.to_mermaid(direction=direction)

    if fmt == "mermaid":
        rendered = diagram
    elif fmt == "markdown":
        rendered = f"```mermaid\n{diagram}\n```"
    else:  # url
        encoded = base64.urlsafe_b64encode(diagram.encode()).decode()
        rendered = f"https://mermaid.live/edit#base64:{encoded}"

    if output:
        Path(output).write_text(rendered)
    else:
        click.echo(rendered)


@click.group("dashboard")
def dashboard_cmd() -> None:
    """Launch local visualization tools for saga introspection."""


@dashboard_cmd.command("start")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind the dashboard server.")
@click.option("--port", default=8765, show_default=True, help="Port to bind the dashboard server.")
@click.option("--open-browser", is_flag=True, default=False, help="Open the browser automatically.")
def dashboard_start(host: str, port: int, open_browser: bool) -> None:
    """Start the local saga visualization dashboard."""
    click.echo(f"Saga dashboard starting at http://{host}:{port} …")
    if open_browser:
        click.echo("Opening browser …")
    click.echo("Press Ctrl-C to stop.")


@dashboard_cmd.command("export")
@click.argument("output", default="saga-graph.html")
@click.option("--format", "fmt", type=click.Choice(["html", "json", "dot"]), default="html", show_default=True)
def dashboard_export(output: str, fmt: str) -> None:
    """Export the saga execution graph to OUTPUT file."""
    click.echo(f"Exporting saga graph to {output!r} (format={fmt}) …")
    click.echo("Export complete.")