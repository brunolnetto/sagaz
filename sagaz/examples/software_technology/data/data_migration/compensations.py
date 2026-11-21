"""
Compensation (rollback) handlers for the data migration saga.
"""

import asyncio
import logging
from typing import Any

from sagaz import compensate

# The example runs as a script (``python main.py``); log under the script's
# logger name so the demo output is unchanged by the module split.
logger = logging.getLogger("__main__")


class DataMigrationCompensations:
    """Compensation (rollback) handlers for DataMigrationSaga."""

    @compensate("backup_target")
    async def cleanup_backup(self, ctx: dict[str, Any]) -> None:
        """Clean up backup tables after successful migration or rollback."""
        backup_id = ctx.get("backup_id")
        backup_tables = ctx.get("backup_tables", {})

        if backup_tables:
            logger.warning(f"🧹 Cleaning up backup: {backup_id}")
            for _original, backup in backup_tables.items():
                logger.info(f"   Dropping {backup}")
            await asyncio.sleep(0.1)

    @compensate("export_from_source")
    async def cleanup_export_files(self, ctx: dict[str, Any]) -> None:
        """Clean up exported files."""
        export_results = ctx.get("export_results", {})

        if export_results:
            logger.warning("🧹 Cleaning up export files")
            for _table, result in export_results.items():
                logger.info(f"   Removing {result['export_path']}")
            await asyncio.sleep(0.1)

    @compensate("transform_schema")
    async def cleanup_transformed_files(self, ctx: dict[str, Any]) -> None:
        """Clean up transformed files."""
        transform_results = ctx.get("transform_results", {})

        if transform_results:
            logger.warning("🧹 Cleaning up transformed files")
            for _table, result in transform_results.items():
                logger.info(f"   Removing {result['transformed_path']}")
            await asyncio.sleep(0.1)

    @compensate("import_to_target")
    async def rollback_target_import(self, ctx: dict[str, Any]) -> None:
        """Delete imported data and restore from backup."""
        target_system = ctx.get("target_system")
        import_results = ctx.get("import_results", {})
        backup_tables = ctx.get("backup_tables", {})

        logger.warning(f"⏪ Rolling back import to {target_system}")

        for table, result in import_results.items():
            logger.info(f"   Truncating {result['target_table']}")

            if table in backup_tables:
                backup_table = backup_tables[table]
                logger.info(f"   Restoring from {backup_table}")

        await asyncio.sleep(0.3)
        logger.info("✅ Rollback complete - target restored to pre-migration state")

    @compensate("verify_row_counts")
    async def log_verification_failure(self, ctx: dict[str, Any]) -> None:
        """Log verification failure details."""
        verification_details = ctx.get("verification_details", {})

        logger.warning("📝 Logging verification failure")
        for table, details in verification_details.items():
            if not details.get("is_match"):
                logger.warning(f"   {table}: {details}")

        await asyncio.sleep(0.05)

    @compensate("verify_checksums")
    async def log_checksum_failure(self, ctx: dict[str, Any]) -> None:
        """Log checksum failure for investigation."""
        logger.warning("📝 Logging checksum verification failure")
        logger.warning("   This may indicate data corruption during transfer")
        await asyncio.sleep(0.05)
