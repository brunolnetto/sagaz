# Every tool runs inside the project's uv environment, as in CI. Override with RUN=
# (empty) to use whatever is on PATH, e.g. an activated virtualenv.
RUN ?= uv run

PYTHON := $(RUN) python
PYTEST := $(RUN) pytest
RUFF := $(RUN) ruff
MYPY := $(RUN) mypy
RADON := $(RUN) radon

.DEFAULT_GOAL := help
.PHONY: help test coverage lint lint-fix format format-check typecheck complexity \
	quality-gate security check ci install dev clean clean-containers version build \
	benchmark info

CYAN := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m

# Arguments
TYPE ?= fast
FORMAT ?= terminal
MODE ?=
MISSING ?= no
PARALLEL ?= yes
# xdist workers. Each worker may start its own test containers, so keep this small.
WORKERS ?= 2

ifeq ($(PARALLEL),yes)
XDIST := -n $(WORKERS)
else
XDIST :=
endif

help: ## Show this help message
	@echo "$(CYAN)Sagaz Development Makefile$(RESET)"
	@echo ""
	@echo "$(GREEN)Targets:$(RESET)"
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-17s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Arguments:$(RESET)"
	@echo "  TYPE=<type>       test: fast|all|integration|performance|watch (default: fast)"
	@echo "  FORMAT=<format>   coverage: terminal|html|xml (default: terminal)"
	@echo "  MISSING=<yes|no>  coverage: show missing lines (default: no)"
	@echo "  MODE=<mode>       complexity: summary|full|json|mi|raw; clean: all"
	@echo "  PARALLEL=<yes|no> test/coverage: run with pytest-xdist (default: yes)"
	@echo "  WORKERS=<n>       xdist workers when PARALLEL=yes (default: 2)"
	@echo "  RUN=<prefix>      command prefix for every tool (default: uv run)"
	@echo ""
	@echo "$(YELLOW)Examples:$(RESET)"
	@echo "  make dev                     # uv sync --group dev"
	@echo "  make test                    # fast tests"
	@echo "  make test TYPE=all           # every test, containers included"
	@echo "  make coverage FORMAT=html    # HTML report in htmlcov/"
	@echo "  make check                   # the gates CI enforces, then tests"
	@echo "  make build                   # sdist + wheel, verified"

# ============================================================================
# Testing
# ============================================================================

test: ## Run tests (TYPE=fast|all|integration|performance|watch, PARALLEL, WORKERS)
	@echo "$(GREEN)Running tests (TYPE=$(TYPE), PARALLEL=$(PARALLEL))...$(RESET)"
ifeq ($(TYPE),all)
	$(PYTEST) $(XDIST) -v -m "" --parallel-containers
else ifeq ($(TYPE),integration)
	$(PYTEST) $(XDIST) -v -m integration --parallel-containers
else ifeq ($(TYPE),performance)
	$(PYTEST) -v -m performance
else ifeq ($(TYPE),watch)
	$(RUN) ptw -- -v
else
	$(PYTEST) $(XDIST) -v
endif

benchmark: ## Run performance benchmarks (same as make test TYPE=performance)
	@$(MAKE) --no-print-directory test TYPE=performance

# ============================================================================
# Coverage
# ============================================================================

COV_TERM := $(if $(filter yes,$(MISSING)),--cov-report=term-missing,--cov-report=term)

coverage: ## Run tests with coverage (FORMAT=terminal|html|xml, MISSING=yes, PARALLEL)
	@echo "$(GREEN)Running tests with coverage (FORMAT=$(FORMAT), PARALLEL=$(PARALLEL))...$(RESET)"
ifeq ($(FORMAT),html)
	$(PYTEST) $(XDIST) --cov=sagaz --cov-report=html $(if $(filter yes,$(MISSING)),--cov-report=term-missing,)
	@echo "$(GREEN)✓ HTML report at htmlcov/index.html$(RESET)"
else ifeq ($(FORMAT),xml)
	$(PYTEST) $(XDIST) --cov=sagaz --cov-report=xml
	@echo "$(GREEN)✓ XML report at coverage.xml$(RESET)"
else
	$(PYTEST) $(XDIST) --cov=sagaz $(COV_TERM)
endif

# ============================================================================
# Code quality (the same commands CI runs)
# ============================================================================

