# MLOps with Sagaz: Machine Learning Pipeline Orchestration

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This directory contains production-ready examples demonstrating how to use **Sagaz** for orchestrating machine learning pipelines with automatic rollback capabilities.

## 🎯 Overview

Modern MLOps workflows involve complex multi-step processes that can fail at any stage. Sagaz brings the **Saga Pattern** to machine learning, providing:

- **Automatic Rollback**: Failed steps trigger compensating transactions in reverse order
- **Resource Cleanup**: GPU resources, temporary artifacts, and cloud storage automatically cleaned up
- **Model Registry Consistency**: Transactional guarantees for model registration and versioning
- **Safe Deployments**: Blue/green deployments with automatic rollback on health check failures
- **Observability**: Full distributed tracing and structured logging for debugging

## 📊 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ML Training Pipeline Saga                        │
└─────────────────────────────────────────────────────────────────────┘
           │
           ├─► Validate Dataset ────────────► [Compensate: Cleanup Temp Files]
           │         │
           ├─► Engineer Features ───────────► [Compensate: Remove Feature Artifacts]
           │         │
           ├─► Train Model ─────────────────► [Compensate: Delete Model Files]
           │         │
           ├─► Evaluate Model ──────────────► [Compensate: Cleanup Test Data]
           │         │
           ├─► Register Model ──────────────► [Compensate: Deregister from Registry]
           │         │
           └─► Deploy Model ────────────────► [Compensate: Rollback to Previous Version]
           
           
           ❌ Any Step Fails → Automatic Compensation Chain
           ✅ All Steps Pass → Model Successfully Deployed
```

### Saga Flow Diagram

```
                    Success Path                    Failure Path
                    ────────────                    ────────────

    [Start] ─────► Validate ─────► Feature Eng ─────► Train
                      │                │                 │
                      │                │                 │ FAIL
                      │                │                 ↓
                      │                │           Compensate: Train
                      │                ↓
                      │           Compensate: Features
                      ↓
                 Compensate: Validate
                      ↓
                  [Rolled Back]
```

## 📁 Files in This Directory

### 1. `main.py` - ML Training Pipeline

**End-to-end training pipeline with automatic rollback**

**Pipeline Steps:**
1. **Dataset Validation** - Verify data quality, schema, and availability
2. **Feature Engineering** - Transform raw data into ML features
3. **Model Training** - Train model with hyperparameter tuning
4. **Model Evaluation** - Validate accuracy meets threshold
5. **Model Registration** - Register in MLflow/model registry
6. **Model Deployment** - Deploy to production infrastructure

**Key Features:**
- Accuracy threshold enforcement
- GPU resource cleanup on failure
- Artifact lifecycle management
- Training metrics tracking
- Hyperparameter logging

**Run:**
```bash
python examples/ml_training/main.py
```

**Output:**
```
✅ Training Pipeline Result:
   Saga ID:        abc-123
   Experiment ID:  exp-20240115-001
   Accuracy:       0.9414
   Model Version:  v40
   Endpoint URL:   https://api.ml-platform.com/models/churn-predictor/v40
```

---

### 2. `model_deployment.py` - Model Deployment Saga

**Production deployment with blue/green strategy**

**Deployment Flow:**
1. **Backup Current Model** - Snapshot production model
2. **Deploy to Staging** - Deploy and validate in staging environment
3. **Run Smoke Tests** - Execute critical test suite
4. **Blue/Green Deployment** - Gradual traffic shift with canary
5. **Monitor Health** - Track metrics and error rates

**Key Features:**
- Zero-downtime deployments
- Canary releases (gradual traffic shifting)
- Smoke test validation
- Automatic rollback on failures
- Production health monitoring

**Run:**
```bash
python examples/ml_training/model_deployment.py
```

**Output:**
```
✅ Deployment Result:
   Model Version:     v14 → v15
   Endpoint:          https://api.ml-platform.com/models/fraud-detector/v15
   Traffic:           {'green': 100, 'blue': 0}
   Health Status:     healthy
   Avg Error Rate:    0.93%
```

---

### 3. `feature_store.py` - Feature Engineering Pipeline

**Transactional feature store updates**

**Pipeline Flow:**
1. **Data Ingestion** - Extract from data lake (S3, BigQuery)
2. **Feature Computation** - Transform and compute features
3. **Feature Validation** - Schema checks and data quality
4. **Feature Store Publish** - Atomic publish to online/offline stores

**Key Features:**
- Transactional guarantees (all-or-nothing)
- Data quality validation
- Online/offline store consistency
- Feature lineage tracking
- Incremental updates support

**Run:**
```bash
python examples/ml_training/feature_store.py
```

**Output:**
```
✅ Feature Pipeline Result:
   Feature Group:         customer_features
   Version:               v2
   Records Ingested:      793,669
   Features Computed:     8
   Online Store Updated:  true
   Offline Store Updated: true
