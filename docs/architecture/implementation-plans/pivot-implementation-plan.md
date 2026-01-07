# ADR-023: Pivot/Irreversible Steps - Implementation Plan

**Version:** 1.0  
**Created:** 2026-01-07  
**Target Release:** v1.3.0  
**Related ADR:** [ADR-023: Pivot/Irreversible Steps](adr/adr-023-pivot-irreversible-steps.md)

---

## Executive Summary

This implementation plan details the phased rollout of the **Pivot/Irreversible Steps** feature from ADR-023. The feature enables marking saga steps as "points of no return" with automatic taint propagation and forward recovery strategies.

---

## Phase Overview

| Phase | Description | Effort | Status |
|-------|-------------|--------|--------|
| **Phase 1** | Core Types & Enums | 3h | ✅ Complete |
| **Phase 2** | SagaStep/StepMetadata Extension | 4h | ✅ Complete |
| **Phase 3** | Taint Propagation Algorithm | 6h | ✅ Complete |
| **Phase 4** | Forward Recovery Decorator | 4h | ✅ Complete |
| **Phase 5** | Saga Execution Integration | 6h | ✅ Complete |
| **Phase 6** | Mermaid Visualization | 3h | ✅ Complete |
| **Phase 7** | Tests & Documentation | 6h | ✅ Complete |

**Total Effort:** ~32 hours (~4 days)
**Actual Completion:** ~3 hours (2026-01-07)
**Status:** ✅ **FULLY IMPLEMENTED**


---

## Phase 1: Core Types & Enums (3h)

### Objective
Add new types for pivot steps, recovery actions, and zone tracking.

### Files to Modify/Create

#### 1.1 Create `sagaz/pivot.py` (New)

```python
"""
Pivot/Irreversible Steps Support.

Provides types and utilities for marking saga steps as "points of no return"
with automatic taint propagation and forward recovery strategies.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


class RecoveryAction(Enum):
    """Actions that forward recovery handlers can return."""
    
    RETRY = "retry"                       # Retry the failed step
    RETRY_WITH_ALTERNATE = "retry_alt"    # Retry with alternate logic
    SKIP = "skip"                         # Skip this step, continue forward
    MANUAL_INTERVENTION = "manual"        # Escalate to human/manual handling
    COMPENSATE_PIVOT = "compensate"       # Trigger pivot compensation (rare)


class StepZone(Enum):
    """Zone classification for saga steps relative to pivots."""
    
    REVERSIBLE = "reversible"     # Before any pivot - full rollback available
    PIVOT = "pivot"               # The pivot step itself - commitment point
    COMMITTED = "committed"       # After pivot - forward recovery only
    TAINTED = "tainted"          # Ancestors of completed pivot - locked


@dataclass
class PivotBoundary:
    """Represents a pivot step and its taint boundary."""
    
    step_name: str
    completed: bool = False
    tainted_ancestors: set[str] = field(default_factory=set)


@dataclass
class SagaZones:
    """Zone analysis result for a saga."""
    
    reversible: set[str] = field(default_factory=set)
    pivots: set[str] = field(default_factory=set)
    committed: set[str] = field(default_factory=set)
    tainted: set[str] = field(default_factory=set)
    
    def get_zone(self, step_name: str) -> StepZone:
        """Get the zone for a specific step."""
        if step_name in self.tainted:
            return StepZone.TAINTED
        if step_name in self.pivots:
            return StepZone.PIVOT
        if step_name in self.committed:
            return StepZone.COMMITTED
        return StepZone.REVERSIBLE


# Type aliases for forward recovery handlers
ForwardRecoveryHandler = Callable[
    [dict[str, Any], Exception], 
    Awaitable[RecoveryAction]
]
```

#### 1.2 Update `sagaz/types.py`

Add new status values and extend `SagaResult`:

```python
# Add to SagaStatus enum
class SagaStatus(Enum):
    # ... existing ...
    PARTIALLY_COMMITTED = "partially_committed"  # Pivot passed, but failed after
    NEEDS_FORWARD_RECOVERY = "forward_recovery"  # Waiting for forward recovery


# Extend SagaResult dataclass
@dataclass
class SagaResult:
    # ... existing fields ...
    
    # New pivot-aware fields
    pivot_reached: bool = False
    committed_steps: list[str] = field(default_factory=list)
    tainted_steps: list[str] = field(default_factory=list)
    forward_recovery_needed: bool = False
    rollback_boundary: str | None = None  # Step name where rollback stopped
```

---

## Phase 2: SagaStep/StepMetadata Extension (4h)

### Objective
Add `pivot` parameter to step definitions in both imperative and declarative APIs.

### Files to Modify

#### 2.1 Update `sagaz/core.py` - SagaStep

```python
@dataclass
class SagaStep:
    """Represents a single step in a saga with full metadata"""
    
    # ... existing fields ...
    
    # NEW: Pivot support
    pivot: bool = False  # True if this is a point of no return
    tainted: bool = False  # True if an ancestor pivot has completed
    zone: StepZone = field(default=StepZone.REVERSIBLE)
```

