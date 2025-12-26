# Saga Pattern Implementation - AI Agent Instructions

## Architecture Overview

This is a production-ready **Saga Pattern** implementation for distributed transactions with automatic compensation. The core concept: multi-step business processes that can automatically "undo" (compensate) failed steps in reverse order.

### Key Components

- **`saga/core.py`** - Base `Saga` class and `SagaStep` definitions
- **`saga/state_machine.py`** - State machine logic (PENDING → EXECUTING → COMPLETED/COMPENSATING → ROLLED_BACK/FAILED)
- **`saga/dag.py`** - `DAGSaga` extends base with parallel execution using dependency graphs
- **`saga/orchestrator.py`** - `SagaOrchestrator` manages multiple concurrent sagas
- **`saga/strategies/`** - Complete parallel failure handling implementations (fail_fast.py, wait_all.py, fail_fast_grace.py)
- **`saga/storage/`** - Pluggable persistence layer (memory, Redis, PostgreSQL)
- **`saga/monitoring/`** - Comprehensive observability (metrics, logging, tracing)
- **`sagas/`** - Business domain implementations (order_processing, trade_execution, payment, travel_booking)
- **`sagas/actions/`** - Reusable action functions (inventory, payment, notification)
- **`sagas/compensations/`** - Reusable compensation functions

## Critical Patterns

### 1. Saga Definition Pattern
```python
class MyBusinessSaga(Saga):
    async def build(self):
        await self.add_step(
            name="action_name",
            action=self._do_action,           # Required: business logic
            compensation=self._undo_action,   # Optional: rollback logic
            timeout=30.0,                     # Per-step timeout
            max_retries=3                     # Retry with exponential backoff
        )
```

### 2. DAG Pattern for Parallel Steps
```python
class ParallelSaga(DAGSaga):
    async def build(self):
        await self.add_dag_step("step1", action1, comp1)  # No dependencies
        await self.add_dag_step("step2", action2, comp2, dependencies={"step1"})
        await self.add_dag_step("step3", action3, comp3, dependencies={"step1"})  # Parallel with step2
```

### 3. Action/Compensation Signatures
```python
async def action(ctx: SagaContext) -> Any:      # Return value passed to compensation
async def compensation(result: Any, ctx: SagaContext) -> None:  # Undo the action
```

## Development Workflows

### Testing
- **Run tests**: `pytest` (uses pytest-asyncio for async test support)
- **With coverage**: `pytest --cov=saga`
- **File location**: Main tests in `test_saga_pattern.py`, domain tests in `tests/`
- **Async pattern**: All tests use `@pytest.mark.asyncio` decorator

### Code Quality
- **Linting**: `ruff check` (configured with strict async/await rules)
- **Type checking**: `mypy saga/` (full type hints required)
- **Format**: `ruff format`

## Project-Specific Conventions

### 1. State Management
- Uses `python-statemachine` library for robust state transitions
- All saga operations are **async/await** - never use sync code in actions/compensations
- Thread-safe with `asyncio.Lock()` protection in orchestrator

### 2. Error Handling Hierarchy
```python
SagaError                    # Base exception
├── SagaStepError           # Action execution failure
├── SagaCompensationError   # Compensation failure (critical!)
├── SagaTimeoutError        # Step timeout
└── SagaExecutionError      # General execution error
```

### 3. Context Passing
- `SagaContext` carries data between steps and compensations
- Immutable - create new context with `ctx.with_data(new_data)` 
- Access via `ctx.get("key")` or `ctx.saga_id`, `ctx.step_name`

### 4. Failure Strategy Configuration
When using `DAGSaga`, configure parallel failure handling:
- `FAIL_FAST`: Cancel other parallel steps immediately on failure
- `WAIT_ALL`: Let all parallel steps complete, then compensate
- `FAIL_FAST_WITH_GRACE`: Cancel remaining, wait for in-flight to finish

### 5. Business Saga Structure
Look at `sagas/order_processing.py`, `sagas/trade_execution.py` for patterns:
- Constructor takes business parameters (`order_id`, `user_id`, etc.)
- `build()` method defines the saga flow
- Private methods `_action_name()` and `_compensation_name()` implement logic
- Always include proper logging and simulate realistic delays

### 6. Reusable Actions/Compensations
- **Actions**: `sagas/actions/{inventory,payment,notification}.py` - Reusable business operations
- **Compensations**: `sagas/compensations/{inventory,payment,notification}.py` - Corresponding rollback operations
- Import and use these in your business sagas instead of implementing from scratch

## Integration Points

### Storage Layer
- **In-Memory**: `InMemorySagaStorage` - Development/testing only
- **Redis**: `RedisSagaStorage` - Distributed caching with TTL support
- **PostgreSQL**: `PostgreSQLSagaStorage` - ACID-compliant with SQL querying
- Use `async with storage:` pattern for proper connection management

### Monitoring & Observability
- **Metrics**: `SagaMetrics` - Execution statistics and performance tracking
- **Logging**: `SagaLogger` with structured JSON output and context propagation
- **Tracing**: `SagaTracer` with OpenTelemetry integration (optional)
- Use decorators `@trace_saga_action` and `@trace_saga_compensation` for automatic tracing

### External Dependencies
- Actions typically call external services (payment gateways, inventory systems)
- Use proper async HTTP clients (aiohttp, httpx) in action implementations
- Implement proper retry and timeout handling per service SLA

## Anti-Patterns to Avoid

1. **Don't** add steps after saga execution starts (raises exception)
2. **Don't** use sync code in async action/compensation methods
3. **Don't** ignore compensation failures - they indicate data consistency issues
4. **Don't** make compensations depend on external service state - they must be reliable
5. **Don't** create circular dependencies in DAG steps (validation will catch this)

## Key Files for New Features

- **New business domain**: Add to `sagas/` directory following existing patterns
- **New reusable action**: Add to `sagas/actions/` with corresponding compensation in `sagas/compensations/`
- **New failure strategy**: Extend `saga/strategies/base.py` and implement in new strategy file
- **New storage backend**: Implement `SagaStorage` interface in `saga/storage/`
- **Core modifications**: Modify `saga/core.py` with extreme caution (affects all sagas)
- **State machine changes**: Update `saga/state_machine.py` for new states/transitions
- **Monitoring**: Extend `saga/monitoring/` modules for new observability features