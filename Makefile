.PHONY: help test coverage lint complexity format check clean install dev docs

# Default target
.DEFAULT_GOAL := help

# Colors for output
CYAN := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m

# Project info
PYTHON := python3
PYTEST := pytest
COVERAGE := coverage
RADON := radon

# Arguments
TYPE ?= fast
FORMAT ?= terminal
MODE ?=
MISSING ?= no
PARALLEL ?= yes

help: ## Show this help message
	@echo "$(CYAN)Sagaz Development Makefile$(RESET)"
	@echo ""
	@echo "$(GREEN)Main Commands:$(RESET)"
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -v "##@" | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-15s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Arguments:$(RESET)"
	@echo "  TYPE=<type>       For test: fast|all|integration|performance|watch (default: fast)"
	@echo "  FORMAT=<format>   For coverage: terminal|html|xml (default: terminal)"
	@echo "  MISSING=<yes|no>  For coverage: show missing lines (default: no)"
	@echo "  MODE=<mode>       For complexity: summary|full|json|mi|raw (default: summary)"
	@echo "  PARALLEL=<yes|no> For test/coverage: enable parallel execution (default: yes)"
	@echo ""
	@echo "$(CYAN)Note:$(RESET) Tests run in parallel by default (pytest -n auto)"
	@echo ""
	@echo "$(YELLOW)Examples:$(RESET)"
	@echo "  make test                    # Run fast tests (parallel)"
	@echo "  make test TYPE=all           # Run all tests (parallel)"
	@echo "  make coverage                # Coverage report"
	@echo "  make coverage MISSING=yes    # Show missing lines"
	@echo "  make coverage FORMAT=html    # HTML coverage report"
	@echo "  make complexity MODE=full    # Detailed complexity"
	@echo "  make check                   # Run all checks"

# ============================================================================
# Testing
# ============================================================================

test: ## Run tests (TYPE=fast|all|integration|performance|watch, PARALLEL=yes|no)
	@echo "$(GREEN)Running tests (TYPE=$(TYPE), PARALLEL=$(PARALLEL))...$(RESET)"
ifeq ($(TYPE),all)
ifeq ($(PARALLEL),yes)
	$(PYTEST) -n auto -v -m ""
else
	$(PYTEST) -v -m ""
endif
else ifeq ($(TYPE),integration)
ifeq ($(PARALLEL),yes)
	$(PYTEST) -n auto -v -m integration
else
	$(PYTEST) -v -m integration
endif
else ifeq ($(TYPE),performance)
	$(PYTEST) -v -m performance
else ifeq ($(TYPE),watch)
	@if command -v ptw >/dev/null 2>&1; then \
		ptw -- -v; \
	else \
		echo "$(RED)Error: pytest-watch not installed. Run: pip install pytest-watch$(RESET)"; \
		exit 1; \
	fi
else
ifeq ($(PARALLEL),yes)
	$(PYTEST) -n auto -v
else
	$(PYTEST) -v
endif
endif

# ============================================================================
# Coverage
# ============================================================================

coverage: ## Run tests with coverage (FORMAT=terminal|html|xml, MISSING=yes, PARALLEL=yes|no)
	@echo "$(GREEN)Running tests with coverage (FORMAT=$(FORMAT), PARALLEL=$(PARALLEL))...$(RESET)"
ifeq ($(PARALLEL),yes)
	$(eval PYTEST_OPTS := -n auto)
else
	$(eval PYTEST_OPTS := )
endif
ifeq ($(FORMAT),html)
	@if [ "$(MISSING)" = "yes" ]; then \
		$(PYTEST) $(PYTEST_OPTS) --cov=sagaz --cov-report=html --cov-report=term-missing; \
	else \
		$(PYTEST) $(PYTEST_OPTS) --cov=sagaz --cov-report=html; \
	fi
	@echo "$(GREEN)✓ HTML report at htmlcov/index.html$(RESET)"
	@echo "$(YELLOW)Open with: open htmlcov/index.html$(RESET)"
else ifeq ($(FORMAT),xml)
	$(PYTEST) $(PYTEST_OPTS) --cov=sagaz --cov-report=xml
	@echo "$(GREEN)✓ XML report generated$(RESET)"
