"""
Model Deployment Saga with Blue/Green Strategy

Demonstrates production-grade model deployment with automatic rollback
capabilities. Implements blue/green deployment pattern with smoke tests
and gradual traffic shifting.
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


class ModelDeploymentSaga(Saga):
    """
    Production model deployment with blue/green strategy and automatic rollback.

    This saga is stateless - all deployment configuration is passed through the context
    via the run() method.

    Expected context:
        - model_name: str
        - model_version: int
        - registry_uri: str
        - deployment_environment: str (optional, default "production")
        - canary_percentage: int (optional, default 10)
        - smoke_test_timeout: float (optional, default 30.0)
    """

    saga_name = "model-deployment"

    @action("backup_current_model")
    async def backup_current_model(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Create backup snapshot of current production model."""
        model_name = ctx.get("model_name")
        model_version = ctx.get("model_version")

        logger.info(f"💾 Backing up current production model: {model_name}")
        await asyncio.sleep(0.2)  # Simulate backup operation

        # Simulate current production state
        current_version = model_version - 1 if model_version > 1 else 1
        backup_id = f"backup-{model_name}-v{current_version}-{int(datetime.now().timestamp())}"

        logger.info(f"Current production version: v{current_version}")
        logger.info(f"Backup ID: {backup_id}")

        # Store backup metadata
        backup_location = f"s3://ml-backups/{model_name}/{backup_id}"

        logger.info(f"✅ Backup created: {backup_location}")

        return {
            "backup_id": backup_id,
            "backup_location": backup_location,
            "previous_version": current_version,
            "previous_registry_uri": f"models:/{model_name}/{current_version}",
            "backup_timestamp": datetime.now().isoformat(),
        }

    @compensate("backup_current_model")
    async def cleanup_backup(self, ctx: dict[str, Any]) -> None:
        """Remove temporary backup if deployment fails early."""
        backup_id = ctx.get("backup_id")
        backup_location = ctx.get("backup_location")

        logger.warning(f"🧹 Cleaning up backup: {backup_id}")

        if backup_location:
            logger.info(f"Removing backup: {backup_location}")
            # In production: s3.delete_object(backup_location)
            await asyncio.sleep(0.1)

    @action("deploy_to_staging", depends_on=["backup_current_model"])
    async def deploy_to_staging(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Deploy new model version to staging environment."""
        model_name = ctx.get("model_name")
        model_version = ctx.get("model_version")
        registry_uri = ctx.get("registry_uri")

        logger.info(f"🚀 Deploying model v{model_version} to staging")
        logger.info(f"Registry: {registry_uri}")

        await asyncio.sleep(0.3)  # Simulate deployment

        # Simulate staging deployment
        staging_endpoint = f"https://staging.ml-platform.com/models/{model_name}/v{model_version}"
        staging_deployment_id = f"staging-{model_name}-v{model_version}"

        # Simulate container startup
        await asyncio.sleep(0.2)

        # Health check
        health_check_passed = random.random() > 0.05  # 95% success rate

        if not health_check_passed:
            msg = f"Staging deployment health check failed for {staging_deployment_id}"
            raise SagaStepError(msg)

        logger.info("✅ Staging deployment successful")
        logger.info(f"Endpoint: {staging_endpoint}")

        return {
            "staging_deployment_id": staging_deployment_id,
            "staging_endpoint": staging_endpoint,
            "staging_health": "healthy",
            "deployed_at": datetime.now().isoformat(),
        }

    @compensate("deploy_to_staging")
    async def teardown_staging(self, ctx: dict[str, Any]) -> None:
        """Remove staging deployment."""
        staging_deployment_id = ctx.get("staging_deployment_id")

        logger.warning(f"🧹 Tearing down staging deployment: {staging_deployment_id}")

        if staging_deployment_id:
            logger.info(f"Deleting staging resources: {staging_deployment_id}")
            # In production: kubectl delete deployment {staging_deployment_id}
            await asyncio.sleep(0.2)

    @action("run_smoke_tests", depends_on=["deploy_to_staging"])
    async def run_smoke_tests(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Execute smoke test suite against staging deployment."""
        staging_endpoint = ctx.get("staging_endpoint")
        model_version = ctx.get("model_version")
        smoke_test_timeout = ctx.get("smoke_test_timeout", 30.0)

        logger.info(f"🧪 Running smoke tests against: {staging_endpoint}")
        logger.info(f"Timeout: {smoke_test_timeout}s")

        # Simulate test execution
        test_cases = [
            "prediction_accuracy",
            "response_latency",
            "error_handling",
            "input_validation",
            "output_format",
            "memory_usage",
        ]

        test_results = {}
        failed_tests = []

        for i, test_case in enumerate(test_cases):
            logger.info(f"Running test [{i + 1}/{len(test_cases)}]: {test_case}")
            await asyncio.sleep(0.1)  # Simulate test execution

            # Simulate test result (95% pass rate)
            passed = random.random() > 0.05
            test_results[test_case] = {
                "passed": passed,
                "duration": random.uniform(0.1, 1.0),
            }

            if not passed:
                failed_tests.append(test_case)

        # Check if critical tests failed
        if failed_tests:
            msg = (
                f"Smoke tests failed: {', '.join(failed_tests)}. "
                f"Model v{model_version} cannot be deployed to production."
            )
            raise SagaStepError(msg)

        # Performance metrics
        avg_latency = sum(t["duration"] for t in test_results.values()) / len(test_results)

        logger.info("✅ All smoke tests passed")
        logger.info(f"Average latency: {avg_latency:.3f}s")

        return {
            "smoke_tests_passed": True,
            "test_results": test_results,
            "average_latency": avg_latency,
            "tests_executed": len(test_cases),
        }

    @compensate("run_smoke_tests")
    async def cleanup_test_resources(self, ctx: dict[str, Any]) -> None:
        """Clean up test data and resources."""
        logger.warning("🧹 Cleaning up smoke test resources")
        await asyncio.sleep(0.05)

    @action("blue_green_deployment", depends_on=["run_smoke_tests"])
    async def blue_green_deployment(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Execute blue/green deployment to production."""
        model_name = ctx.get("model_name")
        model_version = ctx.get("model_version")
        canary_percentage = ctx.get("canary_percentage", 10)
        previous_version = ctx.get("previous_version", 0)

        logger.info("🔄 Initiating blue/green deployment")
        logger.info(f"Model: {model_name} v{model_version}")
        logger.info(f"Strategy: Canary with {canary_percentage}% traffic")

        # Deploy green version
        logger.info("Deploying green version...")
        await asyncio.sleep(0.3)

        green_deployment_id = f"prod-{model_name}-v{model_version}"
        green_endpoint = f"https://api.ml-platform.com/models/{model_name}/v{model_version}"

        # Initial canary traffic
        logger.info(f"Routing {canary_percentage}% traffic to green version")
        await asyncio.sleep(0.2)

        # Monitor canary metrics
        canary_error_rate = random.uniform(0.0, 0.02)
        canary_latency = random.uniform(0.05, 0.15)

        logger.info(
            f"Canary metrics - Error rate: {canary_error_rate:.2%}, Latency: {canary_latency:.3f}s"
        )

        # Check canary health
        if canary_error_rate > 0.05:  # 5% threshold
            msg = (
                f"Canary deployment failed: error rate {canary_error_rate:.2%} exceeds 5% threshold"
            )
            raise SagaStepError(msg)

        # Gradual traffic increase
        traffic_percentages = [canary_percentage, 25, 50, 75, 100]
        for traffic_pct in traffic_percentages[1:]:
            logger.info(f"Increasing traffic to {traffic_pct}%")
            await asyncio.sleep(0.15)

        logger.info("✅ Blue/green deployment complete - 100% traffic on green")

        return {
            "green_deployment_id": green_deployment_id,
            "green_endpoint": green_endpoint,
            "blue_deployment_id": f"prod-{model_name}-v{previous_version}",
            "traffic_distribution": {"green": 100, "blue": 0},
            "canary_error_rate": canary_error_rate,
            "canary_latency": canary_latency,
            "deployment_strategy": "blue-green",
        }

    @compensate("blue_green_deployment")
    async def rollback_to_blue(self, ctx: dict[str, Any]) -> None:
        """Rollback production traffic to blue (previous) version."""
        logger.warning("⏪ ROLLBACK: Switching traffic back to blue version")

        green_deployment_id = ctx.get("green_deployment_id")
        previous_version = ctx.get("previous_version")

        logger.info(f"Routing 100% traffic to blue: v{previous_version}")
        # In production: update load balancer / service mesh routing
        await asyncio.sleep(0.2)

        logger.info(f"Terminating green deployment: {green_deployment_id}")
        # In production: kubectl delete deployment {green_deployment_id}
        await asyncio.sleep(0.2)

        logger.info("Validating blue version health...")
        await asyncio.sleep(0.1)

        logger.info(f"✅ Rollback complete - production traffic on blue v{previous_version}")
        logger.info(f"Green deployment {green_deployment_id} terminated")

    @action("monitor_health", depends_on=["blue_green_deployment"])
    async def monitor_health(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Monitor production health after deployment."""
        green_endpoint = ctx.get("green_endpoint")

        logger.info(f"📊 Monitoring production health: {green_endpoint}")

        # Simulate monitoring period
        monitoring_duration = 5  # seconds
        samples = []

        for i in range(monitoring_duration):
            await asyncio.sleep(0.2)

            # Simulate metrics
            error_rate = random.uniform(0.0, 0.02)
            latency = random.uniform(0.05, 0.20)
            throughput = random.randint(100, 500)

            samples.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "error_rate": error_rate,
                    "latency": latency,
                    "throughput": throughput,
                }
            )

            if i % 2 == 0:
                logger.info(
                    f"Health check [{i + 1}/{monitoring_duration}] - "
                    f"errors: {error_rate:.2%}, latency: {latency:.3f}s"
                )

        # Calculate aggregate metrics
        avg_error_rate = sum(s["error_rate"] for s in samples) / len(samples)
        avg_latency = sum(s["latency"] for s in samples) / len(samples)
        avg_throughput = sum(s["throughput"] for s in samples) / len(samples)

        logger.info("✅ Health monitoring complete")
        logger.info(
            f"Averages - Error: {avg_error_rate:.2%}, Latency: {avg_latency:.3f}s, Throughput: {avg_throughput:.0f} req/s"
        )

        return {
            "health_status": "healthy",
            "monitoring_samples": samples,
            "avg_error_rate": avg_error_rate,
            "avg_latency": avg_latency,
            "avg_throughput": avg_throughput,
            "monitoring_duration": monitoring_duration,
        }