```

---

## 🎓 Key MLOps Concepts

### 1. Automatic Resource Cleanup

**Problem:** Failed training runs leave GPU resources allocated, temp files on disk, and cloud storage costs mounting.

**Sagaz Solution:**
```python
@action("train_model")
async def train_model(self, ctx: dict[str, Any]) -> dict[str, Any]:
    # Allocate GPU, create model artifacts
    model_dir = Path("/tmp/model_artifacts")
    # ... training logic
    return {"model_dir": str(model_dir)}

@compensate("train_model")
async def cleanup_model_artifacts(self, ctx: dict[str, Any]) -> None:
    # Automatic cleanup on ANY downstream failure
    model_dir = ctx.get("model_dir")
    if model_dir:
        shutil.rmtree(model_dir)  # Remove all artifacts
        # Release GPU resources
```

### 2. Model Registry Consistency

**Problem:** Failed deployments can leave stale model versions in registry, causing confusion.

**Sagaz Solution:**
```python
@action("register_model")
async def register_model(self, ctx: dict[str, Any]) -> dict[str, Any]:
    model_version = mlflow.register_model(model_uri, model_name)
    return {"model_version": model_version}

@compensate("register_model")
async def deregister_model(self, ctx: dict[str, Any]) -> None:
    # Automatic deregistration if deployment fails
    model_version = ctx.get("model_version")
    mlflow.delete_model_version(model_name, model_version)
```

### 3. Safe Deployments with Rollback

**Problem:** Deploying broken models to production causes incidents and downtime.

**Sagaz Solution:**
- Blue/green deployments
- Canary releases with gradual traffic shifting
- Automatic rollback on health check failures
- Previous version always available

### 4. Distributed Training Coordination

For multi-node training:

```python
@action("distributed_training", depends_on=["setup_cluster"])
async def distributed_training(self, ctx: dict[str, Any]) -> dict[str, Any]:
    # Coordinate multiple training nodes
    cluster_endpoints = ctx.get("cluster_endpoints")
    # ... distributed training
    return {"model_checkpoint": checkpoint_path}

@compensate("distributed_training")
async def teardown_cluster(self, ctx: dict[str, Any]) -> None:
    # Cleanup all training nodes
    cluster_endpoints = ctx.get("cluster_endpoints")
    for endpoint in cluster_endpoints:
        await terminate_worker(endpoint)
```

---

## 🚀 Use Cases

### 1. AutoML Pipelines

**Scenario:** Run multiple hyperparameter tuning experiments, track best model

```python
class AutoMLSaga(Saga):
    saga_name = "automl-pipeline"
    
    @action("hyperparameter_search")
    async def hyperparameter_search(self, ctx: dict[str, Any]):
        best_params = await optuna_search(search_space)
        return {"best_params": best_params}
    
    @action("train_with_best_params", depends_on=["hyperparameter_search"])
    async def train_with_best_params(self, ctx: dict[str, Any]):
        best_params = ctx.get("best_params")
        model = train(best_params)
        return {"model": model}
```

**Benefits:**
- Failed experiments don't affect other runs
- Resource cleanup per experiment
- Best model automatically registered

---

### 2. A/B Testing Deployments

**Scenario:** Deploy model variants for A/B testing with automatic rollback

```python
class ABTestDeploymentSaga(Saga):
    saga_name = "ab-test-deployment"
    
    @action("deploy_variant_a")
    async def deploy_variant_a(self, ctx: dict[str, Any]):
        endpoint_a = deploy_model(model_a, traffic=50)
        return {"endpoint_a": endpoint_a}
    
    @action("deploy_variant_b")
    async def deploy_variant_b(self, ctx: dict[str, Any]):
        endpoint_b = deploy_model(model_b, traffic=50)
        return {"endpoint_b": endpoint_b}
    
    @action("monitor_metrics", depends_on=["deploy_variant_a", "deploy_variant_b"])
    async def monitor_metrics(self, ctx: dict[str, Any]):
        # Monitor both variants
        if variant_a_metrics < threshold:
            raise SagaStepError("Variant A underperforming")
        return {"winning_variant": "A"}
