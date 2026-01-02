# ADR-022: Unified Execution Graph and Compensation Context

**Status:** Accepted  
**Date:** 2026-01-01  
**Updated:** 2026-01-01 (Architectural Refinement)
**Deciders:** Sagaz Core Team

## Context

The saga pattern implementation had separate concerns for forward execution and compensation that led to architectural questions:

### Original Limitations

1. **No Result Passing Between Compensations**: Compensations couldn't share data with each other, limiting coordination capabilities
2. **No Configurable Failure Handling**: When a compensation failed, the behavior was fixed
3. **Separate Graph Classes**: Having a `SagaCompensationGraph` but no corresponding `SagaActionGraph` raised questions about the distinction
4. **Context Management**: Using plain `dict[str, Any]` for both saga context and compensation context mixed concerns

### Architectural Questions

1. **Is SagaCompensationGraph distinction necessary?** Since we're essentially reversing dependency arrows, could this be unified?
2. **Should compensation have its own context?** A separate `SagaCompensationContext` could facilitate blob storage and snapshots

## Decision

### 1. Unified Execution Graph

**Renamed `SagaCompensationGraph` → `SagaExecutionGraph`** with backward compatibility alias.

**Rationale:**
- The same dependency structure serves both forward execution and compensation (reversed)
- Unifying simplifies the architecture - one graph, two directions
- Compensation-specific features (CompensationType, timeouts, retries) remain as node metadata
- Forward execution continues to use inline topological sort on `SagaStepDefinition` in the Saga class
- `SagaExecutionGraph` focuses on compensation tracking and execution

**Implementation:**
```python
class SagaExecutionGraph:
    """
    Unified graph for managing both forward execution and compensation dependencies.
    
    The same dependency structure is used in both directions:
    - Forward: for action execution
    - Reversed: for compensation
    """
    
# Backward compatibility
SagaCompensationGraph = SagaExecutionGraph
```

### 2. Separate Compensation Context

**Introduced `SagaCompensationContext`** to separate compensation concerns.

**Rationale:**
- Facilitates blob storage and context snapshots
- Clear separation between saga execution context and compensation context
- Makes it explicit what data is available during compensation
- Enables better serialization for distributed compensation

**Structure:**
```python
@dataclass
class SagaCompensationContext:
    saga_id: str
    step_id: str
    original_context: dict[str, Any]  # Snapshot at failure time
    compensation_results: dict[str, Any]  # Results from prior compensations
    metadata: dict[str, Any]
    created_at: datetime
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for blob storage"""
        
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SagaCompensationContext":
        """Restore from storage"""
```

### 3. Compensation Result Passing

Allow compensation functions to return values and access results from previously executed compensations.

#### New Signature

```python
# Old signature (still supported)
async def refund_payment(ctx: dict) -> None:
    await PaymentService.refund(ctx["charge_id"])

# New signature
async def refund_payment(ctx: dict, compensation_results: dict[str, Any]) -> Any:
    # Access results from prior compensations
    cancelled_order_id = compensation_results.get("cancel_order", {}).get("cancellation_id")
    refund = await PaymentService.refund(ctx["charge_id"], reference=cancelled_order_id)
    return {"refund_id": refund.id}  # Return result for downstream compensations
```

#### Implementation Details

- **Signature Detection**: Use `inspect.signature()` to detect function signature
- **Backward Compatibility**: Old signature (ctx only) still works
- **Result Storage**: Store in `_compensation_results` dict (already existed, unused)
- **Passing**: Pass as second parameter to compensation functions

### 4. Failure Strategies

Introduce four configurable strategies for handling compensation failures:

```python
class CompensationFailureStrategy(Enum):
    FAIL_FAST = "fail_fast"
    """Stop immediately on first failure, don't attempt remaining compensations"""
    
    CONTINUE_ON_ERROR = "continue_on_error"  
    """Continue with remaining compensations, collect all errors (default)"""
    
    RETRY_THEN_CONTINUE = "retry_then_continue"
    """Retry failed compensation (using max_retries), then continue if still fails"""
    
    SKIP_DEPENDENTS = "skip_dependents"
    """Skip compensations that depend on the failed one, continue with independent"""
```