else
	@if [ "$(MISSING)" = "yes" ]; then \
		$(PYTEST) $(PYTEST_OPTS) --cov=sagaz --cov-report=term-missing; \
	else \
		$(PYTEST) $(PYTEST_OPTS) --cov=sagaz --cov-report=term; \
	fi
	@echo ""
	@echo "$(YELLOW)Tips:$(RESET)"
	@echo "  make coverage MISSING=yes      # Show missing lines"
	@echo "  make coverage FORMAT=html      # HTML report"
	@echo "  make coverage PARALLEL=no      # Disable parallel execution"
endif

# ============================================================================
# Code Quality
# ============================================================================

lint: ## Run linting (ruff check)
	@echo "$(GREEN)Running linter...$(RESET)"
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check sagaz/ tests/; \
	else \
		echo "$(YELLOW)Warning: ruff not installed. Install with: pip install ruff$(RESET)"; \
		exit 1; \
	fi

lint-fix: ## Auto-fix linting issues
	@echo "$(GREEN)Auto-fixing linting issues...$(RESET)"
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check --fix sagaz/ tests/; \
	else \
		echo "$(RED)Error: ruff not installed$(RESET)"; \
		exit 1; \
	fi

format: ## Format code with ruff
	@echo "$(GREEN)Formatting code...$(RESET)"
	@if command -v ruff >/dev/null 2>&1; then \
		ruff format sagaz/ tests/; \
		echo "$(GREEN)✓ Code formatted$(RESET)"; \
	else \
		echo "$(RED)Error: ruff not installed$(RESET)"; \
		exit 1; \
	fi

format-check: ## Check if code is formatted
	@echo "$(GREEN)Checking code formatting...$(RESET)"
	@if command -v ruff >/dev/null 2>&1; then \
		ruff format --check sagaz/ tests/; \
	else \
		echo "$(RED)Error: ruff not installed$(RESET)"; \
		exit 1; \
	fi

# ============================================================================
# Complexity Analysis
# ============================================================================

complexity: ## Show cyclomatic complexity (MODE=summary|full|json|mi|raw)
	@echo "$(GREEN)Complexity Analysis (MODE=$(MODE))...$(RESET)"
ifeq ($(MODE),full)
	@echo "$(CYAN)=== Full Complexity Report ===$(RESET)"
	$(RADON) cc sagaz/ -a -s
else ifeq ($(MODE),json)
	@echo "$(GREEN)Generating JSON report...$(RESET)"
	$(RADON) cc sagaz/ -j > complexity-report.json
	@echo "$(GREEN)✓ Saved to complexity-report.json$(RESET)"
else ifeq ($(MODE),mi)
	@echo "$(CYAN)=== Maintainability Index ===$(RESET)"
	@echo ""
	$(RADON) mi sagaz/ -s -n B
	@echo ""
	@echo "$(YELLOW)Legend: A=100-20 (highly maintainable), B=19-10 (maintainable), C=9-0 (difficult)$(RESET)"
else ifeq ($(MODE),raw)
	@echo "$(CYAN)=== Raw Code Metrics ===$(RESET)"
	$(RADON) raw sagaz/ -s
else
	@echo "$(CYAN)=== Cyclomatic Complexity (C+ only) ===$(RESET)"
	@echo ""
	$(RADON) cc sagaz/ -a -s -n C
	@echo ""
	@echo "$(YELLOW)Legend: A=1-5 (simple), B=6-10 (easy), C=11-20 (moderate), D=21-50 (complex), F=50+ (very complex)$(RESET)"
	@echo "$(YELLOW)For full report: make complexity MODE=full$(RESET)"
endif

# ============================================================================
# Security
# ============================================================================

security: ## Run security checks with bandit
	@echo "$(GREEN)Running security checks...$(RESET)"
	@if command -v bandit >/dev/null 2>&1; then \
		bandit -r sagaz/ -ll; \
	else \
		echo "$(YELLOW)Warning: bandit not installed. Install with: pip install bandit$(RESET)"; \
	fi

# ============================================================================
# Combined Checks
# ============================================================================

check: lint complexity test ## Run all checks (lint + complexity + test)
	@echo ""
	@echo "$(GREEN)✓ All checks passed!$(RESET)"

