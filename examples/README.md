# Examples

This directory contains self-contained saga examples. Each example is in its own folder with actions, compensations, and documentation.

## 📁 Directory Structure

```
examples/
├── order_processing/          ← E-commerce order workflow
│   ├── README.md             Complete documentation
│   ├── main.py               Saga orchestration
│   ├── actions.py            Forward steps
│   └── compensations.py      Rollback steps
│
├── travel_booking/            ← Travel reservation workflow
│   ├── README.md
│   ├── main.py
│   ├── actions.py
│   └── compensations.py
│
├── trade_execution/           ← Financial trading workflow
│   ├── README.md
│   ├── main.py
│   ├── actions.py
│   └── compensations.py
│
├── payment_processing/        ← Payment processing workflow
│   ├── README.md
│   ├── main.py
│   ├── actions.py
│   └── compensations.py
│
└── monitoring.py              ← Observability integration
```

## 🚀 Quick Start

Each example is self-contained in its own directory.

### 1. Order Processing (E-commerce)

```python
from examples.order_processing import OrderProcessingSaga

saga = OrderProcessingSaga(
    order_id="ORD-123",
    user_id="USER-456",
    items=[{"sku": "ITEM-1", "quantity": 2}],
    total_amount=99.99
)

result = await saga.execute()
```

See [order_processing/README.md](order_processing/README.md) for details.

### 2. Travel Booking (Multi-service)

```python
from examples.travel_booking import TravelBookingSaga

saga = TravelBookingSaga(
    trip_id="TRIP-456",
    user_id="USER-789",
    flight="AA123",
    hotel="HTL-789",
    car_rental=True
)

result = await saga.execute()
```

See [travel_booking/README.md](travel_booking/README.md) for details.

### 3. Trade Execution (Financial)

```python
from examples.trade_execution import TradeExecutionSaga

saga = TradeExecutionSaga(
    trade_id="TRD-789",
    account_id="ACC-123",
    symbol="AAPL",
    quantity=100,
    price=150.00
)

result = await saga.execute()
```

See [trade_execution/README.md](trade_execution/README.md) for details.

### 4. Payment Processing

```python
from examples.payment_processing import PaymentSaga

saga = PaymentSaga(
    payment_id="PAY-101",
    user_id="USER-456",
    amount=250.00,
    currency="USD"
)

result = await saga.execute()
```

See [payment_processing/README.md](payment_processing/README.md) for details.

## 📚 Example Details

### 🛒 Order Processing
**Directory:** `order_processing/`  
**Use Case:** E-commerce order fulfillment  
**Steps:** Inventory → Payment → Shipment → Email  
**Best For:** Learning basic saga patterns

### ✈️ Travel Booking
**Directory:** `travel_booking/`  
**Use Case:** Multi-service travel reservation  
**Steps:** Flight → Hotel → Car → Itinerary  
**Best For:** Understanding service orchestration

### 📈 Trade Execution
**Directory:** `trade_execution/`  
**Use Case:** Financial trading system  
**Steps:** Validation → Risk Check → Execution → Settlement  
**Best For:** Complex business logic with conditional steps

### 💳 Payment Processing
**Directory:** `payment_processing/`  
**Use Case:** Payment gateway integration  
**Steps:** Fraud Check → Authorization → Capture → Reconciliation  
**Best For:** Idempotency and retry patterns

## 🏃 Running Examples

### Option 1: Import and Use
```python
from examples.order_processing import OrderProcessingSaga

saga = OrderProcessingSaga(
    order_id="ORD-123",
    user_id="USER-456",
    items=[{"sku": "ITEM-1", "quantity": 2}],
    total_amount=99.99
)
result = await saga.execute()
```

### Option 2: Run Directly
```bash
cd examples/order_processing
python main.py
```

### Option 3: Use as Template
```bash
cp -r examples/order_processing my_saga
cd my_saga
# Edit main.py, actions.py, compensations.py
```

## 📊 Monitoring

The `monitoring.py` file shows observability integration:

```python
from examples.monitoring import setup_monitoring

# Setup metrics, tracing, logging
setup_monitoring()

# Run any saga with full observability
saga = OrderProcessingSaga(...)
result = await saga.execute()
```

