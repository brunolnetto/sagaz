"""
ML Training Pipeline Saga Example

Demonstrates end-to-end machine learning pipeline orchestration with automatic
rollback capabilities using Sagaz. Shows how to handle resource cleanup,
model versioning, and deployment rollbacks in production MLOps workflows.
Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from sagaz import Saga, action, compensate
from sagaz.core.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MLTrainingPipelineSaga(Saga):
    """
    Production ML training pipeline with automatic rollback.

    This saga is stateless - all training configuration is passed through the context
    via the run() method.

    Expected context:
        - experiment_id: str
        - dataset_path: str
        - model_name: str
        - accuracy_threshold: float (optional, default 0.85)
        - hyperparameters: dict (optional)
    """

    saga_name = "ml-training-pipeline"

    @action("validate_dataset")
    async def validate_dataset(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Validate dataset quality, schema, and availability."""
        dataset_path = ctx.get("dataset_path")
        experiment_id = ctx.get("experiment_id")

        logger.info(f"🔍 Validating dataset: {dataset_path}")
        await asyncio.sleep(0.2)  # Simulate I/O

        # Simulate validation checks
        dataset_size = random.randint(10000, 100000)
        feature_count = random.randint(10, 50)
        missing_ratio = random.uniform(0.0, 0.1)

        if missing_ratio > 0.15:
            msg = f"Dataset has {missing_ratio:.1%} missing values (threshold: 15%)"
            raise SagaStepError(msg)

        # Create temporary validation artifacts
        temp_dir = Path("/tmp") / f"ml_validation_{experiment_id}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        validation_report = temp_dir / "validation_report.json"
        validation_report.write_text('{"status": "passed"}')

        logger.info(f"✅ Dataset validated: {dataset_size:,} records, {feature_count} features")

        return {
            "dataset_size": dataset_size,
            "feature_count": feature_count,
            "missing_ratio": missing_ratio,
            "validation_report_path": str(validation_report),
            "temp_dir": str(temp_dir),
        }

    @compensate("validate_dataset")
    async def cleanup_validation_artifacts(self, ctx: dict[str, Any]) -> None:
        """Clean up temporary validation artifacts."""
        experiment_id = ctx.get("experiment_id")
        logger.warning(f"🧹 Cleaning up validation artifacts for experiment {experiment_id}")

        temp_dir = ctx.get("temp_dir")
        if temp_dir:
            logger.info(f"Removing validation directory: {temp_dir}")
            # In production: shutil.rmtree(temp_dir)
            await asyncio.sleep(0.1)

    @action("engineer_features", depends_on=["validate_dataset"])
    async def engineer_features(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Transform raw data into ML features."""
        dataset_size = ctx.get("dataset_size", 0)
        feature_count = ctx.get("feature_count", 0)
        experiment_id = ctx.get("experiment_id")

        logger.info(f"⚙️ Engineering features for {dataset_size:,} records")
        await asyncio.sleep(0.3)  # Simulate feature computation

        # Simulate feature engineering
        engineered_features = feature_count + random.randint(5, 15)
        feature_importance_scores = [random.random() for _ in range(engineered_features)]

        # Save feature artifacts
        feature_dir = Path("/tmp") / f"ml_features_{experiment_id}"
        feature_dir.mkdir(parents=True, exist_ok=True)

        transformer_path = feature_dir / "feature_transformer.pkl"
        transformer_path.write_text("# Pickle transformer here")

        feature_list_path = feature_dir / "features.txt"
        feature_list_path.write_text(
            "\n".join([f"feature_{i}" for i in range(engineered_features)])
        )

        logger.info(f"✅ Feature engineering complete: {engineered_features} features")

        return {
            "engineered_feature_count": engineered_features,
            "feature_importance": feature_importance_scores,
            "transformer_path": str(transformer_path),
            "feature_list_path": str(feature_list_path),
            "feature_dir": str(feature_dir),
        }

    @compensate("engineer_features")
    async def cleanup_feature_artifacts(self, ctx: dict[str, Any]) -> None:
        """Remove feature engineering artifacts."""
        experiment_id = ctx.get("experiment_id")
        logger.warning(f"🧹 Cleaning up feature artifacts for experiment {experiment_id}")

        feature_dir = ctx.get("feature_dir")
        if feature_dir:
            logger.info(f"Removing feature directory: {feature_dir}")
            # In production: shutil.rmtree(feature_dir)
            await asyncio.sleep(0.1)

    @action("train_model", depends_on=["engineer_features"])
    async def train_model(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Train ML model with specified hyperparameters."""
        dataset_size = ctx.get("dataset_size", 0)
        feature_count = ctx.get("engineered_feature_count", 0)
        model_name = ctx.get("model_name")
        experiment_id = ctx.get("experiment_id")

        hyperparameters = ctx.get("hyperparameters") or {
            "learning_rate": 0.001,
            "batch_size": 32,
            "epochs": 10,
            "optimizer": "adam",
        }

        logger.info(f"🤖 Training model '{model_name}' with {hyperparameters}")
        logger.info(f"Training on {dataset_size:,} samples with {feature_count} features")

        # Simulate training epochs
        epochs = hyperparameters.get("epochs", 10)
        training_losses = []
        validation_losses = []

        for epoch in range(epochs):
            train_loss = 1.0 - (epoch / epochs) * 0.7 + random.uniform(-0.05, 0.05)
            val_loss = train_loss + random.uniform(0.0, 0.1)
            training_losses.append(train_loss)
            validation_losses.append(val_loss)

            if epoch % 3 == 0:
                logger.info(
                    f"Epoch {epoch + 1}/{epochs} - train_loss: {train_loss:.4f}, val_loss: {val_loss:.4f}"
                )

        await asyncio.sleep(0.5)  # Simulate training time

        # Save model artifacts
        model_dir = Path("/tmp") / f"ml_model_{experiment_id}"
        model_dir.mkdir(parents=True, exist_ok=True)

        model_path = model_dir / f"{model_name}.h5"
        model_path.write_text("# Model weights here")

        config_path = model_dir / "config.json"
        config_path.write_text(f'{{"hyperparameters": {hyperparameters}}}')

        logger.info(f"✅ Model training complete: final loss {training_losses[-1]:.4f}")

        return {
            "model_path": str(model_path),
            "config_path": str(config_path),
            "model_dir": str(model_dir),
            "training_losses": training_losses,
            "validation_losses": validation_losses,
            "epochs_trained": epochs,
        }

    @compensate("train_model")
    async def cleanup_model_artifacts(self, ctx: dict[str, Any]) -> None:
        """Remove model training artifacts."""
        experiment_id = ctx.get("experiment_id")
        logger.warning(f"🧹 Cleaning up model artifacts for experiment {experiment_id}")

        model_dir = ctx.get("model_dir")
        if model_dir:
            logger.info(f"Removing model directory: {model_dir}")
            # In production: shutil.rmtree(model_dir)
            await asyncio.sleep(0.1)

    @action("evaluate_model", depends_on=["train_model"])
    async def evaluate_model(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Evaluate model performance on test set."""
        model_path = ctx.get("model_path")
        accuracy_threshold = ctx.get("accuracy_threshold", 0.85)

        logger.info(f"📊 Evaluating model from {model_path}")
        await asyncio.sleep(0.3)  # Simulate evaluation

        # Simulate evaluation metrics
        accuracy = random.uniform(0.75, 0.95)
        precision = accuracy + random.uniform(-0.05, 0.05)
        recall = accuracy + random.uniform(-0.05, 0.05)
        f1_score = 2 * (precision * recall) / (precision + recall)
        auc_roc = accuracy + random.uniform(0.0, 0.05)

        logger.info("Model Metrics:")
        logger.info(f"  Accuracy:  {accuracy:.4f}")
        logger.info(f"  Precision: {precision:.4f}")
        logger.info(f"  Recall:    {recall:.4f}")
        logger.info(f"  F1 Score:  {f1_score:.4f}")
        logger.info(f"  AUC-ROC:   {auc_roc:.4f}")

        # Check accuracy threshold
        if accuracy < accuracy_threshold:
            msg = (
                f"Model accuracy {accuracy:.4f} below threshold {accuracy_threshold:.4f}. "
                f"Training failed - automatic rollback initiated."
            )
            raise SagaStepError(msg)

        logger.info(f"✅ Model evaluation passed: {accuracy:.4f} >= {accuracy_threshold:.4f}")

        return {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1_score,
            "auc_roc": auc_roc,
            "evaluation_passed": True,
        }

    @compensate("evaluate_model")
    async def cleanup_evaluation_artifacts(self, ctx: dict[str, Any]) -> None:
        """Clean up evaluation results and reports."""
        experiment_id = ctx.get("experiment_id")
        logger.warning(f"🧹 Cleaning up evaluation artifacts for experiment {experiment_id}")
        await asyncio.sleep(0.05)

    @action("register_model", depends_on=["evaluate_model"])
    async def register_model(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Register model in model registry (e.g., MLflow)."""
        accuracy = ctx.get("accuracy", 0.0)
        model_path = ctx.get("model_path")
        model_name = ctx.get("model_name")

        logger.info(f"📝 Registering model '{model_name}' in model registry")
        logger.info(f"Model path: {model_path}")
        logger.info(f"Metrics: accuracy={accuracy:.4f}")

        await asyncio.sleep(0.2)  # Simulate registry API call

        # Simulate model registry registration
        model_version = random.randint(1, 100)
        registry_uri = f"models:/{model_name}/{model_version}"

        logger.info(f"✅ Model registered: {registry_uri}")

        return {
            "model_version": model_version,
            "registry_uri": registry_uri,
            "registered_at": datetime.now().isoformat(),
            "model_status": "staged",
        }

    @compensate("register_model")
    async def deregister_model(self, ctx: dict[str, Any]) -> None:
        """Remove model from registry."""
        model_name = ctx.get("model_name")
        logger.warning(f"🧹 Deregistering model '{model_name}' from registry")

        registry_uri = ctx.get("registry_uri")

        if registry_uri:
            logger.info(f"Removing model: {registry_uri}")
            # In production: mlflow.delete_model_version(...)
            await asyncio.sleep(0.2)

    @action("deploy_model", depends_on=["register_model"])
    async def deploy_model(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Deploy model to production serving infrastructure."""
        registry_uri = ctx.get("registry_uri")
        model_version = ctx.get("model_version")
        model_name = ctx.get("model_name")
        experiment_id = ctx.get("experiment_id")

        logger.info("🚀 Deploying model to production")
        logger.info(f"Model: {registry_uri}")
        logger.info("Strategy: Blue/Green Deployment")

        await asyncio.sleep(0.4)  # Simulate deployment

        # Simulate deployment process
        deployment_id = f"deploy-{experiment_id}"
        endpoint_url = f"https://api.ml-platform.com/models/{model_name}/v{model_version}"

        # Health check
        await asyncio.sleep(0.1)
        health_status = "healthy"

        logger.info("✅ Model deployed successfully")
        logger.info(f"Endpoint: {endpoint_url}")
        logger.info(f"Health: {health_status}")

        return {
            "deployment_id": deployment_id,
            "endpoint_url": endpoint_url,
            "health_status": health_status,
            "deployed_at": datetime.now().isoformat(),
            "traffic_percentage": 100,
        }

    @compensate("deploy_model")
    async def rollback_deployment(self, ctx: dict[str, Any]) -> None:
        """Rollback deployment to previous model version."""
        model_name = ctx.get("model_name")
        logger.warning(f"⏪ Rolling back deployment for model '{model_name}'")

        deployment_id = ctx.get("deployment_id")

        if deployment_id:
            logger.info(f"Removing deployment: {deployment_id}")
            logger.info("Switching traffic to previous version")
            # In production: kubectl rollout undo deployment/{deployment_id}
            await asyncio.sleep(0.3)

            logger.info("✅ Rollback complete - traffic restored to previous version")


async def successful_pipeline_demo():
    """Demonstrate successful ML pipeline execution."""

    # Instantiate reusable saga
    saga = MLTrainingPipelineSaga()

    await saga.run(
        {
            "experiment_id": "exp-20240115-001",
            "dataset_path": "/data/training/customer_churn.parquet",
            "model_name": "churn-predictor",
            "accuracy_threshold": 0.80,  # Lenient threshold for demo
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