async def successful_deployment_demo():
    """Demonstrate successful model deployment."""

    # Reusable saga instance
    saga = ModelDeploymentSaga()

    deployment_data = {
        "model_name": "fraud-detector",
        "model_version": 15,
        "registry_uri": "models:/fraud-detector/15",
        "deployment_environment": "production",
        "canary_percentage": 10,
        "smoke_test_timeout": 30.0,
        "deployment_id": "deploy-15",
    }

    await saga.run(deployment_data)


async def failed_deployment_demo():
    """Demonstrate deployment failure with automatic rollback."""

    saga = ModelDeploymentSaga()

    base_data = {
        "model_name": "recommendation-engine",
        "model_version": 42,
        "registry_uri": "models:/recommendation-engine/42",
        "deployment_environment": "production",
        "canary_percentage": 5,
        "smoke_test_timeout": 30.0,
    }

    # Run multiple times to potentially trigger failure
    for attempt in range(1, 4):
        try:
            data = base_data.copy()
            data["deployment_id"] = f"deploy-42-attempt{attempt}"

            await saga.run(data)
            break
        except SagaStepError:
            if attempt < 3:
                await asyncio.sleep(1)
            else:
                pass


async def main():
    """Run deployment scenarios."""
    # Successful deployment
    await successful_deployment_demo()

    # Failed deployment with rollback
    await failed_deployment_demo()


if __name__ == "__main__":
    asyncio.run(main())
