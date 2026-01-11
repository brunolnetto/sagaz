# ADR-030: Dry-Run Parallel Execution Analysis

## Status

**✅ IMPLEMENTED** | Date: 2026-01-11 | Priority: High | Version: v1.4.0

**Implementation Status**: Complete - dry-run is now a true DAG analysis tool

## Dependencies

**Prerequisites**:
- ADR-019: Dry-Run Mode (extends this feature)
- ADR-015: Unified Saga API (DAG dependency analysis)

**Estimated Development Time**: 3-4 hours with AI assistance
- Analysis algorithm: 1.5 hours
- CLI enhancement: 0.5 hours  
- Test coverage: 1.5 hours

## Context

### Current Limitations

The current dry-run implementation (ADR-019) has several issues:

1. **Hardcoded durations**: Relies on `__sagaz_metadata__` being manually added to action functions
   - Users must manually annotate every action with `estimated_duration_ms`
   - Estimates are unrealistic and often ignored
   - Creates chicken-egg problem: need metadata to estimate, but no metadata exists

2. **Missing key analysis**: Doesn't clearly show parallelizable execution groups
   - Current output shows sequential execution order
   - Parallel groups are computed but not prominently displayed
   - Users can't easily see what steps run in parallel

3. **Misleading estimates**: Shows "Duration (parallel)" but it's based on hardcoded values
   - Example output: `Duration (parallel): 0.55s` (meaningless without real data)
   - Doesn't explain parallelization strategy

4. **Not a true analysis tool**: Functions more as a simulator than an analyzer
   - Should focus on **structural analysis** (what CAN run in parallel)
   - Should provide **upper bounds** based on parallelizable layers
   - Should help users understand saga DAG structure

### User Feedback

From recent CLI usage:
```bash
$ sagaz dry-run estimate test_order_saga.py
Duration (parallel): 0.55s    # Where does this come from?
API: payment_gateway: 1        # Hardcoded metadata
```

User: *"I don't feel comfortable with these hard-coded durations. I want to see the parallelizable forward and backward groups as an analysis tool."*

## Decision

Reframe **dry-run** as a **structural analysis tool** that:

1. **Analyzes DAG structure** without requiring duration metadata
2. **Identifies parallelizable layers** (forward execution groups)
3. **Shows compensation groups** (backward rollback layers)
4. **Provides upper bounds** using layer-based max operators
5. **Makes parallelization explicit** in output

### Key Changes

#### 1. Analysis-First Approach

**OLD** (metadata-dependent):
```python
# Required manual annotation
@action("charge_payment")
async def charge_payment(self, ctx):
    ...

charge_payment.__sagaz_metadata__ = {
    "estimated_duration_ms": 200,  # Hardcoded!
    "api_calls": {"payment": 1}
}
```

**NEW** (structure-based):
```python
# No metadata needed - analyzes DAG structure
@action("charge_payment", depends_on={"reserve_inventory"})
async def charge_payment(self, ctx):
    ...

# Dry-run analyzes:
# - This is in layer 2 (depends on layer 1)
# - Can run in parallel with other layer 2 steps
# - Requires compensation on failure
```

#### 2. Parallel Layer Visualization

**OLD** output:
```
Execution Order:
  1. create_order
  2. reserve_inventory
  3. charge_payment
  4. ship_order
  5. send_confirmation

Estimated Duration (with parallelism): 0.55s
```

**NEW** output:
```
Forward Execution Layers (Parallelizable Groups):

Layer 0 (no dependencies):
  • create_order

Layer 1 (depends on layer 0):
  • reserve_inventory

Layer 2 (depends on layer 1):
  • charge_payment

Layer 3 (depends on layer 2):
  • ship_order

Layer 4 (depends on layer 3):
  • send_confirmation

Parallelization Analysis:
  • 5 layers (sequential bottleneck)
  • Max parallel steps per layer: 1
  • No parallelization opportunities (linear DAG)

Compensation Layers (Rollback Order):

Layer 0: send_confirmation (no compensation)
Layer 1: ship_order -> cancel_shipment
Layer 2: charge_payment -> refund_payment
Layer 3: reserve_inventory -> release_inventory
Layer 4: create_order -> cancel_order
```

#### 3. Upper Bound Estimation

Instead of hardcoded durations, provide **complexity-based bounds**:

