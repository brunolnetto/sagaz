"""
Lakehouse Ingestion Saga Example

Demonstrates Bronze → Silver → Gold medallion architecture with layer-by-layer rollback.
Shows how Sagaz handles multi-layer data lakehouse ingestion with compensation.

Key features:
- Raw data ingestion to Bronze layer
- Data cleaning and validation for Silver layer
- Business aggregations for Gold layer
- Layer-by-layer rollback on failure
- Data lineage tracking

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
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class LakehouseIngestionSaga(Saga):
    """
    Medallion architecture ingestion saga (Bronze → Silver → Gold).

    This saga implements the medallion lakehouse pattern:
    1. Bronze: Ingest raw data as-is
    2. Silver: Clean, deduplicate, validate
    3. Gold: Aggregate and prepare for analytics

    Each layer has compensation to roll back on failure.

    Expected context:
        - source_path: str - Path to source data (S3, ADLS, etc.)
        - bronze_table: str - Bronze layer table name
        - silver_table: str - Silver layer table name
        - gold_table: str - Gold layer table name
        - partition_date: str (optional) - Date partition
    """

    saga_name = "lakehouse-ingestion"

    @action("ingest_to_bronze")
    async def ingest_to_bronze(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """
        Bronze Layer: Ingest raw data as-is.

        - No transformations
        - Preserve original schema
        - Add ingestion metadata
        """
        source_path = ctx.get("source_path")
        bronze_table = ctx.get("bronze_table")
        partition_date = ctx.get("partition_date") or datetime.now().strftime("%Y-%m-%d")

        logger.info("🥉 BRONZE: Ingesting raw data")
        logger.info(f"   Source: {source_path}")
        logger.info(f"   Target: {bronze_table}")
        await asyncio.sleep(0.3)

        # Simulate raw ingestion
        raw_record_count = random.randint(50000, 200000)
        raw_file_count = random.randint(10, 50)

        # Add ingestion metadata
        ingestion_id = f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        bronze_path = f"{bronze_table}/partition_date={partition_date}/{ingestion_id}"

        # Simulate possible ingestion failure (source unavailable)
        if random.random() < 0.03:  # 3% failure rate
            msg = f"Source unavailable: {source_path}"
            raise SagaStepError(msg)

        logger.info(f"✅ BRONZE complete: {raw_record_count:,} records from {raw_file_count} files")

        return {
            "ingestion_id": ingestion_id,
            "bronze_path": bronze_path,
            "bronze_record_count": raw_record_count,
            "bronze_file_count": raw_file_count,
            "partition_date": partition_date,
            "bronze_timestamp": datetime.now().isoformat(),
        }

    @compensate("ingest_to_bronze")
    async def delete_bronze_partition(self, ctx: dict[str, Any]) -> None:
        """Delete Bronze layer partition on failure."""
        bronze_path = ctx.get("bronze_path")
        bronze_record_count = ctx.get("bronze_record_count", 0)

        if bronze_path:
            logger.warning("🧹 BRONZE: Deleting partition")
            logger.warning(f"   Path: {bronze_path}")
            logger.warning(f"   Records: {bronze_record_count:,}")
            # In production: DELETE FROM bronze_table WHERE partition_date = ...
            await asyncio.sleep(0.2)
            logger.info("Bronze partition deleted")

    @action("process_to_silver", depends_on=["ingest_to_bronze"])
    async def process_to_silver(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """
        Silver Layer: Clean and validate data.

        - Remove duplicates
        - Handle null values
        - Validate data types
        - Apply business rules
        """
        bronze_table = ctx.get("bronze_table")
        silver_table = ctx.get("silver_table")
        bronze_record_count = ctx.get("bronze_record_count", 0)
        partition_date = ctx.get("partition_date")

        logger.info("🥈 SILVER: Processing and cleaning data")
        logger.info(f"   Source: {bronze_table}")
        logger.info(f"   Target: {silver_table}")
        await asyncio.sleep(0.4)

        # Simulate cleaning operations
        duplicates_removed = int(bronze_record_count * random.uniform(0.02, 0.08))
        nulls_filled = int(bronze_record_count * random.uniform(0.01, 0.05))
        invalid_removed = int(bronze_record_count * random.uniform(0.005, 0.02))

        silver_record_count = bronze_record_count - duplicates_removed - invalid_removed

        # Check data quality threshold
        quality_ratio = silver_record_count / bronze_record_count
        if quality_ratio < 0.85:  # Less than 85% data retained
            msg = (
                f"Silver processing failed: Only {quality_ratio:.1%} data retained. "
                f"Threshold is 85%. Check source data quality."
            )
            raise SagaStepError(
                msg
            )

        silver_path = f"{silver_table}/partition_date={partition_date}"

        logger.info(f"   Duplicates removed: {duplicates_removed:,}")
        logger.info(f"   Nulls filled: {nulls_filled:,}")
        logger.info(f"   Invalid records removed: {invalid_removed:,}")
        logger.info(f"✅ SILVER complete: {silver_record_count:,} records ({quality_ratio:.1%} retained)")

        return {
            "silver_path": silver_path,
            "silver_record_count": silver_record_count,
            "duplicates_removed": duplicates_removed,
            "nulls_filled": nulls_filled,
            "invalid_removed": invalid_removed,
            "quality_ratio": quality_ratio,
            "silver_timestamp": datetime.now().isoformat(),
        }

    @compensate("process_to_silver")
    async def delete_silver_partition(self, ctx: dict[str, Any]) -> None:
        """Delete Silver layer partition on failure."""
        silver_path = ctx.get("silver_path")
        silver_record_count = ctx.get("silver_record_count", 0)

        if silver_path:
            logger.warning("🧹 SILVER: Deleting partition")
            logger.warning(f"   Path: {silver_path}")
            logger.warning(f"   Records: {silver_record_count:,}")
            await asyncio.sleep(0.15)
            logger.info("Silver partition deleted")

    @action("aggregate_to_gold", depends_on=["process_to_silver"])
    async def aggregate_to_gold(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """
        Gold Layer: Aggregate for business analytics.

        - Compute business metrics
        - Create dimensional aggregations
        - Optimize for query performance
        """
        silver_table = ctx.get("silver_table")
        gold_table = ctx.get("gold_table")
        silver_record_count = ctx.get("silver_record_count", 0)
        partition_date = ctx.get("partition_date")

        logger.info("🥇 GOLD: Aggregating for analytics")
        logger.info(f"   Source: {silver_table}")
        logger.info(f"   Target: {gold_table}")
        await asyncio.sleep(0.5)

        # Simulate aggregation
        # Gold layer typically has far fewer records (aggregated)
        aggregation_factor = random.randint(50, 200)
        gold_record_count = max(silver_record_count // aggregation_factor, 100)

        # Simulate aggregation metrics
        aggregations_computed = [
            "daily_event_counts",
            "hourly_user_activity",
            "category_metrics",
            "geographic_distribution",
            "conversion_funnels",
        ]

        gold_path = f"{gold_table}/partition_date={partition_date}"

        # Simulate occasional aggregation failure
        if random.random() < 0.05:  # 5% failure rate
            msg = (
                "Gold aggregation failed: Insufficient memory for aggregation. "
                "Consider increasing cluster resources."
            )
            raise SagaStepError(
                msg
            )

        logger.info(f"   Aggregations: {aggregations_computed}")
        logger.info(f"✅ GOLD complete: {gold_record_count:,} aggregated records")

        return {
            "gold_path": gold_path,
            "gold_record_count": gold_record_count,
            "aggregations_computed": aggregations_computed,
            "aggregation_factor": aggregation_factor,
            "gold_timestamp": datetime.now().isoformat(),
        }

    @compensate("aggregate_to_gold")
    async def delete_gold_partition(self, ctx: dict[str, Any]) -> None:
        """Delete Gold layer partition on failure."""
        gold_path = ctx.get("gold_path")
        gold_record_count = ctx.get("gold_record_count", 0)

        if gold_path:
            logger.warning("🧹 GOLD: Deleting partition")
            logger.warning(f"   Path: {gold_path}")
            logger.warning(f"   Records: {gold_record_count:,}")
            await asyncio.sleep(0.1)
            logger.info("Gold partition deleted")

    @action("update_data_catalog", depends_on=["aggregate_to_gold"])
    async def update_data_catalog(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Update data catalog with new partitions and lineage."""
        bronze_table = ctx.get("bronze_table")
        silver_table = ctx.get("silver_table")
        gold_table = ctx.get("gold_table")
        partition_date = ctx.get("partition_date")
        ingestion_id = ctx.get("ingestion_id")

        logger.info("📚 Updating data catalog")
        await asyncio.sleep(0.1)

        # Create lineage record
        lineage = {
            "ingestion_id": ingestion_id,
            "source": ctx.get("source_path"),
            "bronze": bronze_table,
            "silver": silver_table,
            "gold": gold_table,
            "partition_date": partition_date,
            "bronze_count": ctx.get("bronze_record_count"),
            "silver_count": ctx.get("silver_record_count"),
            "gold_count": ctx.get("gold_record_count"),
            "quality_ratio": ctx.get("quality_ratio"),
        }

        # Register partitions
        for _layer, table in [("bronze", bronze_table), ("silver", silver_table), ("gold", gold_table)]:
            logger.info(f"   Registered: {table}/partition_date={partition_date}")

        logger.info(f"✅ Catalog updated with lineage: {ingestion_id}")

        return {
            "catalog_updated": True,
            "lineage": lineage,
        }

    @compensate("update_data_catalog")
    async def remove_catalog_entries(self, ctx: dict[str, Any]) -> None:
        """Remove catalog entries on failure."""
        ingestion_id = ctx.get("ingestion_id")

        logger.warning(f"🧹 Removing catalog entries for ingestion: {ingestion_id}")
        await asyncio.sleep(0.05)

    @action("notify_downstream", depends_on=["update_data_catalog"])
    async def notify_downstream(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Notify downstream consumers that new data is available."""
        ctx.get("gold_table")
        ctx.get("partition_date")

        logger.info("📢 Notifying downstream consumers")
        await asyncio.sleep(0.1)

        # Simulate notifications
        notifications_sent = [
            {"consumer": "analytics_dashboard", "status": "notified"},
            {"consumer": "ml_feature_store", "status": "notified"},
            {"consumer": "reporting_service", "status": "notified"},
        ]

        logger.info(f"✅ Notified {len(notifications_sent)} downstream consumers")

        return {
            "notifications_sent": notifications_sent,
            "notification_timestamp": datetime.now().isoformat(),
        }


async def successful_lakehouse_demo():
    """Demonstrate successful lakehouse ingestion."""

    saga = LakehouseIngestionSaga()

    await saga.run({
        "source_path": "s3://data-lake-raw/events/clickstream/",
        "bronze_table": "bronze.raw_clickstream",
        "silver_table": "silver.cleaned_clickstream",
        "gold_table": "gold.clickstream_metrics",
        "partition_date": "2026-01-06",
    })



async def failed_lakehouse_demo():
    """Demonstrate lakehouse ingestion failure with layer-by-layer rollback."""

    saga = LakehouseIngestionSaga()

    for attempt in range(5):
        try:
            await saga.run({
                "source_path": "s3://data-lake-raw/events/user_actions/",
                "bronze_table": "bronze.raw_user_actions",
                "silver_table": "silver.cleaned_user_actions",
                "gold_table": "gold.user_action_metrics",
                "partition_date": f"2026-01-0{attempt + 1}",
            })
        except SagaStepError:
            break


async def main():
    """Run lakehouse ingestion demos."""
    await successful_lakehouse_demo()
    await failed_lakehouse_demo()



if __name__ == "__main__":
    asyncio.run(main())
