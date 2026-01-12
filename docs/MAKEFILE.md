# Makefile Quick Reference

**Location**: `Makefile` in project root

All shortcuts for testing, coverage, linting, and complexity analysis.

---

## Quick Start

```bash
make help          # Show all available commands
make test          # Run fast tests
make coverage      # Run tests with coverage
make complexity    # Check cyclomatic complexity
make check         # Run all checks (lint + complexity + test)
```

---

## Testing

| Command | Description |
|---------|-------------|
| `make test` | Run fast tests (excludes integration/performance) |
| `make test-all` | Run ALL tests including integration |
| `make test-parallel` | Run tests in parallel (faster) |
| `make test-integration` | Run only integration tests |
| `make test-performance` | Run performance benchmarks |
| `make test-watch` | Watch mode (re-run on file changes) |

---

## Coverage

| Command | Description |
|---------|-------------|
| `make coverage` | Run tests with coverage report (terminal) |
| `make coverage-html` | Generate HTML coverage report |
| `make coverage-xml` | Generate XML report (for CI) |
| `make coverage-report` | Show last coverage report |
| `make coverage-clean` | Clean coverage data |

**Open HTML report:**
```bash
make coverage-html
open htmlcov/index.html    # macOS
xdg-open htmlcov/index.html # Linux
```

---

## Code Quality

| Command | Description |
|---------|-------------|
| `make lint` | Run ruff linter |
| `make lint-fix` | Auto-fix linting issues |
| `make format` | Format code with ruff |
| `make format-check` | Check if code is formatted |
| `make security` | Run security checks (bandit) |

---

## Complexity Analysis

| Command | Description |
|---------|-------------|
| `make complexity` | Show cyclomatic complexity (Grade C+) |
| `make complexity-full` | Detailed complexity for all modules |
| `make complexity-json` | Output as JSON file |
| `make maintainability` | Show maintainability index |
| `make raw-metrics` | Show LOC, LLOC, comments |

**Complexity Grades:**
- **A** (1-5): Simple
- **B** (6-10): Easy
- **C** (11-20): Moderate
- **D** (21-50): Complex
- **F** (50+): Very complex

---

## Combined Checks

| Command | Description |
|---------|-------------|
| `make check` | Run lint + complexity + test |
| `make check-ci` | Run all CI checks |
| `make check-quality` | Check complexity + maintainability |

---

## Installation

| Command | Description |
|---------|-------------|
| `make install` | Install package in dev mode |
| `make install-dev` | Install with dev dependencies |
| `make install-tools` | Install ruff, radon, bandit |
| `make dev` | Setup complete dev environment |

---

## Cleanup

| Command | Description |
|---------|-------------|
| `make clean` | Clean generated files (__pycache__, .pyc, etc) |
| `make coverage-clean` | Clean coverage data only |
| `make clean-all` | Clean everything including venv |

---

## Build & Release

| Command | Description |
|---------|-------------|
| `make version` | Show current version |
| `make build` | Build distribution packages |
| `make benchmark` | Run performance benchmarks |

---

## Development Workflow

### First Time Setup

```bash
# Clone repo
git clone https://github.com/you/sagaz.git
cd sagaz

# Setup development environment
make dev

# Run checks
make check
```

### Daily Development

```bash
# Run tests while coding
make test-watch

# Before committing
make check

# Check complexity of your changes
make complexity

# View coverage
make coverage-html
```

### Pre-Commit Checklist

```bash
make format       # Format code
make lint         # Check linting
make complexity   # Check complexity
make test         # Run tests
make coverage     # Check coverage
```

Or just:
```bash
make check        # Runs lint + complexity + test
```

---

## CI/CD Integration

```yaml
# .github/workflows/test.yml
- name: Run checks
  run: make check-ci
```

This runs:
- Linting (ruff)
- Format check
- Tests with XML coverage output

---

## Examples

### Check Complexity of Specific File

```bash
radon cc sagaz/core/orchestrator.py -s
```

### Run Tests with Coverage for Specific Module

```bash
pytest tests/unit/test_saga.py --cov=sagaz.saga --cov-report=html
```

### Find High Complexity Functions

```bash
make complexity-full | grep -E "D|F"
```

### Watch Tests for Specific File

```bash
ptw -- tests/unit/test_saga.py -v
```

---

## Troubleshooting

### "ruff: command not found"

```bash
make install-tools
# or
pip install ruff
```

### "ptw: command not found" (for test-watch)

```bash
pip install pytest-watch
```

### "bandit: command not found"

```bash
pip install bandit
```

---

## Tips

1. **Use `make` without arguments** - defaults to `make help`
2. **Tab completion** - type `make ` and press TAB to see options
3. **Parallel tests** - use `make test-parallel` for faster runs
4. **Watch mode** - use `make watch` while coding
5. **HTML coverage** - easier to navigate than terminal output

---

## Color Legend

- 🟢 **Green** - Success messages
- 🔵 **Cyan** - Informational messages
- 🟡 **Yellow** - Warnings or hints
- 🔴 **Red** - Errors

---

**See also**: `make help` for full command list