#### 2.2 Update `sagaz/core.py` - Saga.add_step()

```python
def add_step(
    self,
    name: str,
    action: Callable,
    compensation: Callable | None = None,
    dependencies: set[str] | None = None,
    timeout: float = 30.0,
    compensation_timeout: float = 30.0,
    max_retries: int = 3,
    idempotency_key: str | None = None,
    pivot: bool = False,  # NEW
) -> None:
```

#### 2.3 Update `sagaz/decorators.py` - StepMetadata

```python
@dataclass
class StepMetadata:
    # ... existing fields ...
    pivot: bool = False  # NEW
```

#### 2.4 Update `sagaz/decorators.py` - step() decorator

```python
def step(
    name: str,
    depends_on: list[str] | None = None,
    # ... existing ...
    pivot: bool = False,  # NEW
) -> Callable[[F], F]:
```

Also add `action` as alias:

```python
# Alias for step() decorator
def action(
    name: str,
    depends_on: list[str] | None = None,
    pivot: bool = False,
    # ... other params ...
) -> Callable[[F], F]:
    """Alias for step() decorator."""
    return step(name=name, depends_on=depends_on, pivot=pivot, ...)
```

---

## Phase 3: Taint Propagation Algorithm (6h)

### Objective
Implement algorithm to calculate tainted steps and zones.

### Files to Modify/Create

#### 3.1 Add to `sagaz/pivot.py`

```python
class TaintPropagator:
    """
    Calculates taint propagation when pivots complete.
    
    When a pivot step completes:
    1. All ancestor steps become "tainted" (locked from rollback)
    2. The pivot itself is the boundary
    3. Descendant steps remain in "committed" zone
    """
    
    def __init__(self, steps: list[SagaStep], dependencies: dict[str, set[str]]):
        self.steps = {s.name: s for s in steps}
        self.dependencies = dependencies
        
    def get_ancestors(self, step_name: str) -> set[str]:
        """Get all ancestors of a step (transitive dependencies)."""
        ancestors = set()
        to_visit = list(self.dependencies.get(step_name, set()))
        
        while to_visit:
            current = to_visit.pop()
            if current not in ancestors:
                ancestors.add(current)
                to_visit.extend(self.dependencies.get(current, set()))
                
        return ancestors
    
    def get_descendants(self, step_name: str) -> set[str]:
        """Get all descendants of a step."""
        descendants = set()
        for name, deps in self.dependencies.items():
            if step_name in deps:
                descendants.add(name)
                descendants.update(self.get_descendants(name))
        return descendants
    
    def propagate_taint(self, completed_pivot: str) -> set[str]:
        """
        Propagate taint from a completed pivot.
        
        Returns set of newly tainted step names.
        """
        ancestors = self.get_ancestors(completed_pivot)
        for ancestor_name in ancestors:
            if ancestor_name in self.steps:
                self.steps[ancestor_name].tainted = True
        return ancestors
    
    def calculate_zones(self) -> SagaZones:
        """Calculate zones for all steps."""
        zones = SagaZones()
        
        # Find all pivots
        pivots = {name for name, step in self.steps.items() if step.pivot}
        zones.pivots = pivots
        
        # Find all pivot ancestors (potentially tainted)
        for pivot_name in pivots:
            ancestors = self.get_ancestors(pivot_name)
            # Only tainted if pivot completed
            if self.steps[pivot_name].tainted:  # Pivot completion marked
                zones.tainted.update(ancestors)
            else:
                zones.reversible.update(ancestors)
        
        # Everything else is committed (after pivot)
        all_steps = set(self.steps.keys())
        zones.committed = all_steps - zones.reversible - zones.pivots - zones.tainted
        
        return zones
    
    def get_rollback_boundary(self, failed_step: str) -> str | None:
        """
        Get the rollback boundary for a failed step.
        
        If the step is after a completed pivot, rollback stops at the pivot.
        """
        for pivot_name, step in self.steps.items():
            if step.pivot and step.tainted:  # Pivot completed
                descendants = self.get_descendants(pivot_name)
                if failed_step in descendants or failed_step == pivot_name:
                    return pivot_name
        return None  # Full rollback available
```

---

## Phase 4: Forward Recovery Decorator (4h)

### Objective
Implement `@forward_recovery` decorator and handler invocation.

### Files to Modify

#### 4.1 Add to `sagaz/decorators.py`

```python
@dataclass
class ForwardRecoveryMetadata:
    """Metadata for forward recovery handlers."""
    for_step: str
    max_retries: int = 3
    timeout_seconds: float = 30.0


def forward_recovery(
    for_step: str,
    max_retries: int = 3,
    timeout_seconds: float = 30.0,
) -> Callable[[F], F]:
    """
    Decorator to mark a method as forward recovery handler for a step.
    
    Forward recovery is invoked when a step fails AFTER a pivot has completed.
    Instead of traditional compensation (rollback), the handler decides how
    to proceed forward.
    
    Args:
        for_step: Name of the step this handles recovery for
        max_retries: Maximum retry attempts if RETRY action returned
        timeout_seconds: Handler timeout
    
    Example:
        @forward_recovery("ship_order")
        async def handle_shipping_failure(self, ctx, error) -> RecoveryAction:
            if ctx.get("retry_count", 0) < 3:
                return RecoveryAction.RETRY
            return RecoveryAction.MANUAL_INTERVENTION
    """
    def decorator(func: F) -> F:
        func._saga_forward_recovery_meta = ForwardRecoveryMetadata(
            for_step=for_step,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        return func
    return decorator
```

