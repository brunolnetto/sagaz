"""
Edge Computing Federated Learning Saga Example

Demonstrates distributed ML model training across edge devices with privacy-
preserving federated learning, partial participation handling, and model rollback.
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
    """Federated learning orchestration across distributed edge devices."""

    saga_name = "edge-federated-learning"

    def __init__(
        self,
        training_round_id: str,
        model_name: str,
        model_version: str,
        target_accuracy: float,
        min_participating_nodes: int = 10,
        training_rounds: int = 5,
        simulate_failure: bool = False,
    ):
        super().__init__()
        self.training_round_id = training_round_id
        self.model_name = model_name
        self.model_version = model_version
        self.target_accuracy = target_accuracy
        self.min_participating_nodes = min_participating_nodes
        self.training_rounds = training_rounds
        self.simulate_failure = simulate_failure

    @action("select_edge_nodes")
    async def select_edge_nodes(self, ctx: SagaContext) -> dict[str, Any]:
        """Select participating edge nodes based on availability and resources."""
        logger.info(f"📱 Selecting edge nodes for training round {self.training_round_id}")
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
            f"(min required: {self.min_participating_nodes})"
        )
        return {
            "nodes": selected_nodes,
            "total_nodes": len(selected_nodes),
            "total_dataset_size": sum(node["local_dataset_size"] for node in selected_nodes),
        }

    @compensate("select_edge_nodes")
    async def release_edge_nodes(self, ctx: SagaContext) -> None:
        """Release edge nodes back to available pool."""
        logger.warning(f"📱 Releasing edge nodes for training round {self.training_round_id}")

        total_nodes = ctx.get("total_nodes", 0)
        logger.info(f"   Releasing {total_nodes} edge nodes")
        logger.info("   Nodes returned to available pool")

        await asyncio.sleep(0.1)

    @action("distribute_model_weights", depends_on=["select_edge_nodes"])
    async def distribute_model_weights(self, ctx: SagaContext) -> dict[str, Any]:
        """Distribute current global model weights to all edge nodes."""
        logger.info(f"📤 Distributing model weights for {self.model_name} v{self.model_version}")
        await asyncio.sleep(0.2)

        nodes = ctx.get("nodes", [])

        # Simulate bandwidth-efficient model distribution
        distribution_result = {
            "model_name": self.model_name,
            "model_version": self.model_version,
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
        logger.warning(f"📤 Revoking model weights from edge nodes")

        nodes_received = ctx.get("nodes_received", 0)
        logger.info(f"   Revoking weights from {nodes_received} nodes")
        logger.info("   Model weights deleted from edge devices")

        await asyncio.sleep(0.15)

    @action("coordinate_local_training", depends_on=["distribute_model_weights"])
    async def coordinate_local_training(self, ctx: SagaContext) -> dict[str, Any]:
        """Coordinate local training rounds on edge devices."""
        logger.info(f"🧠 Coordinating {self.training_rounds} training rounds on edge nodes")
        await asyncio.sleep(0.3)

        if self.simulate_failure:
            raise SagaStepError(
                "Insufficient edge nodes completed training - network connectivity issues"
            )

        nodes = ctx.get("nodes", [])

        # Simulate federated training with partial participation
        training_result = {
            "training_round_id": self.training_round_id,
            "total_rounds": self.training_rounds,
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
            f"({(training_result['completed_nodes']/len(nodes))*100:.1f}%)"
        )
        return training_result

    @compensate("coordinate_local_training")
    async def stop_local_training(self, ctx: SagaContext) -> None:
        """Stop ongoing local training on edge nodes."""
        logger.warning(f"🧠 Stopping local training on edge nodes")

        participating_nodes = ctx.get("participating_nodes", 0)
        logger.info(f"   Stopping training on {participating_nodes} nodes")
        logger.info("   Local training processes terminated")

        await asyncio.sleep(0.1)

    @action("aggregate_model_updates", depends_on=["coordinate_local_training"])
    async def aggregate_model_updates(self, ctx: SagaContext) -> dict[str, Any]:
        """Aggregate model updates using federated averaging."""
        logger.info(f"🔄 Aggregating model updates for {self.model_name}")
        await asyncio.sleep(0.2)

        completed_nodes = ctx.get("completed_nodes", 0)

        # Simulate FedAvg (Federated Averaging) algorithm
        aggregation_result = {
            "training_round_id": self.training_round_id,
            "aggregation_method": "FedAvg (Weighted Average)",
            "updates_aggregated": completed_nodes,
            "aggregation_weights": "proportional to dataset size",
            "new_model_version": f"{self.model_version}-FL{self.training_round_id[-3:]}",
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
        logger.warning(f"🔄 Discarding aggregated model for round {self.training_round_id}")

        new_model_version = ctx.get("new_model_version")
        logger.info(f"   Discarding model version {new_model_version}")
        logger.info("   Previous model version remains active")

        await asyncio.sleep(0.05)

    @action("validate_global_model", depends_on=["aggregate_model_updates"])
    async def validate_global_model(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate aggregated global model accuracy on holdout dataset."""
        logger.info(f"✅ Validating global model for {self.model_name}")
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
            "target_accuracy": self.target_accuracy,
            "accuracy_achieved": 0.89 >= self.target_accuracy,
            "previous_accuracy": 0.82,
            "improvement": 0.07,
        }

        status = "✅ PASSED" if validation_result["accuracy_achieved"] else "❌ FAILED"
        logger.info(
            f"   {status} Accuracy: {validation_result['accuracy']:.2%} "
            f"(target: {self.target_accuracy:.2%})"
        )
        return validation_result

    @compensate("validate_global_model")
    async def log_validation_failure(self, ctx: SagaContext) -> None:
        """Log validation failure for analysis."""
        logger.warning(f"✅ Logging validation failure for round {self.training_round_id}")

        model_version = ctx.get("model_version")
        accuracy = ctx.get("accuracy", 0)

        logger.info(f"   Model {model_version} failed validation (accuracy: {accuracy:.2%})")
        logger.info("   Analysis data saved for debugging")

        await asyncio.sleep(0.05)

    @action("deploy_updated_model", depends_on=["validate_global_model"])
    async def deploy_updated_model(self, ctx: SagaContext) -> dict[str, Any]:
        """Deploy updated model to edge fleet (idempotent)."""
        logger.info(f"🚀 Deploying updated model to edge fleet")
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
    print("=" * 80)
    print("Edge Computing Federated Learning Saga Demo - Distributed ML Training")
    print("=" * 80)

    # Scenario 1: Successful federated learning round
    print("\n🟢 Scenario 1: Successful Federated Learning Round")
    print("-" * 80)

    saga_success = EdgeFederatedLearningSaga(
        training_round_id="FL-ROUND-042",
        model_name="user-behavior-predictor",
        model_version="3.2.0",
        target_accuracy=0.85,
        min_participating_nodes=10,
        training_rounds=5,
        simulate_failure=False,
    )

    result_success = await saga_success.run({"training_round_id": saga_success.training_round_id})

    print(f"\n{'✅' if result_success.get('saga_id') else '❌'} Federated Learning Result:")
    print(f"   Saga ID: {result_success.get('saga_id')}")
    print(f"   Training Round: {result_success.get('training_round_id')}")
    print(f"   Model: {saga_success.model_name} v{saga_success.model_version}")
    print("   Status: Model trained, validated, and deployed to edge fleet")

    # Scenario 2: Insufficient node participation with rollback
    print("\n\n🔴 Scenario 2: Insufficient Node Participation")
    print("-" * 80)

    saga_failure = EdgeFederatedLearningSaga(
        training_round_id="FL-ROUND-043",
        model_name="user-behavior-predictor",
        model_version="3.2.0",
        target_accuracy=0.85,
        min_participating_nodes=10,
        training_rounds=5,
        simulate_failure=True,  # Simulate insufficient node completion
    )

    try:
        result_failure = await saga_failure.run({"training_round_id": saga_failure.training_round_id})
    except Exception:
        result_failure = {}

    print(f"\n{'❌' if not result_failure.get('saga_id') else '✅'} Rollback Result:")
    print(f"   Saga ID: {result_failure.get('saga_id', 'N/A')}")
    print(f"   Training Round: {saga_failure.training_round_id}")
    print("   Status: Failed - training stopped, model weights revoked")
    print("   Actions: Edge nodes released, previous model version remains active")

    print("\n" + "=" * 80)
    print("Key Features Demonstrated:")
    print("  ✅ Privacy-preserving ML (data stays on device)")
    print("  ✅ Partial participation handling (88% completion rate)")
    print("  ✅ Federated averaging (FedAvg) aggregation")
    print("  ✅ Differential privacy guarantees")
    print("  ✅ Model validation before deployment")
    print("  ✅ Bandwidth-efficient updates (8.5 MB compressed)")
    print("  ✅ Graceful rollback to previous model version")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
