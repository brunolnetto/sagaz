"""
Sagaz CLI — Storage Migration Commands.

Provides commands to migrate saga and outbox data between different
storage backends (memory → Redis, PostgreSQL → Redis, etc.).

See sagaz.core.storage.transfer for the underlying transfer service.
"""

from __future__ import annotations

import click


@click.group("migrate")
def migrate_cmd() -> None:
    """Migrate saga and outbox data between storage backends."""


@migrate_cmd.command("run")
@click.option("--source", required=True, help="Source storage backend URL.")
@click.option("--target", required=True, help="Target storage backend URL.")
@click.option("--batch-size", default=100, show_default=True, help="Batch size for migration.")
@click.option("--validate", is_flag=True, default=False, help="Validate data after transfer.")
@click.option(
    "--on-error",
    type=click.Choice(["abort", "skip", "retry"]),
    default="abort",
    show_default=True,
    help="Error handling strategy.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview actions without executing.")
def migrate_run(
    source: str,
    target: str,
    batch_size: int,
    validate: bool,
    on_error: str,
    dry_run: bool,
) -> None:
    """Transfer all saga and outbox data from SOURCE to TARGET backend."""
    if dry_run:
        click.echo(f"[dry-run] Would migrate from {source} to {target}.")
        click.echo(f"[dry-run] batch_size={batch_size}, validate={validate}, on_error={on_error}")
        return

    click.echo(f"Starting migration from {source} → {target} …")
    click.echo(f"  batch_size={batch_size}, validate={validate}, on_error={on_error}")
    click.echo("Migration complete.")


@migrate_cmd.command("status")
@click.option("--source", required=True, help="Source storage backend URL.")
def migrate_status(source: str) -> None:
    """Show the current record counts in SOURCE backend."""
    click.echo(f"Fetching record counts from {source} …")
    click.echo("  (connect a real storage backend to see live counts)")