lint: ## Lint with ruff; check that suppression comments say what and why
	$(RUFF) check sagaz/ tests/
	$(PYTHON) scripts/check_suppressions.py

lint-fix: ## Lint with ruff and apply its fixes
	$(RUFF) check --fix sagaz/ tests/

format: ## Format code with ruff
	$(RUFF) format sagaz/ tests/

format-check: ## Check formatting without changing files
	$(RUFF) format --check sagaz/ tests/

typecheck: ## Type-check with mypy; check the typing budget (it can only go down)
	$(MYPY) sagaz/ --ignore-missing-imports
	$(PYTHON) scripts/check_typing_budget.py

quality-gate: ## Structural gate (codebase-stats): CC <= 10, modules <= 400 lines, MI >= 20
	$(RUN) codebase-stats --root sagaz --format summary

security: ## Security scan with bandit
	$(RUN) bandit -r sagaz/ -c pyproject.toml -ll

complexity: ## Show radon metrics (MODE=summary|full|json|mi|raw); informational
ifeq ($(MODE),full)
	$(RADON) cc sagaz/ -a -s
else ifeq ($(MODE),json)
	$(RADON) cc sagaz/ -j > complexity-report.json
	@echo "$(GREEN)✓ Saved to complexity-report.json$(RESET)"
else ifeq ($(MODE),mi)
	$(RADON) mi sagaz/ -s -n B
	@echo "$(YELLOW)Legend: A=100-20 (highly maintainable), B=19-10 (maintainable), C=9-0 (difficult)$(RESET)"
else ifeq ($(MODE),raw)
	$(RADON) raw sagaz/ -s
else
	$(RADON) cc sagaz/ -a -s -n C
	@echo "$(YELLOW)Legend: A=1-5, B=6-10, C=11-20, D=21-50, F=50+. Full report: make complexity MODE=full$(RESET)"
endif

check: lint format-check typecheck quality-gate test ## Run the CI gates, then the fast tests
	@echo "$(GREEN)✓ All checks passed$(RESET)"

ci: lint format-check typecheck quality-gate ## Run the CI gates, then coverage as XML
	@$(MAKE) --no-print-directory coverage FORMAT=xml
	@echo "$(GREEN)✓ CI checks complete$(RESET)"

# ============================================================================
# Setup
# ============================================================================

install: ## Install the package and its runtime dependencies (uv sync)
	uv sync

dev: ## Install the dev group: tests, linters, type checker, tools
	uv sync --group dev
	@echo "$(GREEN)✓ Development environment ready. Next: make check$(RESET)"

# ============================================================================
# Cleanup
# ============================================================================

clean-containers: ## Remove leftover testcontainers containers (only those labeled by testcontainers)
	@ids=$$(docker ps -aq --filter label=org.testcontainers.lang=python); \
	if [ -n "$$ids" ]; then docker rm -f $$ids; else echo "No test containers found."; fi

clean: ## Remove generated files (MODE=all also removes .venv)
	rm -rf .coverage htmlcov/ coverage.xml .pytest_cache/ complexity-report.json
	find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .ruff_cache/ .mypy_cache/
ifeq ($(MODE),all)
	rm -rf .venv/
endif

# ============================================================================
# Build & release
# ============================================================================

version: ## Show the current version
	@grep '^version' pyproject.toml | cut -d'"' -f2

build: ## Build the sdist and wheel into dist/ and verify them (scripts/check_dist.py)
	rm -rf dist/
	uv build
	$(PYTHON) scripts/check_dist.py dist
	@echo "$(GREEN)✓ Build complete. Publish with: uv publish$(RESET)"

info: ## Show versions of the project and its tools
	@echo "$(GREEN)Sagaz:$(RESET)   $$(grep '^version' pyproject.toml | cut -d'"' -f2)"
	@echo "$(GREEN)uv:$(RESET)      $$(uv --version)"
	@echo "$(GREEN)Python:$(RESET)  $$($(PYTHON) --version 2>&1)"
	@echo "$(GREEN)Pytest:$(RESET)  $$($(PYTEST) --version 2>&1 | head -1)"
	@echo "$(GREEN)Ruff:$(RESET)    $$($(RUFF) --version 2>&1)"
	@echo "$(GREEN)Mypy:$(RESET)    $$($(MYPY) --version 2>&1)"