ci: ## Run CI checks (lint + format-check + coverage xml)
	@echo "$(GREEN)Running CI checks...$(RESET)"
	@$(MAKE) lint
	@$(MAKE) format MODE=check
	@$(MAKE) coverage FORMAT=xml
	@echo "$(GREEN)✓ CI checks complete$(RESET)"

# ============================================================================
# Installation & Setup
# ============================================================================

install: ## Install package (MODE=dev for dev dependencies, MODE=tools for dev tools)
	@echo "$(GREEN)Installing sagaz...$(RESET)"
ifeq ($(MODE),dev)
	pip install -e ".[dev,test]"
	@echo "$(GREEN)✓ Development dependencies installed$(RESET)"
else ifeq ($(MODE),tools)
	pip install ruff radon bandit pytest-watch
	@echo "$(GREEN)✓ Development tools installed$(RESET)"
else
	pip install -e .
	@echo "$(GREEN)✓ Package installed in development mode$(RESET)"
endif

dev: ## Setup complete development environment
	@echo "$(GREEN)Setting up development environment...$(RESET)"
	@$(MAKE) install MODE=dev
	@$(MAKE) install MODE=tools
	@echo ""
	@echo "$(GREEN)✓ Development environment ready!$(RESET)"
	@echo ""
	@echo "$(CYAN)Quick Start:$(RESET)"
	@echo "  make test          # Run tests"
	@echo "  make coverage      # Check coverage"
	@echo "  make complexity    # Check complexity"
	@echo "  make check         # Run all checks"

# ============================================================================
# Cleanup
# ============================================================================

clean: ## Clean generated files (MODE=all for everything including venv)
	@echo "$(YELLOW)Cleaning generated files...$(RESET)"
	rm -rf .coverage htmlcov/ coverage.xml .pytest_cache/ complexity-report.json
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .ruff_cache/
ifeq ($(MODE),all)
	@echo "$(RED)Removing virtual environment...$(RESET)"
	rm -rf .venv/
	@echo "$(GREEN)✓ Everything cleaned$(RESET)"
else
	@echo "$(GREEN)✓ Cleaned (use MODE=all to remove venv)$(RESET)"
endif

# ============================================================================
# Build & Release
# ============================================================================

version: ## Show current version
	@echo "$(CYAN)Sagaz version:$(RESET) $(shell grep '^version' pyproject.toml | cut -d'"' -f2)"

build: ## Build distribution packages
	@$(MAKE) clean
	@echo "$(GREEN)Building distribution packages...$(RESET)"
	$(PYTHON) -m build
	@echo "$(GREEN)✓ Build complete$(RESET)"

benchmark: ## Run performance benchmarks
	@echo "$(GREEN)Running benchmarks...$(RESET)"
	$(PYTEST) -v -m performance

# ============================================================================
# Info
# ============================================================================

info: ## Show project information
	@echo "$(CYAN)Sagaz Project Information$(RESET)"
	@echo ""
	@echo "$(GREEN)Version:$(RESET)       $(shell grep '^version' pyproject.toml | cut -d'"' -f2)"
	@echo "$(GREEN)Python:$(RESET)        $(shell $(PYTHON) --version)"
	@echo "$(GREEN)Pytest:$(RESET)        $(shell $(PYTEST) --version 2>&1 | head -1)"
	@echo "$(GREEN)Coverage:$(RESET)      $(shell $(COVERAGE) --version 2>&1 | head -1)"
	@echo "$(GREEN)Radon:$(RESET)         $(shell $(RADON) --version 2>&1)"
	@echo ""
	@echo "$(CYAN)Development Tools:$(RESET)"
	@if command -v ruff >/dev/null 2>&1; then \
		echo "$(GREEN)Ruff:$(RESET)          $(shell ruff --version)"; \
	else \
		echo "$(YELLOW)Ruff:$(RESET)          Not installed"; \
	fi
	@if command -v bandit >/dev/null 2>&1; then \
		echo "$(GREEN)Bandit:$(RESET)        $(shell bandit --version 2>&1 | head -1)"; \
	else \
		echo "$(YELLOW)Bandit:$(RESET)        Not installed"; \
	fi