### 5. Enhanced Execution API

New `execute_compensations()` method supports both dict and SagaCompensationContext:

```python
# With dict (backward compatible)
result = await graph.execute_compensations(
    context={"order_id": "123"},
    failure_strategy=CompensationFailureStrategy.SKIP_DEPENDENTS
)

# With SagaCompensationContext (new, for blob storage)
comp_context = SagaCompensationContext(
    saga_id="saga-123",
    step_id="",
    original_context={"order_id": "123"},
    compensation_results={}
)
result = await graph.execute_compensations(
    context=comp_context,
    failure_strategy=CompensationFailureStrategy.SKIP_DEPENDENTS
)
```
    logger.error(f"Compensations failed: {result.failed}")
    logger.warning(f"Compensations skipped: {result.skipped}")
```

## Examples

### Example 1: Result Passing

```python
graph = SagaCompensationGraph()

async def cancel_order(ctx, comp_results=None):
    order_id = ctx["order_id"]
    cancellation = await OrderService.cancel(order_id)
    return {"cancellation_id": cancellation.id, "cancelled_at": datetime.now()}

async def refund_payment(ctx, comp_results=None):
    # Access result from cancel_order compensation
    cancellation_id = comp_results.get("cancel_order", {}).get("cancellation_id")
    refund = await PaymentService.refund(
        ctx["charge_id"], 
        reason=f"Order cancelled: {cancellation_id}"
    )
    return {"refund_id": refund.id}

# Note: Forward dependencies determine compensation order
# refund_payment depends_on cancel_order (forward)
# So compensation order: refund_payment first, then cancel_order
# But we want cancel_order first, so we reverse the dependency:
graph.register_compensation("refund_payment", refund_payment)
graph.register_compensation("cancel_order", cancel_order, depends_on=["refund_payment"])

result = await graph.execute_compensations(context)
print(result.results["cancel_order"]["cancellation_id"])  # "cancel-123"
```

**Important**: Remember that compensation order is REVERSED from forward execution order!

### Example 2: Failure Strategy - FAIL_FAST

```python
graph = SagaCompensationGraph()

# If payment refund fails, stop immediately (critical operation)
result = await graph.execute_compensations(
    context,
    failure_strategy=CompensationFailureStrategy.FAIL_FAST
)

if not result.success:
    # result.failed contains the step that failed
    # result.skipped contains steps that didn't run
    alert_operations_team(result.failed, result.errors)
```

### Example 3: Failure Strategy - SKIP_DEPENDENTS

```python
graph = SagaCompensationGraph()

async def cancel_order(ctx, comp_results=None):
    return await OrderService.cancel(ctx["order_id"])

async def send_cancellation_email(ctx, comp_results=None):
    # Needs cancellation data
    cancel_result = comp_results.get("cancel_order", {})
    await EmailService.send_cancellation(cancel_result)

async def release_inventory(ctx, comp_results=None):
    # Independent of order cancellation
    await InventoryService.release(ctx["sku"])

# Forward dependencies (reversed in compensation):
# cancel_order runs first, send_email depends on it, inventory is independent
graph.register_compensation("send_cancellation_email", send_cancellation_email)
graph.register_compensation("cancel_order", cancel_order, depends_on=["send_cancellation_email"])
graph.register_compensation("release_inventory", release_inventory)

result = await graph.execute_compensations(
    context,
    failure_strategy=CompensationFailureStrategy.SKIP_DEPENDENTS
)

