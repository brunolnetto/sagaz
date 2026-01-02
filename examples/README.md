# Examples

This directory contains self-contained saga examples demonstrating the **declarative pattern** using `@action` and `@compensate` decorators.

## 📁 Directory Structure

```
examples/
├── order_processing/          ← E-commerce order workflow
│   ├── README.md             Complete documentation
│   └── main.py               Saga implementation with entrypoint
│
├── travel_booking/            ← Travel reservation workflow
│   ├── README.md
│   └── main.py               Saga implementation with entrypoint
│
├── trade_execution/           ← Financial trading workflow
│   ├── README.md
│   └── main.py               Saga implementation with entrypoint
│
├── payment_processing/        ← Payment processing workflow
│   ├── README.md
│   └── main.py               Saga implementation with entrypoint
│
├── ml_training/               ← MLOps machine learning workflows
│   ├── README.md             Comprehensive MLOps guide (300+ lines)
│   ├── main.py               ML training pipeline with rollback
│   ├── model_deployment.py   Blue/green deployment saga
│   └── feature_store.py      Feature engineering pipeline
│
├── iot_device_orchestration/  ← Smart home IoT orchestration
│   ├── README.md
│   └── main.py               Multi-device coordination saga
│
├── healthcare_patient_onboarding/ ← HIPAA-compliant healthcare
│   ├── README.md
│   └── main.py               Patient registration workflow
│
├── supply_chain_drone_delivery/ ← Autonomous drone delivery
│   ├── README.md
│   └── main.py               FAA-compliant delivery orchestration
│
├── smart_grid_energy/         ← Demand response for energy grids
│   ├── README.md
│   └── main.py               Grid stabilization workflow
│
├── edge_federated_learning/   ← Federated ML on edge devices
│   ├── README.md
│   └── main.py               Privacy-preserving distributed training
│
└── README.md                  ← This file
```

## 🚀 Quick Start

Each example is self-contained in a single `main.py` file and can be run directly.

### Running Examples

```bash
# E-commerce & Business
python examples/order_processing/main.py
python examples/payment_processing/main.py
python examples/travel_booking/main.py
python examples/trade_execution/main.py

# MLOps & AI
python examples/ml_training/main.py
python examples/ml_training/model_deployment.py
python examples/ml_training/feature_store.py
python examples/edge_federated_learning/main.py

# Emerging Technologies
python examples/iot_device_orchestration/main.py
python examples/healthcare_patient_onboarding/main.py
python examples/supply_chain_drone_delivery/main.py
python examples/smart_grid_energy/main.py
```

## 📚 Example Details

### 🛒 Order Processing
**Directory:** `order_processing/`  
**Use Case:** E-commerce order fulfillment  
**Steps:** Inventory → Payment → Shipment → Email  
**Best For:** Learning basic saga patterns

Example usage:
```python
from examples.order_processing.main import OrderProcessingSaga

saga = OrderProcessingSaga(
    order_id="ORD-123",
    user_id="USER-456",
    items=[{"id": "ITEM-1", "quantity": 2}],
    total_amount=99.99
)

result = await saga.run({"order_id": saga.order_id})
```

### 💳 Payment Processing
**Directory:** `payment_processing/`  
**Use Case:** Payment gateway integration  
**Steps:** Validation → Primary Payment → Transaction Recording  
**Best For:** Idempotency and retry patterns

Example usage:
```python
from examples.payment_processing.main import PaymentProcessingSaga

saga = PaymentProcessingSaga(
    payment_id="PAY-101",
    amount=250.00,
    providers=["Stripe", "PayPal", "Square"]
)

result = await saga.run({"payment_id": saga.payment_id})
```

### ✈️ Travel Booking
**Directory:** `travel_booking/`  
**Use Case:** Multi-service travel reservation  
**Steps:** Flight → Hotel → Car → Itinerary  
**Best For:** Understanding service orchestration

Example usage:
```python
from examples.travel_booking.main import TravelBookingSaga

saga = TravelBookingSaga(
    booking_id="BOOK-456",
    user_id="USER-789",
    flight_details={"flight_number": "AA123", "from": "NYC", "to": "LAX"},
    hotel_details={"hotel_name": "Grand Hotel", "nights": 3},
    car_details={"car_type": "Sedan", "days": 3}
)

result = await saga.run({"booking_id": saga.booking_id})
```

