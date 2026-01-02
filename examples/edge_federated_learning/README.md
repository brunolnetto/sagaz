# Edge Computing Federated Learning Saga

Distributed ML model training across edge devices with privacy-preserving federated learning, partial participation handling, model versioning, and automatic rollback.

## Overview

This example demonstrates a complete federated learning workflow that trains machine learning models across distributed edge devices without centralizing user data, maintaining privacy while improving model accuracy.

## Use Case

Train ML models across thousands of edge devices (mobile phones, IoT gateways) while:
1. Keeping user data on device (privacy-preserving)
2. Handling partial participation (some devices fail/drop out)
3. Aggregating model updates efficiently
4. Validating model quality before deployment
5. Rolling back on failures

## Workflow

```
Federated Learning Round Started
    ↓
[1] Select Edge Nodes → (Compensation: Release nodes to pool)
    ↓
[2] Distribute Model Weights → (Compensation: Revoke weights from devices)
    ↓
[3] Coordinate Local Training → (Compensation: Stop training processes)
    ↓
[4] Aggregate Model Updates (FedAvg) → (Compensation: Discard aggregated model)
    ↓
[5] Validate Global Model Accuracy → (Compensation: Log validation failure)
    ↓
[6] Deploy Updated Model to Fleet (idempotent)
    ↓
Training Round Complete
```

## Key Features

### Privacy-Preserving ML
- **Data Never Leaves Device**: All training on local data
- **Differential Privacy**: ε-differential privacy guarantees
- **Secure Aggregation**: Encrypted model updates
- **Federated Averaging**: Weighted average by dataset size

### Partial Participation Handling
- **Graceful Degradation**: Works with 50%+ node participation
- **Failure Reasons Tracked**: Battery, network, device suspended
- **Automatic Retry**: Failed nodes can rejoin next round
- **Quality Thresholds**: Minimum nodes required for valid round

### Model Versioning & Rollback
- **Semantic Versioning**: Track all model versions
- **Validation Before Deployment**: Accuracy thresholds
- **Automatic Rollback**: Revert to previous version on failure
- **Canary Deployment**: Gradual rollout (10% → 50% → 100%)

### Bandwidth Efficiency
- **Model Compression**: Quantization + pruning (85% reduction)
- **P2P Distribution**: Peer-to-peer with CDN fallback
- **Delta Updates Only**: Send weight changes, not full model
- **Adaptive Batch Sizes**: Based on device resources

## Files

- **main.py** - Complete saga implementation with demo scenarios

## Usage

```python
from examples.edge_federated_learning.main import EdgeFederatedLearningSaga

# Create federated learning round
saga = EdgeFederatedLearningSaga(
    training_round_id="FL-ROUND-042",
    model_name="user-behavior-predictor",
    model_version="3.2.0",
    target_accuracy=0.85,
    min_participating_nodes=10,
    training_rounds=5,
    simulate_failure=False
)

# Execute training round
result = await saga.run({"training_round_id": saga.training_round_id})
```

## Running the Example

```bash
python examples/edge_federated_learning/main.py
```

Expected output shows:
1. **Scenario 1**: Successful federated learning with deployment
2. **Scenario 2**: Insufficient participation with rollback

## Actions

### select_edge_nodes(ctx)
Selects available edge devices for training based on resources.

**Returns:**
```python
{
    "nodes": [
        {
            "node_id": "EDGE-1",
            "location": "Region-1",
            "device_type": "mobile",
            "cpu_cores": 4,
            "available_memory_mb": 2048,
            "battery_level": 86,
            "network_quality": "4G",
            "local_dataset_size": 1100,
            "status": "available"
        },
        # ... 24 more nodes
    ],
    "total_nodes": 25,
    "total_dataset_size": 32500
}
```

### distribute_model_weights(ctx)
Distributes compressed global model to all edge nodes.