# If cancel_order fails:
# - send_cancellation_email is skipped (depends on cancel_order)
# - release_inventory still runs (independent)
```

## Migration Path

### For Existing Code

No changes required! The new features are opt-in:

1. **Old compensation functions continue to work**:
   ```python
   async def old_comp(ctx):
       await cleanup(ctx)
   # No changes needed, still works
   ```

2. **Existing Saga class continues to work**:
   ```python
   saga = MySaga()
   await saga.run(context)
   # Uses existing _compensate() method, no changes needed
   ```

### To Adopt New Features

1. **Add `comp_results` parameter to compensation functions**:
   ```python
   async def new_comp(ctx, comp_results=None):
       prior_result = comp_results.get("prior_step", {})
       return {"new_data": "value"}
   ```

2. **Use `execute_compensations()` for failure strategies**:
   ```python
   result = await graph.execute_compensations(
       context,
       failure_strategy=CompensationFailureStrategy.SKIP_DEPENDENTS
   )
   ```

3. **Access detailed results**:
   ```python
   if not result.success:
       logger.error(f"Failed steps: {result.failed}")
       for step_id, error in result.errors.items():
           logger.error(f"{step_id} failed: {error}")
   ```

## Design Decisions

### Why Unify into SagaExecutionGraph?

**Decision:** Renamed `SagaCompensationGraph` to `SagaExecutionGraph` with backward compatibility alias.

**Rationale:**
- Eliminates architectural confusion: why have `SagaCompensationGraph` but no `SagaActionGraph`?
- Same dependency structure used bidirectionally (forward for execution, reversed for compensation)
- Simplifies mental model: one graph, two traversal directions
- Compensation-specific features (types, timeouts) remain as node metadata
- Maintains backward compatibility via alias

### Why Introduce SagaCompensationContext?

**Decision:** Created separate `SagaCompensationContext` dataclass.

**Rationale:**
- **Blob Storage Support**: Context snapshots can be serialized/deserialized for distributed compensation
- **Clear Separation**: Distinguishes between saga execution context and compensation context
- **Explicit Data**: Makes it clear what data is available during compensation
- **Metadata Tracking**: Built-in fields for saga_id, step_id, timestamps
- **Backward Compatible**: `execute_compensations()` accepts both dict and SagaCompensationContext

### Why Use `comp_results` as Second Parameter?

**Alternatives Considered:**
1. Store in context (e.g., `ctx["_compensation_results"]`)
2. Use context manager or separate state object
3. Require explicit dependency declaration

**Chosen Approach:**
- Explicit parameter makes result passing visible
- Maintains clean separation between saga context and compensation results
- Easy to detect via signature inspection
- Backward compatible (optional parameter)

### Why CONTINUE_ON_ERROR as Default?

**Rationale:**
- Matches existing behavior (all compensations attempt to run)
- Most forgiving strategy (maximizes cleanup attempts)
- Users can opt into stricter strategies as needed

### Why Not Update Saga Class to Use New Method?

**Decision:**
- Keep existing Saga class unchanged for stability
- New features are opt-in via direct graph usage
- Avoids breaking changes to listeners/hooks integration
- Future enhancement can integrate if needed

## Consequences

### Positive

- **Unified Architecture**: Single graph concept eliminates confusion
- **Blob Storage Ready**: `SagaCompensationContext` enables distributed compensation
- **Enhanced Coordination**: Compensations can share data
- **Flexible Error Handling**: Choose strategy based on business requirements
- **Better Observability**: Detailed results show exactly what happened
- **Backward Compatible**: No breaking changes to existing code
- **Type Safe**: Uses dataclasses and type hints throughout

### Negative

- **Complexity**: More options to understand and configure
- **Documentation**: Need to explain compensation order carefully (reversed!)
- **Performance**: Signature detection adds small overhead (cached after first call)
- **Migration**: Users wanting blob storage need to adopt SagaCompensationContext

### Neutral

- **Two APIs**: Can use `get_compensation_order()` (old) or `execute_compensations()` (new)
- **Learning Curve**: Need to understand compensation order reversal
- **Alias Maintenance**: `SagaCompensationGraph` remains as alias for backward compatibility

## Testing

Comprehensive test coverage added in `tests/test_compensation_graph.py`:

- ✅ Result passing between compensations
- ✅ Backward compatibility (old signatures)
- ✅ Mixed old and new signatures
- ✅ All four failure strategies
- ✅ Parallel execution within levels
- ✅ Timeout handling
- ✅ Circular dependency detection
- ✅ Empty graph and edge cases

## Related ADRs

- **ADR-015**: Unified Saga API - Established imperative vs declarative patterns
- **ADR-016**: Saga Replay - May need result passing for replay consistency

## References

- [Saga Pattern - Chris Richardson](https://microservices.io/patterns/data/saga.html)
- [Compensation Patterns in Distributed Systems](https://docs.microsoft.com/en-us/azure/architecture/patterns/compensating-transaction)
