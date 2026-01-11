# CLI Refactoring: Project-Level Validate and Simulate

## Summary

Refactored the `validate` and `simulate` CLI commands to operate at the project level instead of on individual files. This aligns with the project-oriented approach of Sagaz and makes the commands more intuitive and powerful.

## Changes Made

### 1. Command Interface Changes

**Before:**
```bash
# Had to specify file path for each saga
sagaz validate examples/order_saga.py
sagaz simulate examples/order_saga.py --saga-class OrderSaga
```

**After:**
```bash
# Validates/simulates all sagas in project automatically
sagaz validate
sagaz simulate

# Or target a specific saga by name
sagaz validate --saga OrderSaga
sagaz simulate --saga PaymentSaga
```

### 2. Project Discovery

Commands now:
- Automatically discover all sagas from paths defined in `sagaz.yaml`
- Support filtering by saga name with `--saga` option
- Process multiple sagas in a single command execution
- Show aggregate results for all sagas

### 3. Updated Help Text

```
Commands by Progressive Risk:

  Analysis (Read-only):
    validate         Validate all project sagas
    simulate         Analyze execution DAG for all sagas

  Project Management:
    init             Initialize deployment environment
    check            Validate project structure
    list             List discovered sagas
    examples         Explore examples
  ...
```

### 4. Enhanced Output

#### Validate Output
- Shows validation results for each saga found in project
- Clear success/failure indicators
- Detailed validation checks per saga
- Supports both rich (colored) and plain text output

#### Simulate Output
- Displays parallelization analysis for all sagas
- Shows forward execution layers (parallelizable groups)
- Displays critical path for each saga
- Shows compensation layers when available
- Max parallel width and parallelization ratio metrics

## Usage Examples

### Validate All Sagas
```bash
cd ~/my-sagaz-project
sagaz validate
```

Output:
```
╭───────────────────── Success ─────────────────────╮
│ ✓ All sagas validated successfully                │
╰───────────────────────────────────────────────────╯

Saga: OrderSaga
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Check                 ┃ Result           ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ Steps Defined         │ ✓ 5 steps        │
│ Has Dependencies      │ Yes              │
│ Has Compensation      │ Yes              │
│ Circular Dependencies │ None             │
└───────────────────────┴──────────────────┘

Saga: PaymentSaga
...
```

### Validate Specific Saga
```bash
sagaz validate --saga OrderSaga
```

### Simulate with Parallelization Analysis
```bash
sagaz simulate
```

Output shows:
- Forward execution layers with parallelizable steps
- Critical path (longest dependency chain)
- Parallelization metrics (ratio, max width)
- Compensation layers (rollback order)

### Simulate Specific Saga
```bash
sagaz simulate --saga PaymentSaga
```

## Implementation Details

### Files Modified

1. **sagaz/cli/dry_run.py**
   - Refactored `validate_cmd()` to work with project discovery
   - Refactored `simulate_cmd()` to work with project discovery
   - Added `_discover_project_sagas()` helper function
   - Added `_discover_sagas_in_paths()` for saga discovery
   - Added project-level display functions:
     - `_display_project_validation_results_rich()`
     - `_display_project_validation_results_plain()`
     - `_display_project_simulation_results_rich()`
     - `_display_project_simulation_results_plain()`

2. **sagaz/cli/app.py**
   - Updated main CLI help text to reflect project-level operation

3. **tests/unit/cli/test_cli_validate_simulate.py** (new)
   - Comprehensive test suite for project-level commands
   - Tests for multiple sagas, filtering, error handling
   - Tests for parallel execution analysis
   - Tests for edge cases (no sagas, invalid sagas, etc.)

### Backward Compatibility

The old `_load_saga()` function is retained for potential future use or backward compatibility needs, but the main CLI commands now use project discovery.

## Benefits

1. **Consistency**: Aligns with other project-level commands (`check`, `list`)
2. **Efficiency**: Validate/simulate all sagas with one command
3. **Simplicity**: No need to specify file paths
4. **Scalability**: Easily handles projects with many sagas
5. **Better UX**: Clear, organized output for multiple sagas

## Testing

All new functionality is covered by comprehensive tests:
- 16 test cases covering all scenarios
- Tests for success and error paths
- Tests for filtering and options
- Tests for edge cases

Run tests:
```bash
pytest tests/unit/cli/test_cli_validate_simulate.py -v
```

## Next Steps

Future enhancements could include:
- Output formats (JSON, YAML) for CI/CD integration
- Filtering by saga attributes (tags, categories)
- Parallel execution of validation/simulation
- Progress bars for large projects
- Export of simulation results for visualization
