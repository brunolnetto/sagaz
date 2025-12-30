"""
Feature Store Pipeline Saga

Demonstrates feature engineering pipeline with transactional guarantees.
Shows how to handle data ingestion, transformation, validation, and publishing
to a feature store with automatic cleanup on failure.
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


class FeatureStoreSaga(Saga):
    """
    Feature engineering pipeline with transactional semantics.
    
    Pipeline Flow:
    1. Data Ingestion - Extract data from data lake
    2. Feature Computation - Transform and compute features
    3. Feature Validation - Validate schema and data quality
    4. Feature Store Publish - Atomically publish to feature store
    
    Ensures data consistency with automatic compensation on failures.
    """

    saga_name = "feature-store-pipeline"

    def __init__(
        self,
        feature_group_name: str,
        data_source: str,
        feature_definitions: list[dict[str, Any]],
        validation_rules: dict[str, Any] | None = None,
        target_store: str = "feast",
    ):
        """
        Initialize feature store pipeline.
        
        Args:
            feature_group_name: Name of feature group to create/update
            data_source: Path to raw data (S3, BigQuery, etc.)
            feature_definitions: List of feature specifications
            validation_rules: Data quality rules (schema, ranges, etc.)
            target_store: Feature store backend (feast, tecton, etc.)
        """
        super().__init__()
        self.feature_group_name = feature_group_name
        self.data_source = data_source
        self.feature_definitions = feature_definitions
        self.validation_rules = validation_rules or {
            "null_threshold": 0.1,
            "unique_threshold": 0.01,
            "schema_validation": True,
        }
        self.target_store = target_store

    @action("ingest_data")
    async def ingest_data(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """
        Ingest raw data from data lake.
        
        Data Sources:
        - S3/GCS object storage
        - Data warehouse (Snowflake, BigQuery)
        - Streaming (Kafka, Kinesis)
        - Database (PostgreSQL, MySQL)
        
        Processing:
        - Incremental ingestion with watermarks
        - Partitioning by date/entity
        - Deduplication
        - Schema inference
        
        Returns:
            Ingested data metadata and staging location
        """
        logger.info(f"📥 Ingesting data from: {self.data_source}")
        logger.info(f"Feature group: {self.feature_group_name}")

        await asyncio.sleep(0.3)  # Simulate data extraction

        # Simulate ingestion results
        records_ingested = random.randint(10000, 1000000)
        partitions = random.randint(10, 100)
        data_size_mb = random.uniform(10.0, 1000.0)

        # Create staging area
        staging_location = f"s3://feature-staging/{self.feature_group_name}/{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        logger.info("✅ Data ingested successfully")
        logger.info(f"Records: {records_ingested:,}")
        logger.info(f"Partitions: {partitions}")
        logger.info(f"Size: {data_size_mb:.2f} MB")
        logger.info(f"Staging: {staging_location}")

        return {
            "staging_location": staging_location,
            "records_ingested": records_ingested,
            "partitions": partitions,
            "data_size_mb": data_size_mb,
            "ingestion_timestamp": datetime.now().isoformat(),
        }

    @compensate("ingest_data")
    async def cleanup_staged_data(self, ctx: dict[str, Any]) -> None:
        """Remove staged data from temporary storage."""
        staging_location = ctx.get("staging_location")

        logger.warning(f"🧹 Cleaning up staged data: {staging_location}")

        if staging_location:
            logger.info(f"Removing staging data: {staging_location}")
            # In production: s3.delete_objects(staging_location)
            await asyncio.sleep(0.1)

    @action("compute_features", depends_on=["ingest_data"])
    async def compute_features(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """
        Compute features from raw data.
        
        Feature Types:
        - Aggregations (sum, mean, count, etc.)
        - Time windows (1h, 24h, 7d, 30d)
        - Ratios and percentages
        - Embeddings and encodings
        - Statistical features (std, percentiles)
        
        Optimization:
        - Parallel computation with Spark/Dask
        - Incremental updates
        - Caching intermediate results
        - GPU acceleration for embeddings
        
        Returns:
            Computed feature metadata and storage location
        """
        staging_location = ctx.get("staging_location")
        records_ingested = ctx.get("records_ingested", 0)

        logger.info(f"⚙️ Computing features for {records_ingested:,} records")
        logger.info(f"Feature definitions: {len(self.feature_definitions)}")

        # Simulate feature computation (can be parallelized)
        computed_features = []

        for i, feature_def in enumerate(self.feature_definitions):
            feature_name = feature_def.get("name", f"feature_{i}")
            feature_type = feature_def.get("type", "numeric")

            logger.info(f"Computing feature [{i+1}/{len(self.feature_definitions)}]: {feature_name} ({feature_type})")
            await asyncio.sleep(0.1)  # Simulate computation

            # Simulate feature statistics
            # Ensure reasonable null counts and unique values
            null_count = random.randint(0, int(records_ingested * 0.05))
            # Ensure at least 1% unique values for validation
            min_unique = max(10, int(records_ingested * 0.01))
            max_unique = records_ingested // 10
            unique_values = random.randint(min_unique, max(min_unique, max_unique))

            computed_features.append({
                "name": feature_name,
                "type": feature_type,
                "null_count": null_count,
                "unique_values": unique_values,
                "mean": random.uniform(-10, 10) if feature_type == "numeric" else None,
                "std": random.uniform(0, 5) if feature_type == "numeric" else None,
            })

        # Save computed features
        feature_location = f"s3://feature-computed/{self.feature_group_name}/{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        logger.info("✅ Feature computation complete")
        logger.info(f"Features computed: {len(computed_features)}")
        logger.info(f"Location: {feature_location}")

        return {
            "feature_location": feature_location,
            "computed_features": computed_features,
            "feature_count": len(computed_features),
            "computation_timestamp": datetime.now().isoformat(),
        }

    @compensate("compute_features")
    async def cleanup_computed_features(self, ctx: dict[str, Any]) -> None:
        """Remove computed feature artifacts."""
        feature_location = ctx.get("feature_location")

        logger.warning(f"🧹 Cleaning up computed features: {feature_location}")

        if feature_location:
            logger.info(f"Removing feature data: {feature_location}")
            # In production: s3.delete_objects(feature_location)
            await asyncio.sleep(0.1)

    @action("validate_features", depends_on=["compute_features"])
    async def validate_features(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """
        Validate feature data quality.
        
        Validation Checks:
        - Schema compliance
        - Data type validation
        - Null value thresholds
        - Value range checks
        - Statistical outlier detection
        - Duplicate detection
        - Temporal consistency
        
        Raises:
            SagaStepError: If validation fails critical checks
        
        Returns:
            Validation results and quality metrics
        """
        computed_features = ctx.get("computed_features", [])
        records_ingested = ctx.get("records_ingested", 0)

        logger.info(f"✅ Validating {len(computed_features)} features")
        logger.info(f"Validation rules: {self.validation_rules}")

        validation_results = []
        failed_validations = []

        for feature in computed_features:
            feature_name = feature["name"]
            null_count = feature.get("null_count", 0)
            null_ratio = null_count / records_ingested if records_ingested > 0 else 0

            # Check null threshold
            null_threshold = self.validation_rules.get("null_threshold", 0.1)
            null_check_passed = null_ratio <= null_threshold

            # Check uniqueness
            unique_values = feature.get("unique_values", 0)
            unique_ratio = unique_values / records_ingested if records_ingested > 0 else 0
            unique_threshold = self.validation_rules.get("unique_threshold", 0.01)
            unique_check_passed = unique_ratio >= unique_threshold

            # Schema validation
            schema_check_passed = feature.get("type") in ["numeric", "categorical", "text", "timestamp"]

            validation_result = {
                "feature": feature_name,
                "null_check": null_check_passed,
                "null_ratio": null_ratio,
                "unique_check": unique_check_passed,
                "unique_ratio": unique_ratio,
                "schema_check": schema_check_passed,
                "passed": null_check_passed and unique_check_passed and schema_check_passed,
            }

            validation_results.append(validation_result)

            if not validation_result["passed"]:
                failed_validations.append(feature_name)
                logger.warning(f"❌ Validation failed for {feature_name}")

        # Check if critical validations failed
        if failed_validations:
            raise SagaStepError(
                f"Feature validation failed for: {', '.join(failed_validations)}. "
                f"Cannot publish to feature store."
            )

        logger.info("✅ All feature validations passed")

        return {
            "validation_results": validation_results,
            "features_validated": len(computed_features),
            "validation_passed": True,
            "validation_timestamp": datetime.now().isoformat(),
        }

    @compensate("validate_features")
    async def cleanup_validation_artifacts(self, ctx: dict[str, Any]) -> None:
        """Clean up validation reports and artifacts."""
        logger.warning("🧹 Cleaning up validation artifacts")
        await asyncio.sleep(0.05)

    @action("publish_to_feature_store", depends_on=["validate_features"])
    async def publish_to_feature_store(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """
        Atomically publish features to feature store.
        
        Feature Store Operations:
        - Create/update feature group
        - Write feature values
        - Update metadata catalog
        - Register feature lineage
        - Create feature views
        - Update serving layer
        
        Transactional Guarantees:
        - All-or-nothing publish
        - Version control
        - Rollback on partial failure
        - Consistency across online/offline stores
        
        Returns:
            Feature store publish metadata
        """
        feature_location = ctx.get("feature_location")
        feature_count = ctx.get("feature_count", 0)
        records_ingested = ctx.get("records_ingested", 0)

        logger.info(f"📤 Publishing to {self.target_store} feature store")
        logger.info(f"Feature group: {self.feature_group_name}")
        logger.info(f"Features: {feature_count}")
        logger.info(f"Records: {records_ingested:,}")

        # Simulate feature store operations
        await asyncio.sleep(0.3)

        # Create feature group version
        feature_group_version = random.randint(1, 50)
        commit_id = f"commit-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Write to online store
        logger.info("Writing to online feature store...")
        await asyncio.sleep(0.2)

        # Write to offline store
        logger.info("Writing to offline feature store...")
        await asyncio.sleep(0.2)

        # Update metadata
        logger.info("Updating feature metadata catalog...")
        await asyncio.sleep(0.1)

        # Register lineage
        lineage_info = {
            "source": self.data_source,
            "ingestion_timestamp": ctx.get("ingestion_timestamp"),
            "computation_timestamp": ctx.get("computation_timestamp"),
            "validation_timestamp": ctx.get("validation_timestamp"),
            "publish_timestamp": datetime.now().isoformat(),
        }

        logger.info("✅ Features published successfully")
        logger.info(f"Feature group: {self.feature_group_name} v{feature_group_version}")
        logger.info(f"Commit ID: {commit_id}")

        return {
            "feature_group_version": feature_group_version,
            "commit_id": commit_id,
            "online_store_updated": True,
            "offline_store_updated": True,
            "metadata_updated": True,
            "lineage_registered": True,
            "lineage_info": lineage_info,
            "publish_timestamp": datetime.now().isoformat(),
        }

    @compensate("publish_to_feature_store")
    async def rollback_feature_store(self, ctx: dict[str, Any]) -> None:
        """
        Rollback feature store changes.
        
        Rollback Operations:
        - Revert feature group to previous version
        - Clear new feature values
        - Restore previous metadata
        - Remove lineage entries
        - Invalidate caches
        """
        logger.warning("⏪ Rolling back feature store changes")

        commit_id = ctx.get("commit_id")
        feature_group_version = ctx.get("feature_group_version")

        if commit_id:
            logger.info(f"Reverting commit: {commit_id}")

            # Rollback online store
            if ctx.get("online_store_updated"):
                logger.info("Rolling back online store...")
                await asyncio.sleep(0.2)

            # Rollback offline store
            if ctx.get("offline_store_updated"):
                logger.info("Rolling back offline store...")
                await asyncio.sleep(0.2)

            # Revert metadata
            if ctx.get("metadata_updated"):
                logger.info("Reverting metadata catalog...")
                await asyncio.sleep(0.1)

            logger.info("✅ Rollback complete - feature store restored to previous state")


async def successful_pipeline_demo():
    """Demonstrate successful feature pipeline execution."""
    print("\n" + "=" * 80)
    print("📊 Feature Store Pipeline - Successful Feature Publishing Demo")
    print("=" * 80)

    feature_definitions = [
        {"name": "user_age", "type": "numeric"},
        {"name": "user_tenure_days", "type": "numeric"},
        {"name": "total_purchases", "type": "numeric"},
        {"name": "avg_purchase_amount", "type": "numeric"},
        {"name": "last_purchase_category", "type": "categorical"},
        {"name": "user_segment", "type": "categorical"},
        {"name": "engagement_score", "type": "numeric"},
        {"name": "churn_probability", "type": "numeric"},
    ]

    saga = FeatureStoreSaga(
        feature_group_name="customer_features",
        data_source="s3://data-lake/raw/customers/2024-01-15/",
        feature_definitions=feature_definitions,
        validation_rules={
            "null_threshold": 0.15,
            "unique_threshold": 0.005,
            "schema_validation": True,
        },
        target_store="feast",
    )

    result = await saga.run({"pipeline_id": f"pipeline-{datetime.now().strftime('%Y%m%d')}"})

    print(f"\n{'✅' if result.get('saga_id') else '❌'} Feature Pipeline Result:")
    print(f"   Saga ID:               {result.get('saga_id')}")
    print(f"   Feature Group:         {saga.feature_group_name}")
    print(f"   Version:               v{result.get('feature_group_version')}")
    print(f"   Records Ingested:      {result.get('records_ingested', 0):,}")
    print(f"   Features Computed:     {result.get('feature_count')}")
    print(f"   Validation Status:     {result.get('validation_passed')}")
    print(f"   Online Store Updated:  {result.get('online_store_updated')}")
    print(f"   Offline Store Updated: {result.get('offline_store_updated')}")
    print(f"   Commit ID:             {result.get('commit_id')}")


async def failed_pipeline_demo():
    """Demonstrate pipeline failure with automatic rollback."""
    print("\n" + "=" * 80)
    print("⚠️  Feature Store Pipeline - Failed Pipeline with Rollback Demo")
    print("=" * 80)

    # Use very strict validation rules to increase failure probability
    feature_definitions = [
        {"name": "feature_1", "type": "numeric"},
        {"name": "feature_2", "type": "numeric"},
        {"name": "feature_3", "type": "categorical"},
    ]

    saga = FeatureStoreSaga(
        feature_group_name="experimental_features",
        data_source="s3://data-lake/raw/experiments/2024-01-15/",
        feature_definitions=feature_definitions,
        validation_rules={
            "null_threshold": 0.001,  # Very strict - 0.1% max nulls
            "unique_threshold": 0.1,   # Require high uniqueness
            "schema_validation": True,
        },
        target_store="tecton",
    )

    try:
        result = await saga.run({"pipeline_id": f"pipeline-exp-{datetime.now().strftime('%Y%m%d')}"})
        print(f"✅ Unexpectedly succeeded: {result.get('saga_id')}")
        print("   (Validation rules were lenient enough to pass)")
    except SagaStepError as e:
        print(f"\n❌ Pipeline failed as expected: {e}")
        print("✅ Automatic compensation completed successfully")
        print("   Staged data cleaned up")
        print("   Computed features removed")
        print("   Feature store not updated (consistency maintained)")
        print("   Ready for retry with adjusted validation rules")


async def main():
    """Run feature pipeline scenarios."""
    # Successful pipeline
    await successful_pipeline_demo()

    # Failed pipeline with rollback
    await failed_pipeline_demo()

    print("\n" + "=" * 80)
    print("📚 Feature Store Pipeline Demo Complete")
    print("=" * 80)
    print("\nKey Benefits:")
    print("  ✅ Transactional guarantees for feature updates")
    print("  ✅ Automatic cleanup of staging data on failure")
    print("  ✅ Data quality validation prevents bad features")
    print("  ✅ Consistent online/offline feature stores")
    print("  ✅ Full lineage tracking for reproducibility")
    print("  ✅ Rollback maintains feature store consistency")


if __name__ == "__main__":
    asyncio.run(main())