**Returns:**
```python
{
    "model_name": "user-behavior-predictor",
    "model_version": "3.2.0",
    "model_size_mb": 45.2,
    "compression_used": "quantization + pruning",
    "compressed_size_mb": 8.5,
    "nodes_received": 25,
    "distribution_method": "P2P + CDN fallback",
    "average_download_time_sec": 12.3,
    "failed_downloads": 0
}
```

### coordinate_local_training(ctx)
Coordinates local training rounds on edge devices.

**Returns:**
```python
{
    "training_round_id": "FL-ROUND-042",
    "total_rounds": 5,
    "participating_nodes": 25,
    "completed_nodes": 22,  # 88% completion
    "failed_nodes": 3,
    "reasons_for_failure": {
        "battery_died": 1,
        "network_timeout": 1,
        "device_suspended": 1
    },
    "average_training_time_sec": 245,
    "local_epochs_per_node": 3,
    "batch_size": 32
}
```

### aggregate_model_updates(ctx)
Aggregates updates using Federated Averaging (FedAvg).

**Returns:**
```python
{
    "training_round_id": "FL-ROUND-042",
    "aggregation_method": "FedAvg (Weighted Average)",
    "updates_aggregated": 22,
    "aggregation_weights": "proportional to dataset size",
    "new_model_version": "3.2.0-FL042",
    "compression_ratio": 0.15,
    "privacy_guarantee": "differential privacy (ε=1.0)",
    "aggregation_time_sec": 18.5
}
```

### validate_global_model(ctx)
Validates aggregated model on holdout dataset.

**Returns:**
```python
{
    "model_version": "3.2.0-FL042",
    "validation_dataset_size": 10000,
    "accuracy": 0.89,
    "precision": 0.87,
    "recall": 0.86,
    "f1_score": 0.865,
    "target_accuracy": 0.85,
    "accuracy_achieved": True,
    "previous_accuracy": 0.82,
    "improvement": 0.07
}
```

### deploy_updated_model(ctx)
Deploys validated model to edge fleet (idempotent).

**Returns:**
```python
{
    "model_version": "3.2.0-FL042",
    "deployment_strategy": "canary (10% → 50% → 100%)",
    "total_edge_devices": 1000,
    "devices_updated": 1000,
    "rollout_duration_min": 45,
    "validation_passed": True,
    "production_metrics": {
        "inference_latency_ms": 8.5,
        "memory_usage_mb": 45,
        "battery_impact_percent": 2.1
    }
}
```

## Compensations

### release_edge_nodes(ctx)
Returns edge nodes to available pool immediately.

### revoke_model_weights(ctx)
Deletes model weights from edge devices (privacy/security).

### stop_local_training(ctx)
Terminates ongoing training processes on edge nodes.

### discard_aggregated_model(ctx)
Discards aggregated model, keeps previous version active.

### log_validation_failure(ctx)
Logs validation failure with metrics for debugging.

## Error Scenarios

### Insufficient Node Participation
If < 50% nodes complete training:
- Training stopped on remaining nodes
- Model weights revoked from all devices
- Nodes released for next round
- Previous model version remains

### Model Validation Failure
If accuracy < target threshold:
- Aggregated model discarded
- Previous version remains deployed
- Hyperparameters adjusted for next round

### Network Partitions
If edge nodes lose connectivity:
- Partial updates used if > threshold
- Failed nodes auto-retry next round
- Regional clustering for resilience

### Battery Constraints
If devices run low on battery:
- Training paused automatically
- Resume when charging
- Priority given to plugged-in devices

## Real-World Integration

### TensorFlow Federated (TFF)
```python
import tensorflow_federated as tff

@tff.federated_computation
def federated_train(server_state, federated_data):
    # Define federated training logic
    return tff.federated_mean(
        tff.federated_map(local_train, federated_data)
    )

async def coordinate_tff_training(edge_nodes: list):
    # Coordinate TFF training across edge nodes
    server_state = initialize_server_state()
    for round in range(num_rounds):
        federated_data = collect_edge_data(edge_nodes)
        server_state = federated_train(server_state, federated_data)
    return server_state
```