```python
@dataclass
class ParallelizationMetrics:
    """Metrics for understanding saga parallelization."""
    
    total_steps: int
    forward_layers: int  # Number of sequential layers
    max_parallel_width: int  # Max steps that can run simultaneously
    backward_layers: int  # Compensation layers
    
    # Complexity estimates (without hardcoded durations)
    sequential_complexity: int  # Sum of all steps
    parallel_complexity: int  # Sum of layer maximums
    parallelization_ratio: float  # parallel / sequential
    
    # Critical path (longest dependency chain)
    critical_path: list[str]
    critical_path_length: int
```

**Output**:
```
Complexity Analysis:

Sequential Execution:
  • Total steps: 5
  • Complexity: 5 units

Parallel Execution:
  • Forward layers: 5
  • Max width: 1 step/layer
  • Complexity: 5 units
  • Parallelization ratio: 1.0 (no benefit)

Critical Path:
  create_order → reserve_inventory → charge_payment → ship_order → send_confirmation
  Length: 5 steps (no shortcuts possible)

Upper Bound (with unlimited parallelism):
  • Best case: 5 layers (each layer = 1 time unit)
  • Note: Linear DAG provides no parallelization opportunities
```

#### 4. Duration Metadata (Optional Enhancement)

If users DO provide duration metadata, enhance the analysis:

```python
# Optional: Add duration hints for better estimates
@action("charge_payment", estimated_duration_ms=200)
async def charge_payment(self, ctx):
    ...
```

Then dry-run can provide:
```
Duration Estimates (based on metadata):
  • Sequential: 550ms (sum of all steps)
  • Parallel: 550ms (max per layer, summed)
  • Critical path: 550ms
  
Note: Estimates require duration metadata on actions.
     Use decorator parameter: @action("name", estimated_duration_ms=100)
```

## Implementation

### Enhanced DryRunResult

```python
@dataclass
class ParallelLayerInfo:
    """Information about a parallelizable execution layer."""
    layer_number: int
    steps: list[str]
    dependencies: set[str]  # Steps from previous layers
    estimated_duration_ms: float | None = None  # Optional


@dataclass  
class DryRunResult:
    """Enhanced with parallel analysis."""
    
    # ... existing fields ...
    
    # NEW: Parallel execution analysis
    forward_layers: list[ParallelLayerInfo] = field(default_factory=list)
    backward_layers: list[ParallelLayerInfo] = field(default_factory=list)
    
    # Parallelization metrics
    total_layers: int = 0
    max_parallel_width: int = 0
    critical_path: list[str] = field(default_factory=list)
    parallelization_ratio: float = 1.0
    
    # Complexity (without metadata)
    sequential_complexity: int = 0
    parallel_complexity: int = 0
    
    # Duration estimates (only if metadata available)
    has_duration_metadata: bool = False
    estimated_sequential_ms: float | None = None
    estimated_parallel_ms: float | None = None
```

### Enhanced CLI Output

```python
def _display_simulation_result_rich(result, show_parallel: bool):
    """Display with parallel layer emphasis."""
    
    console.print(Panel("[green]DAG Analysis Complete[/green]", title="Success"))
    
    # Show forward execution layers
    console.print("\n[bold]Forward Execution Layers:[/bold]")
    for layer in result.forward_layers:
        console.print(f"\n[cyan]Layer {layer.layer_number}:[/cyan]")
        for step in layer.steps:
            console.print(f"  • {step}")
        if layer.dependencies:
            console.print(f"  [dim]Depends on: {', '.join(layer.dependencies)}[/dim]")
    
    # Show parallelization analysis
    console.print("\n[bold]Parallelization Analysis:[/bold]")
    table = Table()
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Total steps", str(result.total_steps))
    table.add_row("Sequential layers", str(result.total_layers))
    table.add_row("Max parallel width", str(result.max_parallel_width))
    table.add_row("Parallelization ratio", f"{result.parallelization_ratio:.2f}")
    table.add_row("Critical path length", str(len(result.critical_path)))
    
    console.print(table)
    
    # Show critical path
    console.print("\n[bold]Critical Path:[/bold]")
    console.print(" → ".join(result.critical_path))
    
    # Optional: Show duration estimates if metadata available
    if result.has_duration_metadata:
        console.print("\n[bold]Duration Estimates:[/bold]")
        console.print(f"  Sequential: {result.estimated_sequential_ms}ms")
        console.print(f"  Parallel: {result.estimated_parallel_ms}ms")
    else:
        console.print("\n[dim]💡 Tip: Add duration metadata for time estimates:[/dim]")
        console.print("[dim]   @action('step', estimated_duration_ms=100)[/dim]")
```

