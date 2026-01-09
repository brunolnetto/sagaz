"""
ETL Pipeline Saga Example

Demonstrates Extract-Transform-Load orchestration with automatic rollback.
Shows how Sagaz handles multi-step data pipelines with compensation for:
- Staging table cleanup on transform failure
- Partial load rollback on warehouse errors
- Resource cleanup at every stage

Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Any

from sagaz import Saga, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ETLPipelineSaga(Saga):
    """
    Production ETL pipeline with automatic rollback on failure.

    This saga orchestrates a complete ETL workflow:
    1. Extract data from source (API, database, files)
    2. Load to staging table
    3. Transform with business logic
    4. Validate transformed data
    5. Load to target warehouse table
    6. Update metadata catalog

    Expected context:
        - source_table: str - Source table/path to extract from
        - target_table: str - Target warehouse table
        - batch_date: str - Date partition for the batch
        - transform_config: dict (optional) - Transformation settings
    """

    saga_name = "etl-pipeline"

    @action("extract_from_source")
    async def extract_from_source(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Extract data from source system."""
        source_table = ctx.get("source_table")
        batch_date = ctx.get("batch_date")

        logger.info(f"📥 Extracting from {source_table} for {batch_date}")
        await asyncio.sleep(0.2)  # Simulate I/O

        # Simulate extraction
        record_count = random.randint(10000, 100000)
        extract_path = f"/tmp/extract/{source_table}_{batch_date}.parquet"

        # Simulate possible extraction failure
        if random.random() < 0.05:  # 5% failure rate
            msg = f"Source system unavailable: {source_table}"
            raise SagaStepError(msg)

        logger.info(f"✅ Extracted {record_count:,} records to {extract_path}")

        return {
            "extract_path": extract_path,
            "source_record_count": record_count,
            "extract_timestamp": datetime.now().isoformat(),
        }

    @compensate("extract_from_source")
    async def cleanup_extract_files(self, ctx: dict[str, Any]) -> None:
        """Clean up extracted files on failure."""
        extract_path = ctx.get("extract_path")
        logger.warning(f"🧹 Cleaning up extract files: {extract_path}")

        # In production: os.remove(extract_path) or shutil.rmtree()
        await asyncio.sleep(0.1)
        logger.info(f"Removed: {extract_path}")

    @action("load_to_staging", depends_on=["extract_from_source"])
    async def load_to_staging(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Load extracted data to staging table."""
        ctx.get("extract_path")
        batch_date = ctx.get("batch_date")
        source_record_count = ctx.get("source_record_count", 0)

        # Generate unique staging table name
        staging_table = f"staging.etl_{batch_date.replace('-', '')}_{random.randint(1000, 9999)}"  # type: ignore[union-attr]

        logger.info(f"📤 Loading {source_record_count:,} records to {staging_table}")
        await asyncio.sleep(0.3)  # Simulate database load

        # Simulate staging load
        loaded_count = source_record_count  # Assume all records loaded

        logger.info(f"✅ Staging table created: {staging_table}")

        return {
            "staging_table": staging_table,
            "staging_record_count": loaded_count,
            "staging_timestamp": datetime.now().isoformat(),
        }

    @compensate("load_to_staging")
    async def drop_staging_table(self, ctx: dict[str, Any]) -> None:
        """Drop staging table on failure."""
        staging_table = ctx.get("staging_table")

        if staging_table:
            logger.warning(f"🧹 Dropping staging table: {staging_table}")
            # In production: await db.execute(f"DROP TABLE IF EXISTS {staging_table}")
            await asyncio.sleep(0.1)
            logger.info(f"Dropped: {staging_table}")

    @action("transform_data", depends_on=["load_to_staging"])
    async def transform_data(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Apply business transformations to staging data."""
        staging_table = ctx.get("staging_table")
        staging_record_count = ctx.get("staging_record_count", 0)
        transform_config = ctx.get("transform_config") or {
            "deduplicate": True,
            "null_handling": "drop",
            "normalize_dates": True,
        }

        logger.info(f"⚙️ Transforming {staging_table} with config: {transform_config}")
        await asyncio.sleep(0.4)  # Simulate transformation

        # Simulate transformation results
        dedup_removed = int(staging_record_count * random.uniform(0.01, 0.05))
        null_removed = int(staging_record_count * random.uniform(0.005, 0.02))
        transformed_count = staging_record_count - dedup_removed - null_removed

        # Create transformed staging table
        transformed_table = f"{staging_table}_transformed"

        logger.info("✅ Transformation complete:")
        logger.info(f"   Duplicates removed: {dedup_removed:,}")
        logger.info(f"   Nulls handled: {null_removed:,}")
        logger.info(f"   Output records: {transformed_count:,}")

        return {
            "transformed_table": transformed_table,
            "transformed_record_count": transformed_count,
            "duplicates_removed": dedup_removed,
            "nulls_handled": null_removed,
            "transform_config_used": transform_config,
        }

    @compensate("transform_data")
    async def drop_transformed_table(self, ctx: dict[str, Any]) -> None:
        """Drop transformed staging table on failure."""
        transformed_table = ctx.get("transformed_table")

        if transformed_table:
            logger.warning(f"🧹 Dropping transformed table: {transformed_table}")
            await asyncio.sleep(0.1)
            logger.info(f"Dropped: {transformed_table}")

    @action("validate_data", depends_on=["transform_data"])
    async def validate_data(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Validate transformed data before loading to warehouse."""
        transformed_table = ctx.get("transformed_table")
        transformed_record_count = ctx.get("transformed_record_count", 0)

        logger.info(f"🔍 Validating {transformed_table}")
        await asyncio.sleep(0.2)

        # Simulate validation checks
        schema_valid = True
        null_check_passed = random.random() > 0.1  # 10% chance of null check failure
        row_count_valid = transformed_record_count > 0

        validation_results = {
            "schema_valid": schema_valid,
            "null_check_passed": null_check_passed,
            "row_count_valid": row_count_valid,
            "validated_at": datetime.now().isoformat(),
        }

        # Check for validation failures
        if not null_check_passed:
            msg = (
                "Data validation failed: Unexpected nulls in required columns. "
                "Automatic rollback initiated - staging tables will be cleaned up."
            )
            raise SagaStepError(msg)

        if not row_count_valid:
            msg = "Data validation failed: Zero records after transformation"
            raise SagaStepError(msg)

        logger.info("✅ All validation checks passed")

        return validation_results

    @compensate("validate_data")
    async def log_validation_failure(self, ctx: dict[str, Any]) -> None:
        """Log validation failure details for debugging."""
        batch_date = ctx.get("batch_date")
        logger.warning(f"📝 Logging validation failure for batch {batch_date}")

        # In production: Write to audit log, send alert, etc.
        await asyncio.sleep(0.05)

    @action("load_to_warehouse", depends_on=["validate_data"])
    async def load_to_warehouse(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Load validated data to target warehouse table."""
        ctx.get("transformed_table")
        target_table = ctx.get("target_table")
        transformed_record_count = ctx.get("transformed_record_count", 0)
        batch_date = ctx.get("batch_date")

        logger.info(f"🏭 Loading {transformed_record_count:,} records to {target_table}")
        logger.info(f"   Partition: batch_date={batch_date}")
        await asyncio.sleep(0.5)  # Simulate warehouse load

        # Generate partition path
        partition_path = f"{target_table}/batch_date={batch_date}"

        logger.info(f"✅ Warehouse load complete: {partition_path}")

        return {
            "partition_path": partition_path,
            "loaded_record_count": transformed_record_count,
            "load_timestamp": datetime.now().isoformat(),
        }

    @compensate("load_to_warehouse")
    async def delete_warehouse_partition(self, ctx: dict[str, Any]) -> None:
        """Delete the loaded partition on failure."""
        partition_path = ctx.get("partition_path")
        ctx.get("target_table")
        ctx.get("batch_date")

        if partition_path:
            logger.warning(f"🧹 Deleting warehouse partition: {partition_path}")
            # In production: DELETE FROM {target_table} WHERE batch_date = '{batch_date}'
            await asyncio.sleep(0.2)
            logger.info(f"Deleted partition: {partition_path}")

    @action("update_catalog", depends_on=["load_to_warehouse"])
    async def update_catalog(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Update metadata catalog with new partition info."""
        target_table = ctx.get("target_table")
        batch_date = ctx.get("batch_date")
        loaded_record_count = ctx.get("loaded_record_count", 0)

        logger.info(f"📚 Updating catalog for {target_table}")
        await asyncio.sleep(0.1)

        # In production: MSCK REPAIR TABLE or ALTER TABLE ADD PARTITION
        catalog_entry = {
            "table": target_table,
            "partition": {"batch_date": batch_date},
            "record_count": loaded_record_count,
            "updated_at": datetime.now().isoformat(),
        }

        logger.info(f"✅ Catalog updated: {catalog_entry}")

        return {
            "catalog_entry": catalog_entry,
            "catalog_updated": True,
        }

    @compensate("update_catalog")
    async def revert_catalog(self, ctx: dict[str, Any]) -> None:
        """Revert catalog entry on failure."""
        target_table = ctx.get("target_table")
        batch_date = ctx.get("batch_date")

        logger.warning(f"🧹 Reverting catalog entry for {target_table}/{batch_date}")
        # In production: ALTER TABLE DROP PARTITION
        await asyncio.sleep(0.05)


async def successful_etl_demo():
    """Demonstrate successful ETL pipeline execution."""

    saga = ETLPipelineSaga()

    await saga.run(
        {
            "source_table": "raw_events.clickstream",
            "target_table": "warehouse.fact_events",
            "batch_date": "2026-01-06",
            "transform_config": {
                "deduplicate": True,
                "null_handling": "drop",
                "normalize_dates": True,
                "timezone": "UTC",
            },
        }
    )


async def failed_etl_demo():
    """Demonstrate ETL pipeline failure with automatic rollback."""

    saga = ETLPipelineSaga()

    # Run multiple times to demonstrate failure handling
    for attempt in range(3):
        try:
            await saga.run(
                {
                    "source_table": "raw_events.user_actions",
                    "target_table": "warehouse.dim_users",
                    "batch_date": f"2026-01-0{attempt + 1}",
                }
            )
        except SagaStepError:
            break


async def main():
    """Run ETL pipeline demos."""
    await successful_etl_demo()
    await failed_etl_demo()


if __name__ == "__main__":
    asyncio.run(main())
