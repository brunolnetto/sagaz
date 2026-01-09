"""
Edge Computing Federated Learning Saga Example

Demonstrates distributed ML model training across edge devices with privacy-
preserving federated learning, partial participation handling, and model rollback.
Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EdgeFederatedLearningSaga(Saga):
    """
    Federated learning orchestration across distributed edge devices.

    This saga is stateless - all data is passed through the context via the run() method.

    Expected context:
        - training_round_id: str
        - model_name: str
        - model_version: str
        - target_accuracy: float
        - min_participating_nodes: int
        - training_rounds: int
        - simulate_failure: bool (optional)
    """

    saga_name = "edge-federated-learning"

    @action("select_edge_nodes")
    async def select_edge_nodes(self, ctx: SagaContext) -> dict[str, Any]:
        """Select participating edge nodes based on availability and resources."""
        training_round_id = ctx.get("training_round_id")
        min_participating_nodes = ctx.get("min_participating_nodes", 10)

        logger.info(f"📱 Selecting edge nodes for training round {training_round_id}")
        await asyncio.sleep(0.15)

        # Simulate edge node selection
        selected_nodes = [
            {
                "node_id": f"EDGE-{i}",
                "location": f"Region-{(i % 5) + 1}",
                "device_type": "mobile" if i % 2 == 0 else "iot_gateway",
                "cpu_cores": 4 if i % 2 == 0 else 2,
                "available_memory_mb": 2048 if i % 2 == 0 else 1024,
                "battery_level": 85 + (i % 15),
                "network_quality": "4G" if i % 3 == 0 else "WiFi",
                "local_dataset_size": 1000 + (i * 100),
                "status": "available",
            }
            for i in range(1, 26)  # 25 edge nodes
        ]

        logger.info(
            f"   ✅ Selected {len(selected_nodes)} edge nodes "
            f"(min required: {min_participating_nodes})"
        )
        return {
            "nodes": selected_nodes,
            "total_nodes": len(selected_nodes),
            "total_dataset_size": sum(node["local_dataset_size"] for node in selected_nodes),
        }

    @compensate("select_edge_nodes")
    async def release_edge_nodes(self, ctx: SagaContext) -> None:
        """Release edge nodes back to available pool."""
        training_round_id = ctx.get("training_round_id")
        logger.warning(f"📱 Releasing edge nodes for training round {training_round_id}")

        total_nodes = ctx.get("total_nodes", 0)
        logger.info(f"   Releasing {total_nodes} edge nodes")
        logger.info("   Nodes returned to available pool")

        await asyncio.sleep(0.1)

    @action("distribute_model_weights", depends_on=["select_edge_nodes"])
    async def distribute_model_weights(self, ctx: SagaContext) -> dict[str, Any]:
        """Distribute current global model weights to all edge nodes."""
        model_name = ctx.get("model_name")
        model_version = ctx.get("model_version")

        logger.info(f"📤 Distributing model weights for {model_name} v{model_version}")
        await asyncio.sleep(0.2)

        nodes = ctx.get("nodes", [])

        # Simulate bandwidth-efficient model distribution
        distribution_result = {
            "model_name": model_name,
            "model_version": model_version,
            "model_size_mb": 45.2,
            "compression_used": "quantization + pruning",
            "compressed_size_mb": 8.5,
            "nodes_received": len(nodes),
            "distribution_method": "P2P + CDN fallback",
            "average_download_time_sec": 12.3,
            "failed_downloads": 0,
        }

        logger.info(
            f"   ✅ Distributed to {distribution_result['nodes_received']} nodes "
            f"({distribution_result['compressed_size_mb']} MB compressed)"
        )
        return distribution_result

    @compensate("distribute_model_weights")
    async def revoke_model_weights(self, ctx: SagaContext) -> None:
        """Revoke model weights from edge nodes (privacy/security)."""
        logger.warning("📤 Revoking model weights from edge nodes")

        nodes_received = ctx.get("nodes_received", 0)
        logger.info(f"   Revoking weights from {nodes_received} nodes")
        logger.info("   Model weights deleted from edge devices")

        await asyncio.sleep(0.15)

    @action("coordinate_local_training", depends_on=["distribute_model_weights"])
    async def coordinate_local_training(self, ctx: SagaContext) -> dict[str, Any]:
        """Coordinate local training rounds on edge devices."""
        training_rounds = ctx.get("training_rounds", 5)
        simulate_failure = ctx.get("simulate_failure", False)

        logger.info(f"🧠 Coordinating {training_rounds} training rounds on edge nodes")
        await asyncio.sleep(0.3)

        if simulate_failure:
            msg = "Insufficient edge nodes completed training - network connectivity issues"
            raise SagaStepError(msg)

        nodes = ctx.get("nodes", [])

        # Simulate federated training with partial participation
        training_result = {
            "training_round_id": ctx.get("training_round_id"),
            "total_rounds": training_rounds,
            "participating_nodes": len(nodes),
            "completed_nodes": int(len(nodes) * 0.88),  # 88% completion rate
            "failed_nodes": int(len(nodes) * 0.12),  # 12% failure rate
            "reasons_for_failure": {
                "battery_died": 1,
                "network_timeout": 1,
                "device_suspended": 1,
            },
            "average_training_time_sec": 245,
            "local_epochs_per_node": 3,
            "batch_size": 32,
        }

        logger.info(
            f"   ✅ Training complete: {training_result['completed_nodes']} nodes "
            f"({(training_result['completed_nodes'] / len(nodes)) * 100:.1f}%)"
        )
        return training_result

    @compensate("coordinate_local_training")
    async def stop_local_training(self, ctx: SagaContext) -> None:
        """Stop ongoing local training on edge nodes."""
        logger.warning("🧠 Stopping local training on edge nodes")

        participating_nodes = ctx.get("participating_nodes", 0)
        logger.info(f"   Stopping training on {participating_nodes} nodes")
        logger.info("   Local training processes terminated")

        await asyncio.sleep(0.1)

    @action("aggregate_model_updates", depends_on=["coordinate_local_training"])
    async def aggregate_model_updates(self, ctx: SagaContext) -> dict[str, Any]:
        """Aggregate model updates using federated averaging."""
        model_name = ctx.get("model_name")
        training_round_id = ctx.get("training_round_id")
        model_version = ctx.get("model_version")

        logger.info(f"🔄 Aggregating model updates for {model_name}")
        await asyncio.sleep(0.2)

        completed_nodes = ctx.get("completed_nodes", 0)

        # Simulate FedAvg (Federated Averaging) algorithm
        aggregation_result = {
            "training_round_id": training_round_id,
            "aggregation_method": "FedAvg (Weighted Average)",
            "updates_aggregated": completed_nodes,
            "aggregation_weights": "proportional to dataset size",
            "new_model_version": f"{model_version}-FL{training_round_id[-3:]}",
            "compression_ratio": 0.15,
            "privacy_guarantee": "differential privacy (ε=1.0)",
            "aggregation_time_sec": 18.5,
        }

        logger.info(
            f"   ✅ Aggregated {aggregation_result['updates_aggregated']} updates "
            f"(new version: {aggregation_result['new_model_version']})"
        )
        return aggregation_result

    @compensate("aggregate_model_updates")
    async def discard_aggregated_model(self, ctx: SagaContext) -> None:
        """Discard aggregated model (training failed)."""
        training_round_id = ctx.get("training_round_id")
        logging.warning(f"🔄 Discarding aggregated model for round {training_round_id}")

        new_model_version = ctx.get("new_model_version")
        logger.info(f"   Discarding model version {new_model_version}")
        logger.info("   Previous model version remains active")

        await asyncio.sleep(0.05)

    @action("validate_global_model", depends_on=["aggregate_model_updates"])
    async def validate_global_model(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate aggregated global model accuracy on holdout dataset."""
        model_name = ctx.get("model_name")
        target_accuracy = ctx.get("target_accuracy", 0.0)

        logger.info(f"✅ Validating global model for {model_name}")
        await asyncio.sleep(0.2)

        new_model_version = ctx.get("new_model_version")

        # Simulate model validation
        validation_result = {
            "model_version": new_model_version,
            "validation_dataset_size": 10000,
            "accuracy": 0.89,  # 89% accuracy
            "precision": 0.87,
            "recall": 0.86,
            "f1_score": 0.865,
            "target_accuracy": target_accuracy,
            "accuracy_achieved": target_accuracy <= 0.89,
            "previous_accuracy": 0.82,
            "improvement": 0.07,
        }

        status = "✅ PASSED" if validation_result["accuracy_achieved"] else "❌ FAILED"
        logger.info(
            f"   {status} Accuracy: {validation_result['accuracy']:.2%} "
            f"(target: {target_accuracy:.2%})"
        )
        return validation_result

    @compensate("validate_global_model")
    async def log_validation_failure(self, ctx: SagaContext) -> None:
        """Log validation failure for analysis."""
        training_round_id = ctx.get("training_round_id")
        logger.warning(f"✅ Logging validation failure for round {training_round_id}")

        model_version = ctx.get("model_version")
        accuracy = ctx.get("accuracy", 0)

        logger.info(f"   Model {model_version} failed validation (accuracy: {accuracy:.2%})")
        logger.info("   Analysis data saved for debugging")

        await asyncio.sleep(0.05)

    @action("deploy_updated_model", depends_on=["validate_global_model"])
    async def deploy_updated_model(self, ctx: SagaContext) -> dict[str, Any]:
        """Deploy updated model to edge fleet (idempotent)."""
        logger.info("🚀 Deploying updated model to edge fleet")
        await asyncio.sleep(0.25)

        new_model_version = ctx.get("new_model_version")
        accuracy = ctx.get("accuracy", 0)

        # Simulate gradual rollout
        deployment_result = {
            "model_version": new_model_version,
            "deployment_strategy": "canary (10% → 50% → 100%)",
            "total_edge_devices": 1000,
            "devices_updated": 1000,
            "rollout_duration_min": 45,
            "validation_passed": True,
            "production_metrics": {
                "inference_latency_ms": 8.5,
                "memory_usage_mb": 45,
                "battery_impact_percent": 2.1,
            },
        }

        logger.info(
            f"   ✅ Deployed {new_model_version} to {deployment_result['devices_updated']} devices "
            f"(accuracy: {accuracy:.2%})"
        )
        return deployment_result


async def main():
    """Run the edge federated learning saga demo."""

    # Reusable saga instance
    saga = EdgeFederatedLearningSaga()

    # Scenario 1: Successful federated learning round

    success_data = {
        "training_round_id": "FL-ROUND-042",
        "model_name": "user-behavior-predictor",
        "model_version": "3.2.0",
        "target_accuracy": 0.85,
        "min_participating_nodes": 10,
        "training_rounds": 5,
        "simulate_failure": False,
    }

    await saga.run(success_data)

    # Scenario 2: Insufficient node participation with rollback

    failure_data = {
        "training_round_id": "FL-ROUND-043",
        "model_name": "user-behavior-predictor",
        "model_version": "3.2.0",
        "target_accuracy": 0.85,
        "min_participating_nodes": 10,
        "training_rounds": 5,
        "simulate_failure": True,  # Simulate insufficient node completion
    }

    try:
        await saga.run(failure_data)
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