### Core Analysis Algorithm

```python
def _analyze_parallel_layers(self, dag: dict[str, list[str]]) -> tuple[list[ParallelLayerInfo], list[str]]:
    """Analyze DAG for parallelizable execution layers.
    
    Returns:
        - List of forward execution layers
        - Critical path (longest dependency chain)
    """
    # Calculate layer depth for each node
    layers = self._calculate_layers(dag)
    
    # Group steps by layer
    max_layer = max(layers.values()) if layers else 0
    layer_groups = [[] for _ in range(max_layer + 1)]
    
    for step, layer in layers.items():
        layer_groups[layer].append(step)
    
    # Build layer info with dependencies
    forward_layers = []
    for layer_num, steps in enumerate(layer_groups):
        if not steps:
            continue
            
        # Find dependencies (steps from previous layers)
        deps = set()
        for step in steps:
            deps.update(dag.get(step, []))
        
        forward_layers.append(ParallelLayerInfo(
            layer_number=layer_num,
            steps=sorted(steps),
            dependencies=deps
        ))
    
    # Find critical path (longest chain)
    critical_path = self._find_critical_path(dag, layers)
    
    return forward_layers, critical_path


def _find_critical_path(self, dag: dict[str, list[str]], layers: dict[str, int]) -> list[str]:
    """Find the longest dependency chain (critical path)."""
    # Start from deepest layer
    max_layer = max(layers.values()) if layers else 0
    deepest_nodes = [node for node, layer in layers.items() if layer == max_layer]
    
    # Trace back dependencies to find longest path
    longest_path = []
    
    for start_node in deepest_nodes:
        path = self._trace_path(start_node, dag, [])
        if len(path) > len(longest_path):
            longest_path = path
    
    return list(reversed(longest_path))


def _trace_path(self, node: str, dag: dict[str, list[str]], visited: list[str]) -> list[str]:
    """Recursively trace dependency path."""
    path = [node]
    
    deps = dag.get(node, [])
    if deps:
        # Follow the longest dependency branch
        longest_branch = []
        for dep in deps:
            if dep not in visited:
                branch = self._trace_path(dep, dag, visited + [node])
                if len(branch) > len(longest_branch):
                    longest_branch = branch
        path.extend(longest_branch)
    
    return path
```

## Benefits

### 1. No Metadata Required

Users can immediately analyze sagas without manual annotation:

```bash
$ sagaz dry-run analyze my_saga.py

Forward Execution Layers:
  Layer 0: create_order
  Layer 1: reserve_inventory, check_fraud (2 parallel)
  Layer 2: charge_payment
  
Parallelization: 2 parallel opportunities (layer 1)
```

### 2. Clear Parallelization Visibility

Users can see at a glance which steps can run in parallel:
- Helps optimize saga design
- Identifies bottlenecks (layers with 1 step)
- Shows where to add parallelism

### 3. Realistic Upper Bounds

Instead of fake durations, show **layer-based complexity**:
- "5 layers required" is more meaningful than "0.55s"
- Parallelization ratio shows optimization potential
- Critical path identifies longest chain

### 4. Compensation Analysis

Show backward rollback structure:
- Which steps roll back first
- Parallel compensation opportunities
- Compensation dependencies

## Alternatives Considered

### 1. Keep Current Metadata-Based Approach

**Rejected**: Creates burden on users, estimates are unrealistic

### 2. Dynamic Profiling

Run sagas once to collect real timing data.

**Rejected**: Requires side effects, defeats purpose of dry-run

### 3. Machine Learning Duration Prediction

Use ML to predict step durations based on code analysis.

**Rejected**: Too complex, adds dependencies, unreliable

## Implementation Plan

1. ✅ Create ADR-030
2. ✅ Enhance `DryRunEngine._simulate()` with layer analysis
3. ✅ Add `_analyze_parallel_layers()` and `_find_critical_path()`  
4. ✅ Update CLI output to emphasize layers and parallelization
5. ✅ Add tests for layer analysis (parallel groups, critical path) - 8 new tests, 37 total
6. ✅ Update ADR-019 documentation
7. ⏳ Remove hardcoded metadata from examples (optional cleanup)

## Success Metrics

- Users can analyze sagas without adding metadata
- Parallel execution opportunities are clearly visible
- No more fake duration estimates
- Users understand critical path and bottlenecks

## References

- **ADR-019**: Current dry-run implementation
- **ADR-015**: DAG dependency model
- **Graph Theory**: Critical path method (CPM), topological layering