### 📈 Trade Execution
**Directory:** `trade_execution/`  
**Use Case:** Financial trading system  
**Steps:** Reserve Funds → Execute Trade → Update Position  
**Best For:** Complex business logic with compensations

Example usage:
```python
from examples.trade_execution.main import TradeExecutionSaga

saga = TradeExecutionSaga(
    trade_id=12345,
    symbol="AAPL",
    quantity=100,
    price=150.00,
    user_id=789
)

result = await saga.run({"trade_id": saga.trade_id})
```

### 🤖 ML Training Pipeline
**Directory:** `ml_training/`  
**Use Case:** End-to-end ML pipeline with automatic rollback  
**Steps:** Validation → Feature Engineering → Training → Evaluation → Deployment  
**Best For:** Understanding MLOps integration patterns

The `ml_training/` directory contains three comprehensive examples:

1. **`main.py`** - Complete ML training pipeline
   - Dataset validation
   - Feature engineering
   - Model training with hyperparameters
   - Model evaluation with accuracy threshold
   - Model registration in registry
   - Production deployment

2. **`model_deployment.py`** - Blue/green deployment
   - Backup current model
   - Deploy to staging
   - Run smoke tests
   - Gradual traffic shifting (canary)
   - Production health monitoring

3. **`feature_store.py`** - Feature engineering pipeline
   - Data ingestion from data lake
   - Feature computation
   - Data quality validation
   - Transactional feature store publish

Example usage:
```python
from examples.ml_training.main import MLTrainingPipelineSaga

saga = MLTrainingPipelineSaga(
    experiment_id="exp-001",
    dataset_path="/data/training/dataset.parquet",
    model_name="churn-predictor",
    accuracy_threshold=0.85,
    hyperparameters={"learning_rate": 0.001, "epochs": 15}
)

result = await saga.run({"experiment_id": saga.experiment_id})
```

**Key Features:**
- ✅ Automatic resource cleanup (GPU, temp files)
- ✅ Model registry consistency
- ✅ Safe deployments with rollback
- ✅ Feature store transactional guarantees
- ✅ Distributed tracing for ML pipelines

See [ml_training/README.md](ml_training/README.md) for comprehensive MLOps guide (300+ lines).

### 📱 IoT Device Orchestration
**Directory:** `iot_device_orchestration/`  
**Use Case:** Smart home device coordination  
**Steps:** Lock Doors → Thermostat Away → Lights Off → Arm Security → Notify  
**Best For:** Multi-device coordination with safety rollback

Example usage:
```python
from examples.iot_device_orchestration.main import IoTDeviceOrchestrationSaga

saga = IoTDeviceOrchestrationSaga(
    routine_id="ROUTINE-001",
    home_id="HOME-123",
    user_id="USER-456",
    device_count=100,
    simulate_failure=False
)

result = await saga.run({"routine_id": saga.routine_id})
```

### 🏥 Healthcare Patient Onboarding
**Directory:** `healthcare_patient_onboarding/`  
**Use Case:** HIPAA-compliant patient registration  
**Steps:** Verify Identity → Create EHR → Assign PCP → Portal Setup → Schedule → Welcome  
**Best For:** Compliance, audit trails, PHI protection

Example usage:
```python
from examples.healthcare_patient_onboarding.main import HealthcarePatientOnboardingSaga

saga = HealthcarePatientOnboardingSaga(
    patient_id="PAT-2026-001",
    first_name="Alice",
    last_name="Johnson",
    date_of_birth="1985-06-15",
    ssn_last_4="1234",
    email="alice.johnson@email.com",
    phone="+1-555-0123",
    simulate_failure=False
)

result = await saga.run({"patient_id": saga.patient_id})
```

### 🚁 Supply Chain Drone Delivery
**Directory:** `supply_chain_drone_delivery/`  
**Use Case:** Autonomous drone package delivery  
**Steps:** Reserve Drone → Plan Path → Get FAA Auth → Pickup → Deliver → Return  
**Best For:** Regulatory compliance, real-time coordination

