# Makefile Quick Reference

The Makefile wraps the commands CI runs. Every tool runs through `uv run`, inside the
project environment, so nothing has to be activated or installed globally. To use the
tools on your `PATH` instead (an activated virtualenv, say), pass an empty prefix:
`make lint RUN=`.

`make help` lists every target and argument.

## Quick start

```bash
make dev      # uv sync --group dev: tests, linters, mypy, tools
make check    # the CI gates, then the fast tests
```

## Testing

| Command | What it runs |
|---|---|
| `make test` | Fast tests (no containers), in parallel |
| `make test TYPE=all` | Every test, test containers included |
| `make test TYPE=integration` | Integration tests only |
| `make test TYPE=performance` | Performance tests (also `make benchmark`) |
| `make test TYPE=watch` | Re-run tests on file changes (pytest-watch) |
| `make test PARALLEL=no` | Without pytest-xdist |
| `make test WORKERS=4` | With 4 xdist workers (default 2; each may start its own containers) |

## Coverage

| Command | Report |
|---|---|
| `make coverage` | Terminal |
| `make coverage MISSING=yes` | Terminal, with missing lines |
| `make coverage FORMAT=html` | `htmlcov/index.html` |
| `make coverage FORMAT=xml` | `coverage.xml` |
| `make coverage FORMAT=json` | `coverage.json` (read by `make quality-gate`) and `coverage.xml` |

CI fails below 95% coverage (`--cov-fail-under=95`).

## Code quality

These run the same commands as the CI gates.

| Command | Tool |
|---|---|
| `make lint` | `ruff check sagaz/ tests/`, then `scripts/check_suppressions.py`: each `# type: ignore`, `# noqa`, `# nosec` and `# pragma: no cover` must name what it suppresses and why |
| `make lint-fix` | `ruff check --fix` |
| `make format` | `ruff format` (rewrites files) |
| `make format-check` | `ruff format --check` (changes nothing) |
| `make typecheck` | `mypy sagaz/ --ignore-missing-imports` (an unused `# type: ignore` is an error), then `scripts/check_typing_budget.py`: the counts of bare `Any`, missing annotations and `# type: ignore` must match the budget in `pyproject.toml`, which can only go down |
| `make quality-gate` | `codebase-stats`: CC ≤ 10 per function, modules ≤ 400 lines, MI ≥ 20. When `coverage.json` exists, it also reports coverage, lists the files to cover first, and requires 95% |
| `make security` | `bandit -ll` (medium severity and up; informational in CI) |
| `make complexity` | radon metrics, informational: `MODE=summary` (C and worse), `full`, `json`, `mi`, `raw` |

## Combined checks

| Command | Runs |
|---|---|
| `make check` | lint, format-check, typecheck, quality-gate, then `make test` |
| `make ci` | lint, format-check, typecheck, then `make coverage FORMAT=json` and `make quality-gate` with that coverage |

## Setup and cleanup

| Command | Does |
|---|---|
| `make install` | `uv sync`: the package and its runtime dependencies |
| `make dev` | `uv sync --group dev` |
| `make clean` | Removes caches, coverage output, `build/` and `dist/` |
| `make clean MODE=all` | Also removes `.venv/` |
| `make clean-containers` | Removes leftover testcontainers containers |

## Build and release

| Command | Does |
|---|---|
| `make version` | Prints the version in `pyproject.toml` |
| `make build` | `uv build` into a fresh `dist/`, then `scripts/check_dist.py dist` |
| `make info` | Versions of sagaz, uv, Python and the tools |

To publish a release: check out its tag, run `make build`, then `uv publish`.

## Before opening a pull request

```bash
make format   # apply formatting
make check    # gates + fast tests
```
