"""
Data migration saga: backup, export, transform, import, verify and finalize.
"""

import asyncio
import hashlib
import logging
import random
from datetime import datetime
from typing import Any

from sagaz import Saga, action
from sagaz.core.exceptions import SagaStepError
from sagaz.examples.technology.data.data_migration.compensations import DataMigrationCompensations

# The example runs as a script (``python main.py``); log under the script's
# logger name so the demo output is unchanged by the module split.
logger = logging.getLogger("__main__")


class DataMigrationSaga(DataMigrationCompensations, Saga):
    """
    Cross-database migration saga with verification and rollback.

    This saga performs atomic data migration:
    1. Create backup of target (if exists)
    2. Export data from source system
    3. Transform schema for target
    4. Import to target system
    5. Verify row counts match
    6. Verify checksums match
    7. Finalize migration

    Expected context:
        - source_system: str - Source database/system name
        - target_system: str - Target database/system name
        - tables: list[str] - List of tables to migrate
        - verify_checksums: bool (optional) - Enable checksum verification
    """

    saga_name = "data-migration"

    @action("backup_target")
    async def backup_target(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Create backup of existing target data before migration."""
        target_system = ctx.get("target_system")
        tables = ctx.get("tables", [])

        logger.info(f"💾 Creating backup of target system: {target_system}")
        await asyncio.sleep(0.2)

        backup_id = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_tables = {}

        for table in tables:
            backup_table = f"{table}_backup_{backup_id}"
            backup_tables[table] = backup_table
            logger.info(f"   Backing up {table} → {backup_table}")

        await asyncio.sleep(0.3)

        logger.info(f"✅ Backup complete: {backup_id}")

        return {
            "backup_id": backup_id,
            "backup_tables": backup_tables,
            "backup_timestamp": datetime.now().isoformat(),
        }

    @action("export_from_source", depends_on=["backup_target"])
    async def export_from_source(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Export data from source system."""
        source_system = ctx.get("source_system")
        tables = ctx.get("tables", [])

        logger.info(f"📤 Exporting from {source_system}")

        export_results = {}
        total_records = 0

        for table in tables:
            await asyncio.sleep(0.15)
            record_count = random.randint(10000, 100000)
            checksum = hashlib.md5(f"{table}_{record_count}".encode()).hexdigest()[:8]

            export_path = f"/migration/export/{source_system}/{table}.parquet"
            export_results[table] = {
                "export_path": export_path,
                "record_count": record_count,
                "checksum": checksum,
            }
            total_records += record_count

            logger.info(f"   {table}: {record_count:,} records (checksum: {checksum})")

        logger.info(
            f"✅ Export complete: {total_records:,} total records from {len(tables)} tables"
        )

        return {
            "export_results": export_results,
            "total_source_records": total_records,
            "export_timestamp": datetime.now().isoformat(),
        }

    @action("transform_schema", depends_on=["export_from_source"])
    async def transform_schema(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Transform data schema for target system."""
        source_system = ctx.get("source_system")
        target_system = ctx.get("target_system")
        export_results = ctx.get("export_results", {})

        logger.info(f"🔄 Transforming schema: {source_system} → {target_system}")

        transform_results = {}

        for table, export_info in export_results.items():
            await asyncio.sleep(0.1)

            # Simulate schema transformations
            transformations = [
                f"Rename: old_id → {target_system}_id",
                "Convert: datetime → timestamp with timezone",
                "Add: migration_batch_id column",
            ]

            transformed_path = f"/migration/transformed/{target_system}/{table}.parquet"
            transform_results[table] = {
                "transformed_path": transformed_path,
                "transformations": transformations,
                "source_checksum": export_info["checksum"],
            }

            logger.info(f"   {table}: {len(transformations)} transformations applied")

        logger.info("✅ Schema transformation complete")

        return {
            "transform_results": transform_results,
            "transform_timestamp": datetime.now().isoformat(),
        }

    @action("import_to_target", depends_on=["transform_schema"])
    async def import_to_target(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Import transformed data to target system."""
        target_system = ctx.get("target_system")
        tables = ctx.get("tables", [])
        export_results = ctx.get("export_results", {})

        logger.info(f"📥 Importing to {target_system}")

        import_results = {}
        total_imported = 0

        for table in tables:
            await asyncio.sleep(0.2)

            source_count = export_results.get(table, {}).get("record_count", 0)
            # Simulate slight variation (some records might be filtered)
            imported_count = source_count - random.randint(0, int(source_count * 0.001))
            checksum = hashlib.md5(f"{table}_{imported_count}".encode()).hexdigest()[:8]

            import_results[table] = {
                "imported_count": imported_count,
                "checksum": checksum,
                "target_table": f"{target_system}.{table}",
            }
            total_imported += imported_count

            logger.info(f"   {table}: {imported_count:,} records imported")

        logger.info(f"✅ Import complete: {total_imported:,} total records")

        return {
            "import_results": import_results,
            "total_imported_records": total_imported,
            "import_timestamp": datetime.now().isoformat(),
        }

    @action("verify_row_counts", depends_on=["import_to_target"])
    async def verify_row_counts(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Verify row counts match between source and target."""
        export_results = ctx.get("export_results", {})
        import_results = ctx.get("import_results", {})

        logger.info("🔢 Verifying row counts")

        count_mismatches = []
        verification_details = {}

        for table in export_results:
            source_count = export_results[table]["record_count"]
            target_count = import_results.get(table, {}).get("imported_count", 0)

            # Allow small variance (0.1%)
            variance = abs(source_count - target_count) / source_count if source_count > 0 else 0
            max_variance = 0.001  # 0.1%

            is_match = variance <= max_variance

            verification_details[table] = {
                "source_count": source_count,
                "target_count": target_count,
                "variance": variance,
                "is_match": is_match,
            }

            if not is_match:
                count_mismatches.append(table)
                logger.error(
                    f"   ❌ {table}: {source_count:,} → {target_count:,} (variance: {variance:.2%})"
                )
            else:
                logger.info(f"   ✅ {table}: {source_count:,} ≈ {target_count:,}")

        if count_mismatches:
            msg = (
                f"Row count verification failed for tables: {count_mismatches}. "
                f"Migration will be rolled back."
            )
            raise SagaStepError(msg)

        logger.info("✅ All row counts verified")

        return {
            "row_count_verified": True,
            "verification_details": verification_details,
        }

    @action("verify_checksums", depends_on=["verify_row_counts"])
    async def verify_checksums(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Verify data checksums match (optional deep verification)."""
        verify_checksums = ctx.get("verify_checksums", True)
        export_results = ctx.get("export_results", {})
        import_results = ctx.get("import_results", {})

        if not verify_checksums:
            logger.info("⏭️ Checksum verification skipped (disabled)")
            return {"checksum_verified": True, "skipped": True}

        logger.info("🔐 Verifying data checksums")

        checksum_mismatches = []

        for table in export_results:
            source_checksum = export_results[table]["checksum"]
            target_checksum = import_results.get(table, {}).get("checksum", "")

            # Note: In this simulation, checksums are based on record count
            # so slight count variations will cause mismatches
            # In production, you'd compute actual data checksums

            # Simulate 5% chance of checksum mismatch
            if random.random() < 0.05:
                checksum_mismatches.append(table)
                logger.error(f"   ❌ {table}: {source_checksum} ≠ {target_checksum}")
            else:
                logger.info(f"   ✅ {table}: checksums match")

        if checksum_mismatches:
            msg = (
                f"Checksum verification failed for tables: {checksum_mismatches}. "
                f"Data integrity compromised - rolling back migration."
            )
            raise SagaStepError(msg)

        logger.info("✅ All checksums verified")

        return {
            "checksum_verified": True,
            "tables_verified": list(export_results.keys()),
        }

    @action("finalize_migration", depends_on=["verify_checksums"])
    async def finalize_migration(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Finalize migration and clean up temporary resources."""
        source_system = ctx.get("source_system")
        target_system = ctx.get("target_system")
        tables = ctx.get("tables", [])
        total_imported_records = ctx.get("total_imported_records", 0)

        logger.info("🎉 Finalizing migration")

        # Update migration registry
        migration_id = f"migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Clean up export/transform files (keeping backups for now)
        logger.info("   Cleaning up temporary files")
        await asyncio.sleep(0.1)

        # Update source system to mark as migrated
        logger.info(f"   Marking {source_system} tables as migrated")
        await asyncio.sleep(0.1)

        logger.info(f"✅ Migration complete: {migration_id}")
        logger.info(f"   Source: {source_system}")
        logger.info(f"   Target: {target_system}")
        logger.info(f"   Tables: {tables}")
        logger.info(f"   Records: {total_imported_records:,}")

        return {
            "migration_id": migration_id,
            "source_system": source_system,
            "target_system": target_system,
            "tables_migrated": tables,
            "total_records": total_imported_records,
            "completed_at": datetime.now().isoformat(),
            "status": "SUCCESS",
        }