Example usage:
```python
from examples.supply_chain_drone_delivery.main import SupplyChainDroneDeliverySaga

saga = SupplyChainDroneDeliverySaga(
    delivery_id="DEL-2026-001",
    package_id="PKG-54321",
    warehouse_id="WH-SF-01",
    destination_lat=37.7899,
    destination_lon=-122.3999,
    package_weight_kg=2.5,
    priority="standard",
    simulate_failure=False
)

result = await saga.run({"delivery_id": saga.delivery_id})
```

### ⚡ Smart Grid Energy Management
**Directory:** `smart_grid_energy/`  
**Use Case:** Demand response for grid stabilization  
**Steps:** Forecast → Identify Participants → Send Requests → Monitor → Verify → Pay  
**Best For:** Distributed resource coordination, real-time monitoring

Example usage:
```python
from examples.smart_grid_energy.main import SmartGridEnergySaga

saga = SmartGridEnergySaga(
    event_id="DR-2026-HEATWAVE-001",
    grid_operator_id="GRID-CAISO",
    target_reduction_mw=1.5,
    event_duration_hours=4,
    incentive_rate_per_kwh=0.15,
    simulate_failure=False
)

result = await saga.run({"event_id": saga.event_id})
```

### 🤖 Edge Federated Learning
**Directory:** `edge_federated_learning/`  
**Use Case:** Privacy-preserving distributed ML training  
**Steps:** Select Nodes → Distribute Weights → Train → Aggregate → Validate → Deploy  
**Best For:** Privacy-preserving ML, partial participation handling

Example usage:
```python
from examples.edge_federated_learning.main import EdgeFederatedLearningSaga

saga = EdgeFederatedLearningSaga(
    training_round_id="FL-ROUND-042",
    model_name="user-behavior-predictor",
    model_version="3.2.0",
    target_accuracy=0.85,
    min_participating_nodes=10,
    training_rounds=5,
    simulate_failure=False
)

result = await saga.run({"training_round_id": saga.training_round_id})
```

---

## 🎯 Key Features Demonstrated

### Declarative Pattern
All examples use the modern **declarative approach** with decorators:

```python
from sagaz import Saga, action, compensate

class OrderProcessingSaga(Saga):
    saga_name = "order-processing"
    
    @action("reserve_inventory")
    async def reserve_inventory(self, ctx):
        # Forward action logic
        return {"reserved": True}
    
    @compensate("reserve_inventory")
    async def release_inventory(self, ctx):
        # Compensation logic
        pass
    
    @action("process_payment", depends_on=["reserve_inventory"])
    async def process_payment(self, ctx):
        # This runs after reserve_inventory
        return {"paid": True}
```

### Dependencies
Use `depends_on` to create execution order:

```python
@action("step1")
async def step1(self, ctx): pass

@action("step2", depends_on=["step1"])
async def step2(self, ctx): pass

@action("step3", depends_on=["step2"])
async def step3(self, ctx): pass
```

### Automatic Compensation
On failure, compensations run in **reverse order**:
1. Execute: step1 → step2 → step3 (fails)
2. Compensate: step2 → step1

### Error Handling
```python
from sagaz.exceptions import SagaStepError

@action("validate")
async def validate(self, ctx):
    if not valid:
        raise SagaStepError("Validation failed")
```

## 📊 Monitoring

All sagas automatically include:
- ✅ **Structured logging** with step progression
- ✅ **Automatic listeners** (LoggingSagaListener by default)
- ✅ **Saga execution tracking** with unique IDs
- ✅ **Success/failure notifications**

Example output:
```
[SAGA] Starting: order-processing (id=abc-123)
[STEP] Entering: order-processing.reserve_inventory
[STEP] Success: order-processing.reserve_inventory
[STEP] Entering: order-processing.process_payment
[STEP] Success: order-processing.process_payment
[SAGA] Completed: order-processing (id=abc-123)
```

## 🧪 Testing Examples

Run the examples directly:

```bash
# Test order processing
python examples/order_processing/main.py

# Test payment processing
python examples/payment_processing/main.py

# Test travel booking
python examples/travel_booking/main.py

# Test trade execution
python examples/trade_execution/main.py
```

