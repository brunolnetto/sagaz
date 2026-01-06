# Examples

This directory contains self-contained saga examples demonstrating the **declarative pattern** using `@action` and `@compensate` decorators.

## 📁 Directory Structure

```
examples/
├── ecommerce/                 ← E-commerce & Retail
│   └── order_processing/      ← Order fulfillment workflow
│
├── fintech/                   ← Financial Services
│   ├── payment_processing/    ← Payment gateway integration
│   └── trade_execution/       ← Stock trading system
│
├── travel/                    ← Travel & Hospitality
│   └── booking/               ← Travel reservation workflow
│
├── healthcare/                ← Healthcare & Life Sciences
│   └── patient_onboarding/    ← HIPAA-compliant registration
│
├── iot/                       ← Internet of Things
│   ├── device_orchestration/  ← Smart home coordinator
│   └── smart_grid/            ← Energy demand response
│
├── logistics/                 ← Supply Chain
│   └── drone_delivery/        ← Autonomous delivery
│
├── ml/                        ← Machine Learning & AI
│   ├── training/              ← MLOps training pipeline
│   └── federated_learning/    ← Distributed edge training
│
├── monitoring/                ← Observability
│   ├── main.py                ← Metrics monitoring
│   └── mermaid_demo.py        ← Visualization generator
│
└── README.md                  ← This file
```

## 🚀 Quick Start

Each example is self-contained in its directory and can be run directly.

### Running Examples

```bash
# E-commerce
python examples/ecommerce/order_processing/main.py

# Fintech
python examples/fintech/payment_processing/main.py
python examples/fintech/trade_execution/main.py

# Travel
python examples/travel/booking/main.py

# Healthcare
python examples/healthcare/patient_onboarding/main.py

# IoT & Energy
python examples/iot/device_orchestration/main.py
python examples/iot/smart_grid/main.py

# Logistics
python examples/logistics/drone_delivery/main.py

# AI & MLOps
python examples/ml/training/main.py
python examples/ml/training/model_deployment.py
python examples/ml/federated_learning/main.py

# Monitoring & Visualization
python examples/monitoring/mermaid_demo.py
```

## 📚 Example Details

### 🛒 Order Processing
**Path:** `examples/ecommerce/order_processing/`  
**Use Case:** E-commerce order fulfillment  
**Steps:** Inventory → Payment → Shipment → Email  
**Best For:** Learning basic saga patterns

Example usage:
```python
from examples.ecommerce.order_processing.main import OrderProcessingSaga

# Create a reusable saga instance (stateless)
saga = OrderProcessingSaga()

# Pass order data through the run() method
result = await saga.run({
    "order_id": "ORD-123",
    "user_id": "USER-456",
    "items": [{"id": "ITEM-1", "quantity": 2}],
    "total_amount": 99.99
})
```

### 💳 Payment Processing
**Path:** `examples/fintech/payment_processing/`  
**Use Case:** Payment gateway integration  
**Steps:** Validation → Primary Payment → Transaction Recording  
**Best For:** Idempotency and retry patterns

Example usage:
```python
from examples.fintech.payment_processing.main import PaymentProcessingSaga

saga = PaymentProcessingSaga()

result = await saga.run({
    "payment_id": "PAY-101",
    "amount": 250.00,
    "providers": ["Stripe", "PayPal", "Square"]
})
```

### 📈 Trade Execution
**Path:** `examples/fintech/trade_execution/`  
**Use Case:** Financial trading system  
**Steps:** Reserve Funds → Execute Trade → Update Position  
**Best For:** Complex business logic with compensations

Example usage:
```python
from examples.fintech.trade_execution.main import TradeExecutionSaga

saga = TradeExecutionSaga()

result = await saga.run({
    "trade_id": 12345,
    "symbol": "AAPL",
    "quantity": 100,
    "price": 150.00,
    "user_id": 789
})
```

### ✈️ Travel Booking
**Path:** `examples/travel/booking/`  
**Use Case:** Multi-service travel reservation  
**Steps:** Flight → Hotel → Car → Itinerary  
**Best For:** Understanding service orchestration

Example usage:
```python
from examples.travel.booking.main import TravelBookingSaga

saga = TravelBookingSaga()

result = await saga.run({
    "booking_id": "BOOK-456",
    "user_id": "USER-789",
    "flight_details": {"flight_number": "AA123", "from": "NYC", "to": "LAX"},
    "hotel_details": {"hotel_name": "Grand Hotel", "nights": 3},
    "car_details": {"car_type": "Sedan", "days": 3}
})
```