### PySyft for Privacy
```python
import syft as sy

async def train_with_privacy(edge_nodes: list):
    hook = sy.TorchHook(torch)
    
    # Create virtual workers for edge nodes
    workers = {node['id']: sy.VirtualWorker(hook, id=node['id']) 
               for node in edge_nodes}
    
    # Distribute data (stays on device)
    distributed_data = distribute_to_workers(data, workers)
    
    # Train with differential privacy
    model = train_with_differential_privacy(
        distributed_data, 
        epsilon=1.0,
        delta=1e-5
    )
    return model
```

### MQTT for Edge Communication
```python
import aiomqtt

async def distribute_model_via_mqtt(nodes: list, model_weights: bytes):
    async with aiomqtt.Client("edge-cluster.local") as client:
        for node in nodes:
            await client.publish(
                f"federated-learning/{node['id']}/model",
                payload=model_weights,
                qos=1
            )
```

## Testing

```bash
# Run with default settings
python examples/edge_federated_learning/main.py

# Test with different parameters
python -c "
import asyncio
from examples.edge_federated_learning.main import EdgeFederatedLearningSaga

async def test():
    saga = EdgeFederatedLearningSaga(
        training_round_id='FL-TEST-001',
        model_name='image-classifier',
        model_version='1.0.0',
        target_accuracy=0.92,  # Higher target
        min_participating_nodes=50,
        training_rounds=10,
        simulate_failure=False
    )
    result = await saga.run({'training_round_id': saga.training_round_id})
    print(f'Result: {result}')

asyncio.run(test())
"
```

## Related Examples

- **Smart Grid Energy** - Distributed resource coordination
- **Supply Chain Drone Delivery** - Fleet management
- **ML Training** - Centralized training patterns

## Best Practices

1. **Always validate before deployment** - Never deploy untested models
2. **Use differential privacy** - Protect individual user data
3. **Handle partial participation** - Design for 50-80% completion rates
4. **Compress model updates** - Minimize bandwidth usage
5. **Monitor device health** - Battery, memory, network
6. **Implement gradual rollout** - Canary deployments catch issues early
7. **Version all models** - Enable rollback on production issues

## Privacy Considerations

### Differential Privacy Parameters
- **ε (epsilon)**: Privacy budget (lower = more private, less accurate)
- **δ (delta)**: Probability of privacy breach (typically 1e-5)
- **Typical values**: ε=1.0, δ=1e-5 for good privacy/utility tradeoff

### Data Protection
- User data never transmitted off device
- Only model weight updates sent to aggregator
- Secure aggregation prevents individual update inspection
- Regular security audits of federated system

### Regulatory Compliance
- **GDPR**: Right to erasure (delete local model)
- **CCPA**: Data minimization (only necessary data)
- **HIPAA**: For healthcare applications, additional safeguards

## Performance Metrics

- **Communication Efficiency**: < 10 MB per device per round
- **Training Time**: 2-5 minutes per round on mobile devices
- **Battery Impact**: < 3% battery per training round
- **Model Accuracy**: Within 2% of centralized training
- **Convergence**: 20-50 rounds typical for convergence

## Use Cases

### Mobile Keyboard Prediction
- Gboard (Google), SwiftKey use federated learning
- Learn from user typing patterns
- Privacy-preserving personalization

### Healthcare Diagnostics
- Train disease detection models across hospitals
- Keep patient data in-house (HIPAA compliance)
- Improve models without data sharing

### Smart Home Automation
- Learn user preferences across devices
- Personalized without cloud sync
- Local processing, fast response

### Financial Fraud Detection
- Train across banks without sharing transactions
- Detect novel fraud patterns
- Regulatory compliance maintained

---

**Questions?** Check the [main documentation](../../README.md) or open an issue.

**Academic References**:
- McMahan et al. (2017): "Communication-Efficient Learning of Deep Networks from Decentralized Data"
- Bonawitz et al. (2019): "Towards Federated Learning at Scale: System Design"
- Kairouz et al. (2021): "Advances and Open Problems in Federated Learning"