## 🔧 Customization

### Create Your Own Example

1. **Create a new file:**
```bash
mkdir -p examples/my_saga
touch examples/my_saga/main.py
```

2. **Implement your saga:**
```python
"""My Custom Saga Example"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, action, compensate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MySaga(Saga):
    saga_name = "my-saga"
    
    def __init__(self, id: str):
        super().__init__()
        self.id = id
    
    @action("step1")
    async def step1(self, ctx: dict[str, Any]) -> dict[str, Any]:
        logger.info(f"Executing step1 for {self.id}")
        await asyncio.sleep(0.1)
        return {"step1": "done"}
    
    @compensate("step1")
    async def undo_step1(self, ctx: dict[str, Any]) -> None:
        logger.warning(f"Compensating step1 for {self.id}")
        await asyncio.sleep(0.1)


async def main():
    print("My Saga Demo")
    saga = MySaga(id="TEST-123")
    result = await saga.run({"id": saga.id})
    print(f"✅ Result: {result.get('saga_id')}")


if __name__ == "__main__":
    asyncio.run(main())
```

3. **Run your saga:**
```bash
python examples/my_saga/main.py
```

## 💡 Best Practices

These examples demonstrate:
- ✅ **Single file per saga** - Each example in one `main.py` file
- ✅ **Declarative pattern** - Using `@action` and `@compensate` decorators
- ✅ **Proper entrypoints** - All examples have `if __name__ == "__main__":`
- ✅ **Clear documentation** - Docstrings for every class and method
- ✅ **Error handling** - Proper exception handling with `SagaStepError`
- ✅ **Idempotency** - Safe to retry operations
- ✅ **Type hints** - Full type annotations for better IDE support
- ✅ **Real-world patterns** - Based on actual production use cases

## 📚 Learning Path

### Basic Patterns
1. **Start:** `order_processing/` - Simplest workflow (4 steps)
2. **Intermediate:** `payment_processing/` - Provider fallback patterns
3. **Advanced:** `travel_booking/` - Multi-service orchestration
4. **Expert:** `trade_execution/` - Financial system with strict compensations

### Production Use Cases
5. **MLOps:** `ml_training/` - Real-world ML pipeline patterns
6. **IoT:** `iot_device_orchestration/` - Multi-device coordination (100+ devices)
7. **Healthcare:** `healthcare_patient_onboarding/` - HIPAA compliance & audit trails
8. **Supply Chain:** `supply_chain_drone_delivery/` - Regulatory compliance (FAA)
9. **Energy:** `smart_grid_energy/` - Distributed resource management
10. **AI/ML:** `edge_federated_learning/` - Privacy-preserving distributed training

Each example builds on the previous one, introducing new concepts progressively.

### By Industry

**E-commerce/Retail**
- `order_processing/` - Order fulfillment
- `payment_processing/` - Payment gateway integration

**Travel & Hospitality**
- `travel_booking/` - Multi-service booking

**Finance**
- `trade_execution/` - Trading systems

**Technology & AI**
- `ml_training/` - MLOps pipelines
- `edge_federated_learning/` - Distributed ML

**Healthcare**
- `healthcare_patient_onboarding/` - Patient registration

**IoT & Smart Home**
- `iot_device_orchestration/` - Device automation

**Logistics & Supply Chain**
- `supply_chain_drone_delivery/` - Autonomous delivery

**Energy & Utilities**
- `smart_grid_energy/` - Grid management

## 🐛 Troubleshooting

### Import Errors
```bash
# Install the package in development mode
pip install -e .
```

### Module Not Found
```bash
# Add project to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/path/to/sagaz"
```

### Example Doesn't Run
```bash
# Check Python version (requires 3.11+)
python --version

# Reinstall dependencies
pip install -r requirements.txt
```

## 📖 Related Documentation

- [Main README](../README.md) - Project overview
- [Saga Class](../sagaz/decorators.py) - Declarative API implementation
- [Action/Compensate Decorators](../sagaz/decorators.py) - Decorator details
- [Configuration](../docs/configuration.md) - Global configuration
- [Monitoring](../docs/monitoring.md) - Observability integration

---

**Questions?** Check [main documentation](../README.md) or open an issue.
