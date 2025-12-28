# ADR-015: Unified Saga API

**Status:** Accepted  
**Date:** 2024-12-28  
**Deciders:** Sagaz Core Team

## Context

Sagaz originally provided **two separate classes** for defining sagas:

1. **`Saga` (declarative)** - Using `@action` and `@compensate` decorators on class methods
2. **`ClassicSaga` (imperative)** - Using `add_step()` method to programmatically add steps

This dual-API approach created several problems:

### Problems

1. **User Confusion**: New users didn't know which class to use
2. **Import Ambiguity**: `from sagaz import Saga` vs `from sagaz import ClassicSaga`
3. **Accidental Mixing**: Users might try to use `add_step()` on a decorated saga
4. **Documentation Overhead**: Had to document two APIs separately
5. **Test Coverage**: Had to test both APIs independently

## Decision

**Unify both approaches into a single `Saga` class** that:

1. Supports both declarative (decorators) and imperative (add_step) modes
2. Detects which mode is being used automatically
3. Prevents mixing of modes with clear error messages
4. Uses `run()` as the single execution method

### How Mode Detection Works

```python
class Saga:
    def __init__(self, name: str | None = None, config=None):
        self._mode = None  # 'declarative', 'imperative', or None
        
        # Collect decorated methods
        self._collect_steps()
        
        if self._steps:
            self._mode = 'declarative'
        # else: allow imperative mode via add_step()
```

### Mode Enforcement

```python
def add_step(self, name, action, compensation=None, ...):
    if self._mode == 'declarative':
        raise TypeError(
            "Cannot use add_step() on a saga with decorators. "
            "Choose one approach: either decorators or add_step()."
        )
    self._mode = 'imperative'
    # ... add step logic
```

## Usage Examples

### Mode 1: Declarative (Decorators)

```python
from sagaz import Saga, action, compensate

class OrderSaga(Saga):
    saga_name = "order-processing"
    
    @action("reserve_inventory")
    async def reserve_inventory(self, ctx):
        return {"inventory_id": await inventory.reserve(ctx["order_id"])}
    
    @compensate("reserve_inventory")
    async def release_inventory(self, ctx):
        await inventory.release(ctx["inventory_id"])
    
    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx):
        return await payment.charge(ctx["amount"])

# Usage
saga = OrderSaga()
result = await saga.run({"order_id": "123", "amount": 99.99})
```

### Mode 2: Imperative (add_step)

```python
from sagaz import Saga

# Create saga instance
saga = Saga(name="order-processing")

# Add steps programmatically
saga.add_step("validate", validate_order)
saga.add_step("reserve", reserve_inventory, release_inventory, depends_on=["validate"])
saga.add_step("charge", charge_payment, refund_payment, depends_on=["reserve"])

# Execute
result = await saga.run({"order_id": "123", "amount": 99.99})
```

### What Happens When Mixing

```python
class MixedSaga(Saga):
    saga_name = "mixed"
    
    @action("step1")
    async def step1(self, ctx):
        return {}

saga = MixedSaga()
saga.add_step("step2", some_action)  # Raises TypeError!
```

Error message:
```
TypeError: Cannot use add_step() on a saga with @action/@compensate decorators.
Choose one approach: either use decorators (declarative) or add_step() (imperative),
but not both. See Saga class docstring for examples.
```

## Consequences

### Positive

1. **Single Class**: Users only need to learn one class
2. **Clear Errors**: Attempting to mix approaches gives helpful error messages
3. **Simpler Imports**: Just `from sagaz import Saga`
4. **Method Chaining**: `add_step()` returns `self` for fluent API
5. **Consistent Execution**: Both modes use `run()` method

### Negative

1. **Breaking Change**: Legacy `ClassicSaga` users need to migrate
2. **Slight Complexity**: Mode detection adds internal complexity

### Migration Path

```python
# Before (ClassicSaga)
from sagaz import ClassicSaga
saga = ClassicSaga(name="order")
saga.add_step("step1", action_fn)
result = await saga.execute()  # Different method

# After (Unified Saga)
from sagaz import Saga
saga = Saga(name="order")
saga.add_step("step1", action_fn)
result = await saga.run({})  # Same method as declarative
```

Key changes:
- `ClassicSaga` → `Saga`
- `execute()` → `run({})` (initial context is now required)

## Backward Compatibility

- `ClassicSaga` is still exported for backward compatibility (deprecated)
- `DAGSaga` and `DeclarativeSaga` are aliases (deprecated)
- Deprecation warnings will be added in a future release

## Related Documents

- [ADR-012: Synchronous Orchestration Model](adr-012-synchronous-orchestration-model.md)
- [Overview](../overview.md)

---

*Accepted 2024-12-28*
