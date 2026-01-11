# ADR-032: CLI Command Organization by Progressive Risk

## Status
Accepted

## Context

The Sagaz CLI has grown to include multiple commands with varying levels of risk and impact:
- Read-only analysis commands (validate, simulate)
- Infrastructure management (dev, stop, status)
- State-modifying commands (replay)

Users need clear guidance on command safety and appropriate usage order. A logical organization helps users:
1. Discover safe commands first
2. Understand command risk before execution
3. Follow a natural workflow progression

## Decision

Organize CLI commands by **progressive risk level**:

### Risk Levels

1. **Analysis (Zero Risk)** - Read-only, no side effects
   - `validate` - Configuration validation
   - `simulate` - DAG analysis and simulation

2. **Project Management (Low Risk)** - Scaffolding only
   - `init` - Deployment configuration
   - `project` - Project templates
   - `examples` - Example exploration

3. **Development Operations (Medium Risk)** - Infrastructure changes
   - `dev` - Start services
   - `status` - Health checks
   - `stop` - Stop services
   - `logs` - View logs
   - `monitor` - Dashboards

4. **Performance Testing (Medium-High Risk)** - Resource intensive
   - `benchmark` - Performance tests

5. **State Modification (Highest Risk)** - Direct saga state changes
   - `replay` - Replay and modify saga execution

### Implementation

```python
# Command registration order reflects progressive risk
cli.add_command(validate)      # 1. Analysis
cli.add_command(simulate)      # 1. Analysis
cli.add_command(project_cli)   # 2. Project
cli.add_command(examples_cli)  # 2. Project
# Infrastructure commands via @cli.command()
cli.add_command(replay)        # 5. State modification
```

### Documentation

- Main CLI docstring groups commands by risk level
- Each command's help text indicates its risk category
- Architecture docs explain rationale and workflow

## Consequences

### Positive

- **Safety**: Users encounter safe commands first
- **Learning curve**: Natural progression from analysis to modification
- **Discoverability**: Clear mental model for command organization
- **Documentation**: Risk levels serve as built-in documentation

### Negative

- **Alphabetical conflict**: Click sorts commands alphabetically in `--help` output, which may not match risk order
- **Subjective**: Risk assessment may be subjective (e.g., is `benchmark` more risky than `dev`?)

### Mitigations

- Document risk ordering in main CLI docstring
- Use inline comments in code to explain organization
- Architecture documentation provides full rationale
- Risk levels are suggestions, not enforcements

## Alternatives Considered

### 1. Alphabetical Only
- **Rejected**: No semantic grouping, users may encounter risky commands first

### 2. By Functionality
- **Rejected**: Doesn't convey risk/safety information

### 3. By Usage Frequency
- **Rejected**: Varies by user; doesn't indicate risk

### 4. Sub-commands/Groups
```bash
sagaz analysis validate
sagaz ops dev
sagaz danger replay
```
- **Rejected**: More verbose, breaks existing workflows

## References

- Related: ADR-019 (Dry-Run Validation)
- CLI Design: [Click Documentation](https://click.palletsprojects.com/)
- Risk-based UX: Progressive disclosure pattern

## Decision Date
2026-01-11

## Notes

While Click's help output sorts commands alphabetically, the code organization and documentation clearly reflect progressive risk. This provides:
1. Self-documenting code for maintainers
2. Clear documentation for users
3. Logical grouping for future CLI evolution
