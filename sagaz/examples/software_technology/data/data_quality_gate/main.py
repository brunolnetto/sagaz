"""
Data Quality Gate Saga Example

Demonstrates data validation pipeline with automatic rejection and quarantine.
Shows how Sagaz enforces data quality gates before loading to production systems.

Key features:
- Schema validation
- Null/duplicate checks
- Business rule validation
- Automatic quarantine on failure
- Rollback of partial loads

Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Any

from sagaz import Saga, action, compensate
from sagaz.core.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DataQualityGateSaga(Saga):
    """
    Data quality validation pipeline with automatic rejection.

    This saga enforces data quality before loading to production:
    1. Ingest raw data to landing zone
    2. Validate schema compatibility
    3. Check for nulls in required fields
    4. Check for duplicates
    5. Apply business rule validations
    6. Load to production or quarantine on failure

    Expected context:
        - dataset_path: str - Path to incoming dataset
        - target_table: str - Target production table
        - quality_rules: dict - Quality thresholds and rules
    """

    saga_name = "data-quality-gate"

    @action("ingest_to_landing")
    async def ingest_to_landing(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Ingest raw data to landing zone for validation."""
        dataset_path = ctx.get("dataset_path")

        logger.info(f"📥 Ingesting data from {dataset_path} to landing zone")
        await asyncio.sleep(0.2)

        # Simulate ingestion
        record_count = random.randint(5000, 50000)
        landing_path = f"/landing/{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        logger.info(f"✅ Ingested {record_count:,} records to {landing_path}")

        return {
            "landing_path": landing_path,
            "raw_record_count": record_count,
            "ingest_timestamp": datetime.now().isoformat(),
        }

    @compensate("ingest_to_landing")
    async def cleanup_landing(self, ctx: dict[str, Any]) -> None:
        """Clean up landing zone data on failure."""
        landing_path = ctx.get("landing_path")

        if landing_path:
            logger.warning(f"🧹 Cleaning up landing zone: {landing_path}")
            await asyncio.sleep(0.1)
            logger.info(f"Removed: {landing_path}")

    @action("validate_schema", depends_on=["ingest_to_landing"])
    async def validate_schema(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Validate schema compatibility with target table."""
        ctx.get("landing_path")
        target_table = ctx.get("target_table")

        logger.info(f"📋 Validating schema against {target_table}")
        await asyncio.sleep(0.15)

        # Simulate schema validation
        expected_columns = ["id", "timestamp", "user_id", "event_type", "payload"]
        actual_columns = expected_columns.copy()

        # Simulate occasional schema mismatch
        if random.random() < 0.05:  # 5% schema failure
            actual_columns.remove("user_id")
            missing = set(expected_columns) - set(actual_columns)
            msg = f"Schema validation failed. Missing columns: {missing}. Data will be quarantined."
            raise SagaStepError(msg)

        logger.info(f"✅ Schema valid: {len(expected_columns)} columns match")

        return {
            "schema_valid": True,
            "column_count": len(expected_columns),
            "validated_columns": expected_columns,
        }

    @compensate("validate_schema")
    async def log_schema_failure(self, ctx: dict[str, Any]) -> None:
        """Log schema validation failure."""
        dataset_path = ctx.get("dataset_path")
        logger.warning(f"📝 Schema validation failed for {dataset_path}")

        # In production: Write to data quality log, alert data team
        await asyncio.sleep(0.05)

    @action("check_nulls", depends_on=["validate_schema"])
    async def check_nulls(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Check for null values in required fields."""
        landing_path = ctx.get("landing_path")
        raw_record_count = ctx.get("raw_record_count", 0)
        quality_rules = ctx.get("quality_rules") or {}
        null_threshold = quality_rules.get("null_threshold", 0.05)

        logger.info(f"🔍 Checking nulls in {landing_path} (threshold: {null_threshold:.1%})")
        await asyncio.sleep(0.2)

        # Simulate null check
        null_counts = {
            "id": 0,
            "timestamp": int(raw_record_count * random.uniform(0.0, 0.01)),
            "user_id": int(raw_record_count * random.uniform(0.0, 0.08)),
            "event_type": int(raw_record_count * random.uniform(0.0, 0.02)),
            "payload": int(raw_record_count * random.uniform(0.0, 0.1)),
        }

        total_nulls = sum(null_counts.values())
        null_ratio = total_nulls / (raw_record_count * len(null_counts))

        # Check threshold
        if null_ratio > null_threshold:
            msg = (
                f"Null check failed: {null_ratio:.2%} nulls exceeds {null_threshold:.1%} threshold. "
                f"Breakdown: {null_counts}"
            )
            raise SagaStepError(msg)

        logger.info(f"✅ Null check passed: {null_ratio:.2%} nulls (below {null_threshold:.1%})")

        return {
            "null_check_passed": True,
            "null_counts": null_counts,
            "null_ratio": null_ratio,
        }

    @compensate("check_nulls")
    async def quarantine_null_data(self, ctx: dict[str, Any]) -> None:
        """Move data with excessive nulls to quarantine."""
        ctx.get("landing_path")
        null_counts = ctx.get("null_counts", {})

        quarantine_path = f"/quarantine/nulls/{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.warning(f"🔒 Quarantining data with null issues to {quarantine_path}")
        logger.warning(f"   Null counts: {null_counts}")

        # In production: Move data to quarantine bucket
        await asyncio.sleep(0.1)

    @action("check_duplicates", depends_on=["check_nulls"])
    async def check_duplicates(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Check for duplicate records."""
        raw_record_count = ctx.get("raw_record_count", 0)
        quality_rules = ctx.get("quality_rules") or {}
        duplicate_threshold = quality_rules.get("duplicate_threshold", 0.01)

        logger.info(f"🔍 Checking duplicates (threshold: {duplicate_threshold:.1%})")
        await asyncio.sleep(0.15)

        # Simulate duplicate check
        duplicate_count = int(raw_record_count * random.uniform(0.0, 0.03))
        duplicate_ratio = duplicate_count / raw_record_count

        if duplicate_ratio > duplicate_threshold:
            msg = (
                f"Duplicate check failed: {duplicate_ratio:.2%} duplicates exceeds "
                f"{duplicate_threshold:.1%} threshold ({duplicate_count:,} records)"
            )
            raise SagaStepError(msg)

        logger.info(f"✅ Duplicate check passed: {duplicate_ratio:.2%} duplicates")

        return {
            "duplicate_check_passed": True,
            "duplicate_count": duplicate_count,
            "duplicate_ratio": duplicate_ratio,
        }

    @compensate("check_duplicates")
    async def log_duplicate_failure(self, ctx: dict[str, Any]) -> None:
        """Log duplicate detection failure."""
        duplicate_count = ctx.get("duplicate_count", 0)
        logger.warning(f"📝 Duplicate check failed: {duplicate_count:,} duplicates found")
        await asyncio.sleep(0.05)

    @action("validate_business_rules", depends_on=["check_duplicates"])
    async def validate_business_rules(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Apply business-specific validation rules."""
        raw_record_count = ctx.get("raw_record_count", 0)
        quality_rules = ctx.get("quality_rules") or {}

        logger.info("📊 Applying business rule validations")
        await asyncio.sleep(0.2)

        # Simulate business rule checks
        rules_applied = []
        violations = {}

        # Rule 1: Event timestamps must be within last 7 days
        future_events = int(raw_record_count * random.uniform(0.0, 0.02))
        if future_events > 0:
            violations["future_timestamps"] = future_events
        rules_applied.append("timestamp_recency")

        # Rule 2: User IDs must follow format
        invalid_user_ids = int(raw_record_count * random.uniform(0.0, 0.01))
        if invalid_user_ids > 0:
            violations["invalid_user_id_format"] = invalid_user_ids
        rules_applied.append("user_id_format")

        # Rule 3: Event types must be from allowed list
        unknown_events = int(raw_record_count * random.uniform(0.0, 0.005))
        if unknown_events > 0:
            violations["unknown_event_types"] = unknown_events
        rules_applied.append("event_type_whitelist")

        # Check if violations exceed threshold
        total_violations = sum(violations.values())
        violation_ratio = total_violations / raw_record_count

        max_violation_ratio = quality_rules.get("max_violation_ratio", 0.05)

        if violation_ratio > max_violation_ratio:
            msg = (
                f"Business rules failed: {violation_ratio:.2%} violations exceeds "
                f"{max_violation_ratio:.1%} threshold. Details: {violations}"
            )
            raise SagaStepError(msg)

        logger.info(
            f"✅ Business rules passed: {len(rules_applied)} rules, {total_violations:,} minor violations"
        )

        return {
            "business_rules_passed": True,
            "rules_applied": rules_applied,
            "violations": violations,
            "violation_ratio": violation_ratio,
        }

    @compensate("validate_business_rules")
    async def quarantine_rule_violations(self, ctx: dict[str, Any]) -> None:
        """Quarantine data that violates business rules."""
        violations = ctx.get("violations", {})

        quarantine_path = f"/quarantine/rules/{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.warning(f"🔒 Quarantining data with rule violations to {quarantine_path}")
        logger.warning(f"   Violations: {violations}")

        await asyncio.sleep(0.1)

    @action("load_to_production", depends_on=["validate_business_rules"])
    async def load_to_production(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Load validated data to production table."""
        ctx.get("landing_path")
        target_table = ctx.get("target_table")
        raw_record_count = ctx.get("raw_record_count", 0)
        duplicate_count = ctx.get("duplicate_count", 0)

        final_count = raw_record_count - duplicate_count

        logger.info(f"🚀 Loading {final_count:,} validated records to {target_table}")
        await asyncio.sleep(0.3)

        logger.info(f"✅ Production load complete: {final_count:,} records")

        return {
            "production_load_complete": True,
            "loaded_record_count": final_count,
            "target_table": target_table,
            "load_timestamp": datetime.now().isoformat(),
        }

    @compensate("load_to_production")
    async def rollback_production_load(self, ctx: dict[str, Any]) -> None:
        """Rollback production load if post-load checks fail."""
        target_table = ctx.get("target_table")
        loaded_record_count = ctx.get("loaded_record_count", 0)

        logger.warning(f"⏪ Rolling back {loaded_record_count:,} records from {target_table}")

        # In production: DELETE FROM target_table WHERE batch_id = ...
        await asyncio.sleep(0.2)
        logger.info("Rollback complete")

    @action("update_quality_metrics", depends_on=["load_to_production"])
    async def update_quality_metrics(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Record quality metrics for monitoring."""
        raw_record_count = ctx.get("raw_record_count", 0)
        loaded_record_count = ctx.get("loaded_record_count", 0)
        null_ratio = ctx.get("null_ratio", 0.0)
        duplicate_ratio = ctx.get("duplicate_ratio", 0.0)
        violation_ratio = ctx.get("violation_ratio", 0.0)

        logger.info("📈 Recording quality metrics")
        await asyncio.sleep(0.1)

        quality_score = 1.0 - (null_ratio + duplicate_ratio + violation_ratio)

        metrics = {
            "quality_score": quality_score,
            "raw_record_count": raw_record_count,
            "loaded_record_count": loaded_record_count,
            "null_ratio": null_ratio,
            "duplicate_ratio": duplicate_ratio,
            "violation_ratio": violation_ratio,
            "recorded_at": datetime.now().isoformat(),
        }

        logger.info(f"✅ Quality score: {quality_score:.2%}")

        return metrics


async def successful_quality_gate_demo():
    """Demonstrate successful data quality validation."""

    saga = DataQualityGateSaga()

    await saga.run(
        {
            "dataset_path": "/incoming/sales_events_20260106.parquet",
            "target_table": "production.sales_events",
            "quality_rules": {
                "null_threshold": 0.10,  # Allow up to 10% nulls
                "duplicate_threshold": 0.05,  # Allow up to 5% duplicates
                "max_violation_ratio": 0.03,  # Allow up to 3% rule violations
            },
        }
    )


async def failed_quality_gate_demo():
    """Demonstrate quality gate failure with quarantine."""

    saga = DataQualityGateSaga()

    # Strict quality rules that are likely to fail
    try:
        await saga.run(
            {
                "dataset_path": "/incoming/user_events_messy.parquet",
                "target_table": "production.user_events",
                "quality_rules": {
                    "null_threshold": 0.01,  # Very strict: 1% nulls
                    "duplicate_threshold": 0.005,  # Very strict: 0.5% duplicates
                    "max_violation_ratio": 0.001,  # Very strict: 0.1% violations
                },
            }
        )
    except SagaStepError:
        pass


async def main():
    """Run data quality gate demos."""
    await successful_quality_gate_demo()
    await failed_quality_gate_demo()


if __name__ == "__main__":
    asyncio.run(main())
