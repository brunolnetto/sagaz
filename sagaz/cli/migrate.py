"""
Sagaz CLI — Storage Migration Commands.

Provides commands to migrate saga and outbox data between different
storage backends (memory → Redis, PostgreSQL → Redis, etc.).

See sagaz.core.storage.transfer for the underlying transfer service.
"""

from __future__ import annotations

import asyncio

import click

from sagaz.core.storage import create_storage_manager
from sagaz.storage.migration import SagaStorageMigrator


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

    async def _run() -> None:
        click.echo(f"Starting migration from {source} → {target} …")
        click.echo(f"  batch_size={batch_size}, validate={validate}, on_error={on_error}")

        async with create_storage_manager(url=source) as source_manager:
            async with create_storage_manager(url=target) as target_manager:
                migrator = SagaStorageMigrator(source_manager, target_manager)
                result = await migrator.migrate(
                    dry_run=False,
                    batch_size=batch_size,
                    on_error=on_error,
                )

                click.echo(
                    "Migration result: "
                    f"sagas={result.sagas_transferred} (failed={result.sagas_failed}), "
                    f"events={result.events_transferred} (failed={result.events_failed})"
                )

                if validate:
                    verification = await migrator.verify()
                    status = "passed" if verification.ok else "failed"
                    click.echo(
                        "Verification "
                        f"{status}: sagas {verification.source_sagas}->{verification.dest_sagas}, "
                        f"events {verification.source_events}->{verification.dest_events}"
                    )
                    if not verification.ok:
                        msg = "Migration verification failed."
                        raise click.ClickException(msg)

                if not result.success:
                    msg = "Migration completed with failures."
                    raise click.ClickException(msg)

                click.echo("Migration complete.")

    asyncio.run(_run())


@migrate_cmd.command("status")
@click.option("--source", required=True, help="Source storage backend URL.")
def migrate_status(source: str) -> None:
    """Show the current record counts in SOURCE backend."""

    async def _run() -> None:
        click.echo(f"Fetching record counts from {source} …")
        async with create_storage_manager(url=source) as manager:
            saga_stats = await manager.saga.get_statistics()
            event_count = await manager.outbox.count()
            click.echo(f"  sagas={saga_stats.total_records}")
            click.echo(f"  outbox_events={event_count}")

    asyncio.run(_run())