### 🏥 Healthcare Patient Onboarding
**Path:** `examples/healthcare/patient_onboarding/`  
**Use Case:** HIPAA-compliant patient registration  
**Steps:** Verify Identity → Create EHR → Assign PCP → Portal Setup → Schedule → Welcome  
**Best For:** Compliance, audit trails, PHI protection

Example usage:
```python
from examples.healthcare.patient_onboarding.main import HealthcarePatientOnboardingSaga

saga = HealthcarePatientOnboardingSaga()

result = await saga.run({
    "patient_id": "PAT-2026-001",
    "first_name": "Alice",
    "last_name": "Johnson",
    "date_of_birth": "1985-06-15",
    "ssn_last_4": "1234",
    "email": "alice.johnson@email.com",
    "phone": "+1-555-0123"
})
```

### 📱 IoT Device Orchestration
**Path:** `examples/iot/device_orchestration/`  
**Use Case:** Smart home device coordination  
**Steps:** Lock Doors → Thermostat Away → Lights Off → Arm Security → Notify  
**Best For:** Multi-device coordination with safety rollback

Example usage:
```python
from examples.iot.device_orchestration.main import IoTDeviceOrchestrationSaga

saga = IoTDeviceOrchestrationSaga()

result = await saga.run({
    "routine_id": "ROUTINE-001",
    "home_id": "HOME-123",
    "user_id": "USER-456",
    "device_count": 100
})
```

### ⚡ Smart Grid Energy Management
**Path:** `examples/iot/smart_grid/`  
**Use Case:** Demand response for grid stabilization  
**Steps:** Forecast → Identify Participants → Send Requests → Monitor → Verify → Pay  
**Best For:** Distributed resource coordination, real-time monitoring

Example usage:
```python
from examples.iot.smart_grid.main import SmartGridEnergySaga

saga = SmartGridEnergySaga()

result = await saga.run({
    "event_id": "DR-2026-HEATWAVE-001",
    "grid_operator_id": "GRID-CAISO",
    "target_reduction_mw": 1.5,
    "event_duration_hours": 4,
    "incentive_rate_per_kwh": 0.15
})
```

### 🚁 Supply Chain Drone Delivery
**Path:** `examples/logistics/drone_delivery/`  
**Use Case:** Autonomous drone package delivery  
**Steps:** Reserve Drone → Plan Path → Get FAA Auth → Pickup → Deliver → Return  
**Best For:** Regulatory compliance, real-time coordination

Example usage:
```python
from examples.logistics.drone_delivery.main import SupplyChainDroneDeliverySaga

saga = SupplyChainDroneDeliverySaga()

result = await saga.run({
    "delivery_id": "DEL-2026-001",
    "package_id": "PKG-54321",
    "warehouse_id": "WH-SF-01",
    "destination_lat": 37.7899,
    "destination_lon": -122.3999,
    "package_weight_kg": 2.5,
    "priority": "standard"
})
```

### 🤖 ML Training Pipeline
**Path:** `examples/ml/training/`  
**Use Case:** End-to-end ML pipeline with automatic rollback  
**Steps:** Validation → Feature Engineering → Training → Evaluation → Deployment  
**Best For:** Understanding MLOps integration patterns

The `examples/ml/training/` directory contains three examples:
1. **`main.py`** - Complete training pipeline
2. **`model_deployment.py`** - Blue/green deployment
3. **`feature_store.py`** - Feature engineering pipeline

Example usage:
```python
from examples.ml.training.main import MLTrainingPipelineSaga

saga = MLTrainingPipelineSaga()

result = await saga.run({
    "experiment_id": "exp-001",
    "dataset_path": "/data/training/dataset.parquet",
    "model_name": "churn-predictor",
    "accuracy_threshold": 0.85,
    "hyperparameters": {"learning_rate": 0.001, "epochs": 15}
})
```

### 🤖 Edge Federated Learning
**Path:** `examples/ml/federated_learning/`  
**Use Case:** Privacy-preserving distributed ML training  
**Steps:** Select Nodes → Distribute Weights → Train → Aggregate → Validate → Deploy  
**Best For:** Privacy-preserving ML, partial participation handling

Example usage:
```python
from examples.ml.federated_learning.main import EdgeFederatedLearningSaga

saga = EdgeFederatedLearningSaga()

result = await saga.run({
    "training_round_id": "FL-ROUND-042",
    "model_name": "user-behavior-predictor",
    "model_version": "3.2.0",
    "target_accuracy": 0.85,
    "min_participating_nodes": 10,
    "training_rounds": 5
})
```

### 📊 Monitoring & Visualization
**Path:** `examples/monitoring/`  
**Use Case:** Saga metrics and visualization  

- **`mermaid_demo.py`**: Generates Mermaid diagrams via `saga.to_mermaid()`
- **`main.py`**: Monitoring orchestrator example