```

**Benefits:**
- Both variants automatically rolled back if either fails
- Traffic automatically restored to previous version
- Metrics tracked for both variants

---

### 3. Model Monitoring & Drift Detection

**Scenario:** Continuous monitoring with automatic retraining on drift

```python
class DriftMonitoringSaga(Saga):
    saga_name = "drift-monitoring"
    
    @action("detect_drift")
    async def detect_drift(self, ctx: dict[str, Any]):
        drift_score = calculate_drift(production_data, training_data)
        if drift_score > threshold:
            raise SagaStepError("Drift detected - retraining required")
        return {"drift_score": drift_score}
    
    @action("trigger_retraining", depends_on=["detect_drift"])
    async def trigger_retraining(self, ctx: dict[str, Any]):
        # Automatically trigger retraining pipeline
        training_saga = MLTrainingPipelineSaga(...)
        result = await training_saga.run({})
        return result
```

**Benefits:**
- Drift detection integrated with retraining
- Failed retraining doesn't affect production model
- Automatic rollback if new model underperforms

---

### 4. Feature Store Updates

**Scenario:** Update feature definitions with transactional guarantees

```python
class FeatureUpdateSaga(Saga):
    saga_name = "feature-update"
    
    @action("compute_new_features")
    async def compute_new_features(self, ctx: dict[str, Any]):
        features = compute_features(raw_data)
        return {"features": features}
    
    @action("validate_features", depends_on=["compute_new_features"])
    async def validate_features(self, ctx: dict[str, Any]):
        features = ctx.get("features")
        if not validate(features):
            raise SagaStepError("Feature validation failed")
        return {"validated": True}
    
    @action("publish_to_feature_store", depends_on=["validate_features"])
    async def publish_to_feature_store(self, ctx: dict[str, Any]):
        features = ctx.get("features")
        feature_store.write(features)
        return {"published": True}
```

**Benefits:**
- All-or-nothing feature updates
- Validation prevents bad features
- Automatic cleanup of staging data

---

## 🔌 Integration Examples

### MLflow Integration

```python
import mlflow
from sagaz import Saga, action, compensate

class MLflowTrainingSaga(Saga):
    saga_name = "mlflow-training"
    
    @action("start_mlflow_run")
    async def start_mlflow_run(self, ctx: dict[str, Any]):
        run = mlflow.start_run()
        mlflow.log_params(self.hyperparameters)
        return {"mlflow_run_id": run.info.run_id}
    
    @action("train_and_log", depends_on=["start_mlflow_run"])
    async def train_and_log(self, ctx: dict[str, Any]):
        model = train_model()
        mlflow.log_metrics({"accuracy": model.accuracy})
        mlflow.sklearn.log_model(model, "model")
        return {"model": model}
    
    @compensate("start_mlflow_run")
    async def end_mlflow_run(self, ctx: dict[str, Any]):
        mlflow.end_run(status="FAILED")
```

---

### Kubeflow Pipelines Integration

```python
from kfp import dsl
from sagaz import Saga, action, compensate

class KubeflowSaga(Saga):
    saga_name = "kubeflow-pipeline"
    
    @action("create_pipeline_run")
    async def create_pipeline_run(self, ctx: dict[str, Any]):
        client = kfp.Client()
        run = client.create_run_from_pipeline_func(
            pipeline_func=training_pipeline,
            arguments=self.arguments
        )
        return {"run_id": run.id}
    
    @action("wait_for_completion", depends_on=["create_pipeline_run"])
    async def wait_for_completion(self, ctx: dict[str, Any]):
        run_id = ctx.get("run_id")
        status = await client.wait_for_run_completion(run_id)
        if status != "Succeeded":
            raise SagaStepError(f"Pipeline failed: {status}")
        return {"status": status}
```

---

### Weights & Biases Integration

```python
import wandb
from sagaz import Saga, action, compensate

class WandBTrainingSaga(Saga):
    saga_name = "wandb-training"
    
    @action("init_wandb")
    async def init_wandb(self, ctx: dict[str, Any]):
        run = wandb.init(project="my-project", config=self.config)
        return {"wandb_run_id": run.id}
    
    @action("train_with_logging", depends_on=["init_wandb"])
    async def train_with_logging(self, ctx: dict[str, Any]):
        for epoch in range(epochs):
            loss = train_epoch()
            wandb.log({"loss": loss, "epoch": epoch})
        return {"final_loss": loss}
    
    @compensate("init_wandb")
    async def finish_wandb(self, ctx: dict[str, Any]):
        wandb.finish(exit_code=1)
```

---

### Seldon Core Deployment Integration

```python
from seldon_core import SeldonClient
from sagaz import Saga, action, compensate

