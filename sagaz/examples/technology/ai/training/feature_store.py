"""
Feature Store Pipeline Saga

Demonstrates feature engineering pipeline with transactional guarantees.
Shows how to handle data ingestion, transformation, validation, and publishing
to a feature store with automatic cleanup on failure.
Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging
from datetime import datetime

from sagaz.core.exceptions import SagaStepError
from sagaz.examples.technology.ai.training.feature_store_saga import FeatureStoreSaga

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def successful_pipeline_demo():
    """Demonstrate successful feature pipeline execution."""

    # Reusable saga instance
    saga = FeatureStoreSaga()

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

    pipeline_data = {
        "feature_group_name": "customer_features",
        "data_source": "s3://data-lake/raw/customers/2024-01-15/",
        "feature_definitions": feature_definitions,
        "validation_rules": {
            "null_threshold": 0.15,
            "unique_threshold": 0.005,
            "schema_validation": True,
        },
        "target_store": "feast",
        "pipeline_id": f"pipeline-{datetime.now().strftime('%Y%m%d')}",
    }

    await saga.run(pipeline_data)


async def failed_pipeline_demo():
    """Demonstrate pipeline failure with automatic rollback."""

    # Use very strict validation rules to increase failure probability
    feature_definitions = [
        {"name": "feature_1", "type": "numeric"},
        {"name": "feature_2", "type": "numeric"},
        {"name": "feature_3", "type": "categorical"},
    ]

    saga = FeatureStoreSaga()

    pipeline_data = {
        "feature_group_name": "experimental_features",
        "data_source": "s3://data-lake/raw/experiments/2024-01-15/",
        "feature_definitions": feature_definitions,
        "validation_rules": {
            "null_threshold": 0.001,  # Very strict - 0.1% max nulls
            "unique_threshold": 0.1,  # Require high uniqueness
            "schema_validation": True,
        },
        "target_store": "tecton",
        "pipeline_id": f"pipeline-exp-{datetime.now().strftime('%Y%m%d')}",
    }

    try:
        await saga.run(pipeline_data)
    except SagaStepError:
        pass


async def main():
    """Run feature pipeline scenarios."""
    # Successful pipeline
    await successful_pipeline_demo()

    # Failed pipeline with rollback
    await failed_pipeline_demo()


if __name__ == "__main__":
    asyncio.run(main())