Run the visualization demo:
```bash
python examples/monitoring/mermaid_demo.py
```

---

## 🎯 Key Features Demonstrated

### Declarative Pattern
All examples use the modern **declarative approach** with decorators:

```python
from sagaz import Saga, SagaContext, action, compensate

class OrderProcessingSaga(Saga):
    """Stateless saga - all data passed through run() context."""
    
    saga_name = "order-processing"
    
    @action("reserve_inventory")
    async def reserve_inventory(self, ctx: SagaContext):
        # Get data from context
        order_id = ctx.get("order_id")
        items = ctx.get("items", [])
        
        # Forward action logic
        return {"reserved": True, "order_id": order_id}
    
    @compensate("reserve_inventory")
    async def release_inventory(self, ctx: SagaContext):
        # Compensation uses context data
        order_id = ctx.get("order_id")
        # Release logic here
    
    @action("process_payment", depends_on=["reserve_inventory"])
    async def process_payment(self, ctx: SagaContext):
        # Access data from previous steps and initial context
        total_amount = ctx.get("total_amount")
        return {"paid": True, "amount": total_amount}
```

### Stateless Sagas (Recommended)

**Best Practice:** Pass execution data through `run()`, not the constructor.

```python
# ✅ RECOMMENDED: Stateless saga, data via run()
saga = OrderProcessingSaga()
result1 = await saga.run({"order_id": "ORD-001", "amount": 99.99})
result2 = await saga.run({"order_id": "ORD-002", "amount": 149.99})  # Reuse!

# ❌ AVOID: Data in constructor (not reusable)
saga = OrderProcessingSaga(order_id="ORD-001", amount=99.99)  # Single use
```

**Benefits:**
- ✅ **Reusable** - Same saga instance processes multiple requests
- ✅ **Testable** - Easy to test with different inputs
- ✅ **Serializable** - Context can be stored/restored
- ✅ **Industry standard** - Aligns with Temporal, Step Functions, etc.

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

## 🔧 Customization

### Create Your Own Example

1. **Create a new file:**
```bash
mkdir -p examples/my_domain/my_saga
touch examples/my_domain/my_saga/main.py
```

2. **Implement your saga (stateless pattern):**
```python
"""My Custom Saga Example"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MySaga(Saga):
    """Stateless saga - all data passed through run() context."""
    
    saga_name = "my-saga"
    
    @action("step1")
    async def step1(self, ctx: SagaContext) -> dict[str, Any]:
        entity_id = ctx.get("id")
        logger.info(f"Executing step1 for {entity_id}")
        await asyncio.sleep(0.1)
        return {"step1": "done", "id": entity_id}
    
    @compensate("step1")
    async def undo_step1(self, ctx: SagaContext) -> None:
        entity_id = ctx.get("id")
        logger.warning(f"Compensating step1 for {entity_id}")
        await asyncio.sleep(0.1)


async def main():
    print("My Saga Demo")
    
    # Create reusable saga
    saga = MySaga()
    
    # Run with different data
    result = await saga.run({"id": "TEST-123", "value": 100})
    print(f"✅ Result: {result.get('saga_id')}")


if __name__ == "__main__":
    asyncio.run(main())
```

3. **Run your saga:**
```bash
python examples/my_domain/my_saga/main.py
```

## 💡 Best Practices

These examples demonstrate:
- ✅ **Stateless sagas** - Data passed through `run()`, not constructor
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
1. **Start:** `examples/ecommerce/order_processing/` - Simplest workflow (4 steps)
2. **Intermediate:** `examples/fintech/payment_processing/` - Provider fallback patterns
3. **Advanced:** `examples/travel/booking/` - Multi-service orchestration
4. **Expert:** `examples/fintech/trade_execution/` - Financial system with strict compensations

### Production Use Cases
5. **MLOps:** `examples/ml/training/` - Real-world ML pipeline patterns
6. **IoT:** `examples/iot/device_orchestration/` - Multi-device coordination (100+ devices)
7. **Healthcare:** `examples/healthcare/patient_onboarding/` - HIPAA compliance & audit trails
8. **Supply Chain:** `examples/logistics/drone_delivery/` - Regulatory compliance (FAA)
9. **Energy:** `examples/iot/smart_grid/` - Distributed resource management
10. **AI/ML:** `examples/ml/federated_learning/` - Privacy-preserving distributed training

Each example builds on the previous one, introducing new concepts progressively.

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
- [Configuration](../docs/guides/configuration.md) - Global configuration
- [Patterns](../docs/patterns/) - Implementation patterns

---

**Questions?** Check [main documentation](../README.md) or open an issue.