class SeldonDeploymentSaga(Saga):
    saga_name = "seldon-deployment"
    
    @action("create_seldon_deployment")
    async def create_seldon_deployment(self, ctx: dict[str, Any]):
        client = SeldonClient()
        deployment = client.create_deployment(
            name=self.model_name,
            model_uri=self.model_uri
        )
        return {"deployment_name": deployment.name}
    
    @compensate("create_seldon_deployment")
    async def delete_seldon_deployment(self, ctx: dict[str, Any]):
        deployment_name = ctx.get("deployment_name")
        client = SeldonClient()
        client.delete_deployment(deployment_name)
```

---

## 🐳 Kubernetes Deployment

### Deploy ML Pipeline on Kubernetes

**1. Create Kubernetes Job for Training:**

```yaml
# ml-training-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: ml-training-pipeline
spec:
  template:
    spec:
      containers:
      - name: training
        image: myorg/ml-training:latest
        command: ["python", "examples/ml_training/main.py"]
        env:
        - name: EXPERIMENT_ID
          value: "exp-k8s-001"
        - name: MODEL_NAME
          value: "churn-predictor"
        resources:
          limits:
            nvidia.com/gpu: 1
            memory: "16Gi"
            cpu: "4"
      restartPolicy: OnFailure
```

**2. Deploy with Model Serving:**

```yaml
# model-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: model-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: model-server
  template:
    metadata:
      labels:
        app: model-server
    spec:
      containers:
      - name: model-server
        image: myorg/model-server:latest
        env:
        - name: MODEL_NAME
          value: "churn-predictor"
        - name: MODEL_VERSION
          value: "v40"
        ports:
        - containerPort: 8080
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
```

**3. Apply Configurations:**

```bash
kubectl apply -f ml-training-job.yaml
kubectl apply -f model-deployment.yaml

# Monitor training job
kubectl logs -f job/ml-training-pipeline

# Check deployment status
kubectl rollout status deployment/model-server
```

---

## 📊 Monitoring & Observability

### Structured Logging

All sagas automatically emit structured logs:

```python
2025-12-30 21:37:37,003 - sagaz.listeners - INFO - [SAGA] Starting: ml-training-pipeline (id=abc-123)
2025-12-30 21:37:37,003 - sagaz.listeners - INFO - [STEP] Entering: ml-training-pipeline.validate_dataset
2025-12-30 21:37:37,204 - sagaz.listeners - INFO - [STEP] Success: ml-training-pipeline.validate_dataset
2025-12-30 21:37:38,307 - sagaz.listeners - INFO - [STEP] Success: ml-training-pipeline.evaluate_model
2025-12-30 21:37:39,010 - sagaz.listeners - INFO - [SAGA] Completed: ml-training-pipeline (id=abc-123)
```

### Distributed Tracing

Integrate with OpenTelemetry for distributed tracing:

```python
from sagaz import Saga, SagaConfig, configure
from sagaz.listeners import TracingSagaListener
from opentelemetry import trace

# Configure tracing
tracer = trace.get_tracer(__name__)
config = SagaConfig(
    listeners=[TracingSagaListener(tracer=tracer)]
)
configure(config)

# Your saga automatically gets distributed tracing
saga = MLTrainingPipelineSaga(...)
await saga.run({})
```

**Trace Output:**
```
Trace: ml-training-pipeline (duration: 2.1s)
  ├─ validate_dataset (200ms)
  ├─ engineer_features (300ms)
  ├─ train_model (500ms)
  ├─ evaluate_model (300ms)
  ├─ register_model (200ms)
  └─ deploy_model (400ms)
```

### Prometheus Metrics

Export saga metrics to Prometheus:

```python
from sagaz.listeners import MetricsSagaListener

config = SagaConfig(
    listeners=[MetricsSagaListener()]
)
configure(config)

# Metrics automatically exported:
# - saga_executions_total{saga_name="ml-training-pipeline", status="completed"}
# - saga_execution_duration_seconds{saga_name="ml-training-pipeline"}
# - saga_step_duration_seconds{saga_name="ml-training-pipeline", step="train_model"}
# - saga_compensation_total{saga_name="ml-training-pipeline"}
```

**Grafana Dashboard Queries:**
```promql
# Success rate
rate(saga_executions_total{status="completed"}[5m]) 
  / 
rate(saga_executions_total[5m])

# P95 execution time
histogram_quantile(0.95, saga_execution_duration_seconds)

