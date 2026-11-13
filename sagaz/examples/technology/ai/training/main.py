"""
ML Training Pipeline Saga Example

Demonstrates end-to-end machine learning pipeline orchestration with automatic
rollback capabilities using Sagaz. Shows how to handle resource cleanup,
model versioning, and deployment rollbacks in production MLOps workflows.
Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging

from sagaz.core.exceptions import SagaStepError
from sagaz.examples.technology.ai.training.saga import MLTrainingPipelineSaga

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def successful_pipeline_demo():
    """Demonstrate successful ML pipeline execution."""

    # Instantiate reusable saga
    saga = MLTrainingPipelineSaga()

    await saga.run(
        {
            "experiment_id": "exp-20240115-001",
            "dataset_path": "/data/training/customer_churn.parquet",
            "model_name": "churn-predictor",
            "accuracy_threshold": 0.75,  # Realistic threshold for demo success
            "hyperparameters": {
                "learning_rate": 0.001,
                "batch_size": 64,
                "epochs": 15,
                "optimizer": "adam",
                "dropout": 0.3,
            },
        }
    )


async def failed_pipeline_demo():
    """Demonstrate pipeline failure and automatic rollback."""

    saga = MLTrainingPipelineSaga()

    try:
        await saga.run(
            {
                "experiment_id": "exp-20240115-002",
                "dataset_path": "/data/training/customer_churn.parquet",
                "model_name": "churn-predictor",
                "accuracy_threshold": 0.95,  # Very high threshold - likely to fail
                "hyperparameters": {
                    "learning_rate": 0.01,  # High learning rate - may cause instability
                    "batch_size": 32,
                    "epochs": 5,  # Too few epochs
                    "optimizer": "sgd",
                },
            }
        )
    except SagaStepError:
        pass


async def main():
    """Run both success and failure scenarios."""
    # Run successful pipeline
    await successful_pipeline_demo()

    # Run failed pipeline with automatic rollback
    await failed_pipeline_demo()


if __name__ == "__main__":
    asyncio.run(main())