#### 4.2 Update Saga class to collect forward recovery handlers

```python
class Saga:
    def __init__(self, ...):
        # ... existing ...
        self._forward_recovery_handlers: dict[str, Callable] = {}
        
    def _collect_steps(self) -> None:
        self._collect_step_methods()
        self._attach_compensations()
        self._collect_forward_recovery_handlers()  # NEW
        
    def _collect_forward_recovery_handlers(self) -> None:
        """Collect forward recovery handlers."""
        for attr_name in dir(self):
            if attr_name.startswith("_"):
                continue
            attr = getattr(self, attr_name)
            if hasattr(attr, "_saga_forward_recovery_meta"):
                meta = attr._saga_forward_recovery_meta
                self._forward_recovery_handlers[meta.for_step] = attr
```

---

## Phase 5: Saga Execution Integration (6h)

### Objective
Modify execution flow to respect pivots and invoke forward recovery.

### Key Changes

#### 5.1 Update `_execute_step` in both Saga classes

After pivot step completes:
```python
async def _execute_step(self, step: SagaStep) -> None:
    # ... execute action ...
    
    # NEW: Handle pivot completion
    if step.pivot:
        self._propagate_taint(step.name)
```

#### 5.2 Update `_compensate_all` to respect taint boundary

```python
async def _compensate_all(self) -> None:
    """Compensate steps, stopping at pivot boundary."""
    for step in reversed(self.completed_steps):
        # NEW: Stop at pivot boundary
        if step.tainted:
            logger.info(f"Stopping compensation at tainted step: {step.name}")
            break
            
        if step.pivot:
            logger.info(f"Reached pivot boundary: {step.name}")
            break
            
        if step.compensation:
            await self._compensate_step(step)
```

#### 5.3 Add forward recovery invocation

```python
async def _handle_post_pivot_failure(
    self, 
    step: SagaStep, 
    error: Exception
) -> RecoveryAction:
    """Handle failure in post-pivot step."""
    handler = self._forward_recovery_handlers.get(step.name)
    
    if handler:
        return await handler(self._context, error)
    
    # Default: manual intervention if no handler
    return RecoveryAction.MANUAL_INTERVENTION
```

---

## Phase 6: Mermaid Visualization (3h)

### Objective
Add zone coloring to Mermaid diagrams.

### Files to Modify

#### 6.1 Update `sagaz/mermaid.py`

Add zone-based styling:

```python
ZONE_STYLES = {
    StepZone.REVERSIBLE: "fill:#98FB98",    # Light green
    StepZone.PIVOT: "fill:#FFD700",         # Gold
    StepZone.COMMITTED: "fill:#87CEEB",     # Light blue  
    StepZone.TAINTED: "fill:#DDA0DD",       # Plum (locked)
}
```

Update `MermaidGenerator` to accept zones and apply styling.

---

## Phase 7: Tests & Documentation (6h)

### Test Files to Create

- `tests/test_pivot.py` - Core pivot functionality
- `tests/test_forward_recovery.py` - Forward recovery handlers
- `tests/test_taint_propagation.py` - Taint algorithm
- `tests/test_pivot_mermaid.py` - Visualization tests

### Documentation Updates

- Update `README.md` with pivot feature
- Update `docs/api/` with new decorators
- Add `docs/guides/pivot-steps.md` tutorial

---

## Implementation Order

```
Phase 1: Core Types
    ↓
Phase 2: Step Extensions
    ↓
Phase 3: Taint Algorithm 
    ↓
Phase 4: Forward Recovery ←→ Phase 5: Execution Integration
    ↓
Phase 6: Visualization
    ↓
Phase 7: Tests & Docs
```

Phases 4 and 5 can be developed in parallel.

---

## Success Criteria

1. ✅ `pivot=True` parameter works in both `add_step()` and `@action` decorator
2. ✅ Taint propagation correctly marks ancestors when pivot completes
3. ✅ Compensation stops at pivot boundary
4. ✅ `@forward_recovery` decorator invoked for post-pivot failures
5. ✅ `SagaResult` includes pivot-aware fields
6. ✅ Mermaid diagrams show zones with color coding
7. ✅ All tests pass with >90% coverage
8. ✅ Documentation updated

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Breaking existing sagas | Default `pivot=False` preserves existing behavior |
| Complex DAG scenarios | Start with linear sagas, test DAG cases incrementally |
| Forward recovery complexity | Provide sensible defaults, detailed error messages |

---

## References

- [ADR-023: Pivot/Irreversible Steps](adr/adr-023-pivot-irreversible-steps.md)
- [ADR-022: Compensation Result Passing](adr/adr-022-compensation-result-passing.md)