Features:
- ✅ Prometheus metrics
- ✅ OpenTelemetry tracing
- ✅ Structured logging
- ✅ Custom metric labels

## 🧪 Testing

All examples have corresponding tests:

```bash
# Test all examples
pytest tests/test_sagas.py -v

# Test specific example
pytest tests/test_sagas.py::TestOrderProcessingSaga -v
pytest tests/test_sagas.py::TestTravelBookingSaga -v
pytest tests/test_sagas.py::TestTradeExecutionSaga -v
pytest tests/test_sagas.py::TestPaymentSaga -v
```

## 📚 Learning Path

1. **Start:** `order_processing/` - Simplest workflow (4 steps)
2. **Intermediate:** `payment_processing/` - Idempotency patterns
3. **Advanced:** `travel_booking/` - Multi-service orchestration
4. **Expert:** `trade_execution/` - Complex business logic

Each example includes:
- ✅ Complete documentation (README.md)
- ✅ Action implementations (actions.py)
- ✅ Compensation handlers (compensations.py)
- ✅ Main saga logic (main.py)
- ✅ Test coverage

## 🔧 Customization

### Create Your Own Example

```bash
# Copy template
cp -r examples/order_processing examples/my_saga

# Edit files
cd examples/my_saga
# 1. Edit main.py - orchestration logic
# 2. Edit actions.py - forward steps
# 3. Edit compensations.py - rollback steps
# 4. Edit README.md - documentation
```

### Modify Actions

```python
# examples/my_saga/actions.py
async def my_action(ctx: Any) -> Dict[str, Any]:
    """Your business logic here"""
    result = await external_api.call(ctx.data)
    return {"result": result}
```

### Modify Compensations

```python
# examples/my_saga/compensations.py
async def undo_my_action(ctx: Any) -> Dict[str, Any]:
    """Rollback logic here"""
    await external_api.rollback(ctx.data)
    return {"rolled_back": True}
```

## 💡 Best Practices

These examples demonstrate:
- ✅ **Self-Contained**: Each example in its own directory
- ✅ **Separation of Concerns**: Actions, compensations, orchestration separated
- ✅ **Documentation**: Each example has detailed README
- ✅ **Error Handling**: Proper exception handling and retries
- ✅ **Idempotency**: Safe to retry operations
- ✅ **Type Safety**: Type hints for better IDE support
- ✅ **Testing**: All examples have comprehensive tests
- ✅ **Real-World**: Based on actual production patterns

## 🐛 Troubleshooting

### Import Errors
```bash
# Make sure you're in the project root
cd /path/to/saga_pattern

# Install in development mode
pip install -e .
```

### Module Not Found
```bash
# Add project to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/path/to/saga_pattern"
```

### Example Doesn't Run
```bash
# Check dependencies
pip install -r requirements.txt

# Run with Python module syntax
python -m examples.sagas.order_processing
```

## 📖 Related Documentation

- [Main README](../README.md) - Project overview
- [DAG Pattern](../docs/feature_compensation_graph.md) - Parallel execution
- [Optimistic Sending](../docs/optimistic-sending.md) - Performance optimization
- [Consumer Inbox](../docs/consumer-inbox.md) - Exactly-once processing
- [Kubernetes Deployment](../k8s/README.md) - Production deployment

## 🤝 Contributing Examples

Want to add your own example?

1. **Create directory structure:**
```bash
mkdir -p examples/my_example
cd examples/my_example
touch main.py actions.py compensations.py README.md __init__.py
```

2. **Implement your saga:**
   - `main.py` - Orchestration logic
   - `actions.py` - Forward step functions
   - `compensations.py` - Rollback functions
   - `README.md` - Documentation
   - `__init__.py` - Module exports

3. **Add tests:**
```bash
# Add tests to tests/test_sagas.py
```

4. **Update documentation:**
   - Add entry to `examples/README.md`
   - Update `docs/DOCUMENTATION_INDEX.md`

---

**Questions?** Check [documentation index](../docs/DOCUMENTATION_INDEX.md) or open an issue.
