# ADR-031: Dry-Run Command Simplification

**Status:** Accepted  
**Date:** 2026-01-11  
**Deciders:** Architecture Team  
**Related:** [ADR-019](adr-019-dry-run-mode.md), [ADR-030](adr-030-dry-run-parallel-analysis.md)

## Context

The dry-run feature was initially designed with four modes: `validate`, `simulate`, `estimate`, and `trace`. After implementation and usage analysis:

1. **Time estimation challenges**: Duration metadata is chicken-and-egg problem - users don't have duration data until they run sagas, but estimates require upfront metadata
2. **Hard-coded durations**: The `estimate` and `trace` commands relied on default duration values (100ms) when metadata wasn't available, providing unrealistic estimates
3. **Command complexity**: The nested `sagaz dry-run <subcommand>` structure added unnecessary nesting
4. **Limited value**: Estimation without real data and detailed tracing provided minimal practical value compared to DAG analysis

## Decision

We simplify the dry-run feature to focus on its core value: **DAG analysis without side effects**.

### Changes

1. **Remove time estimation completely**:
   - Remove `estimate` and `trace` commands
   - Remove duration-related calculations and metadata dependencies
   - Remove `DryRunTraceEvent`, `EstimateResult`, `TraceResult` dataclasses
   - Remove API pricing and cost calculation features

2. **Flatten command structure**:
   - Change from `sagaz dry-run validate` → `sagaz validate`
   - Change from `sagaz dry-run simulate` → `sagaz simulate`
   - Remove the `dry-run` command group entirely

3. **Focus on parallelization analysis**:
   - `validate`: Configuration validation (cycles, dependencies, compensation)
   - `simulate`: DAG analysis with parallelizable execution layers, critical path, and complexity metrics

### What Remains

```python
# Core functionality
class DryRunMode(Enum):
    VALIDATE = "validate"
    SIMULATE = "simulate"

# Analysis without time estimates
@dataclass
class DryRunResult:
    # Validation
    validation_errors: list[str]
    validation_checks: dict[str, bool]
    
    # DAG analysis
    forward_layers: list[ParallelLayerInfo]
    backward_layers: list[ParallelLayerInfo]
    critical_path: list[str]
    parallelization_ratio: float
    sequential_complexity: int
    parallel_complexity: int
```

### CLI Examples

```bash
# Before
sagaz dry-run validate order_saga.py
sagaz dry-run simulate order_saga.py
sagaz dry-run estimate order_saga.py --scale=10000
sagaz dry-run trace order_saga.py --show-context

# After (simplified)
sagaz validate order_saga.py
sagaz simulate order_saga.py
```

## Consequences

### Positive

- **Clearer purpose**: Dry-run is now explicitly a static analysis tool
- **No misleading data**: Removes unrealistic duration estimates without real metadata
- **Simpler UX**: Flattened command structure is more intuitive
- **Better focus**: Emphasizes valuable DAG parallelization analysis
- **Easier maintenance**: Less code, fewer concepts to maintain

### Negative

- **Lost features**: No cost estimation or detailed trace output
- **Breaking change**: Removes commands users might have scripted
- **Limited observability**: Can't preview execution flow details without real run

### Mitigations

- Users needing duration estimates can use actual execution metrics instead of synthetic estimates
- Observability is better served by actual saga execution with tracing/monitoring
- Breaking changes documented in migration guide

## Alternatives Considered

### 1. Keep estimation with required metadata

Make duration metadata mandatory for estimate command.

**Rejected:** Still chicken-and-egg problem - users need to run sagas first to get realistic durations.

### 2. Separate estimation tool

Create standalone profiling/estimation tool based on historical data.

**Deferred:** Could be future enhancement, but requires execution history analysis infrastructure.

### 3. Keep trace for debugging

Maintain trace command for debugging workflow logic.

**Rejected:** Actual execution with dry-run flag provides better debugging with real step logic execution.

## Implementation Notes

### Code Removed

- `DryRunMode.ESTIMATE` and `DryRunMode.TRACE` enums
- `_estimate()`, `_trace()`, `_calculate_cost()` methods  
- `_calculate_parallel_duration_with_metadata()` method
- `estimate` and `trace` CLI commands
- Display functions for estimation and trace output
- API pricing configuration

### Code Modified

- `DryRunEngine.run()`: Simplified to only handle VALIDATE and SIMULATE modes
- `simulate` display: Removed duration estimate tips and metadata checks
- CLI structure: Flattened from group to individual commands

### Migration Path

```python
# Old code
from sagaz import EstimateResult, TraceResult, DryRunTraceEvent

# New code - removed, use DryRunResult directly
from sagaz import DryRunResult, SimulationResult, ValidationResult
```

## References

- [ADR-019: Dry-Run Mode](adr-019-dry-run-mode.md) - Original dry-run design
- [ADR-030: Dry-Run Parallel Analysis](adr-030-dry-run-parallel-analysis.md) - Enhanced DAG analysis
- Issue: Dry-run estimation relies on hard-coded durations
- User feedback: Nested commands confusing, estimates unrealistic

## Timeline

- **Phase 1** (Current): Remove estimation and flatten commands
- **Phase 2** (Future): Consider historical execution-based profiling tool
- **Phase 3** (Future): Explore ML-based duration prediction from code analysis