# Compensation rate (rollback rate)
rate(saga_compensation_total[5m])
```

---

## 🎯 Best Practices

### 1. Idempotent Operations

Make actions safe to retry:

```python
@action("register_model")
async def register_model(self, ctx: dict[str, Any]):
    # Check if model already registered
    existing = mlflow.search_registered_models(f"name='{self.model_name}'")
    if existing:
        return {"model_version": existing[0].version}
    
    # Register only if not exists
    version = mlflow.register_model(...)
    return {"model_version": version}
```

### 2. Granular Compensation

Keep compensations simple and focused:

```python
# ❌ Bad: Complex compensation
@compensate("complex_step")
async def cleanup_complex(self, ctx):
    cleanup_model()
    cleanup_artifacts()
    cleanup_database()
    cleanup_storage()

# ✅ Good: Separate steps with individual compensations
@action("save_model")
async def save_model(self, ctx): ...

@compensate("save_model")
async def delete_model(self, ctx): ...

@action("save_artifacts")
async def save_artifacts(self, ctx): ...

@compensate("save_artifacts")
async def delete_artifacts(self, ctx): ...
```

### 3. Proper Error Handling

Use specific exceptions:

```python
from sagaz.exceptions import SagaStepError

@action("validate_accuracy")
async def validate_accuracy(self, ctx: dict[str, Any]):
    accuracy = ctx.get("accuracy")
    
    if accuracy < self.threshold:
        # This triggers automatic compensation
        raise SagaStepError(
            f"Model accuracy {accuracy:.4f} below threshold {self.threshold:.4f}"
        )
    
    return {"validation_passed": True}
```

### 4. Context Propagation

Pass data between steps via context:

```python
@action("train_model")
async def train_model(self, ctx: dict[str, Any]):
    dataset_size = ctx.get("dataset_size")  # From previous step
    features = ctx.get("features")  # From previous step
    
    model = train(features, dataset_size)
    
    return {
        "model_path": "/tmp/model.pkl",
        "accuracy": 0.95,
        "training_time": 120.5
    }

@action("deploy_model", depends_on=["train_model"])
async def deploy_model(self, ctx: dict[str, Any]):
    model_path = ctx.get("model_path")  # From train_model
    accuracy = ctx.get("accuracy")  # From train_model
    
    deploy(model_path, accuracy)
```

### 5. Timeout Configuration

Set appropriate timeouts per step:

```python
@action("train_model", timeout_seconds=3600.0)  # 1 hour for training
async def train_model(self, ctx: dict[str, Any]):
    # Long-running training
    model = train_for_hours()
    return {"model": model}

@action("deploy_model", timeout_seconds=300.0)  # 5 minutes for deployment
async def deploy_model(self, ctx: dict[str, Any]):
    # Faster deployment
    deploy(model)
```

---

## 🐛 Troubleshooting

### Import Errors

```bash
# Install Sagaz
pip install -e .

# Or install from PyPI (when published)
pip install sagaz
```

### Module Not Found

```bash
# Add to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/path/to/sagaz"

# Or install in development mode
cd /path/to/sagaz
pip install -e .
```

### Examples Don't Run

```bash
# Check Python version (requires 3.11+)
python --version

# Verify installation
python -c "from sagaz import Saga, action, compensate; print('✅ Sagaz installed')"

# Run with full traceback
python -u examples/ml_training/main.py
```

### GPU Not Available

If running on GPU-enabled machines:

```python
import torch

@action("train_model")
async def train_model(self, ctx: dict[str, Any]):
    if torch.cuda.is_available():
        device = "cuda"
        logger.info(f"Using GPU: {torch.cuda.get_device_name(0)}")
    else:
        device = "cpu"
        logger.warning("GPU not available, using CPU")
    
    model = train_on_device(device)
    return {"model": model, "device": device}
```

---

## 📚 Related Documentation

- [Main Sagaz README](../../../README.md) - Project overview
- [Configuration Guide](../../../docs/guides/configuration.md) - Configuration options
- [API Documentation](../../../docs/api/) - Complete API reference
- [Other Examples](../../README.md) - More saga examples

---

## 🤝 Contributing

Found a bug or have a feature request? Please open an issue on GitHub.

Want to contribute? Pull requests are welcome! See [CONTRIBUTING.md](../../../CONTRIBUTING.md) for guidelines.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](../../../LICENSE) file for details.

---

## 🙏 Acknowledgments

- Inspired by the Saga pattern from distributed systems literature
- Built with Python's async/await for high performance
- Designed for production MLOps workflows

---

**Questions?** Open an issue or check [main documentation](../../../README.md).
