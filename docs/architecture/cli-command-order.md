# CLI Command Organization (Progressive Risk)

## Overview

CLI commands are organized by progressive risk level to guide users from safe exploratory operations to potentially dangerous state-modifying operations.

## Command Categories

### 1. Analysis/Validation (Read-only, Zero Risk)
- `validate` - Validates saga configuration without execution
- `simulate` - Analyzes execution DAG and shows parallelization

**Risk Level:** None - Read-only operations that never modify state.

### 2. Project Management (Low Risk - Scaffolding)
- `init` - Initialize deployment configurations (scaffolding only)
- `project` - Project scaffolding commands
- `examples` - Browse and run example sagas

**Risk Level:** Low - Creates files but doesn't modify existing saga state.

### 3. Development Operations (Medium Risk)
- `dev` - Start local Docker environment
- `status` - Check service health  
- `stop` - Stop local services
- `logs` - View service/saga logs
- `monitor` - Open Grafana dashboard

**Risk Level:** Medium - Manages local infrastructure but doesn't directly modify saga execution state.

### 4. Performance Testing (Medium-High Risk)
- `benchmark` - Run performance tests

**Risk Level:** Medium-High - Resource intensive, may stress systems and create test data.

### 5. State Modification (Highest Risk)
- `replay` - Replay sagas, rerun compensations, modify execution state

**Risk Level:** Highest - Directly modifies saga execution state and can trigger compensations.

## Rationale

Progressive risk ordering provides several benefits:

1. **Natural Learning Curve**: Users naturally progress from analysis → setup → operations → modification
2. **Safety First**: Read-only commands come first, preventing accidental state changes
3. **Discoverability**: Users explore safe commands before discovering risky ones
4. **Mental Model**: Reinforces that validation/simulation should happen before modification

## Implementation

Commands are added to the CLI group in progressive risk order:

```python
# 1. Analysis (Zero risk)
cli.add_command(validate)
cli.add_command(simulate)

# 2. Project (Low risk)
cli.add_command(project_cli)
cli.add_command(examples_cli)

# 3-5. Operations, Testing, Replay (Medium-High risk)
# Registered via @cli.command() decorators
```

Note: Click sorts commands alphabetically in help output, but the logical grouping in code and documentation reflects progressive risk.

## References

- ADR-019: Dry-Run Validation and Simulation
- ADR-032: CLI Command Organization
