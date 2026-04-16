# Test Suite Organization

This document describes the reorganized test suite structure that now mirrors the source code organization.

## Overview

The test suite is organized into two main categories:
- **Unit Tests** (`tests/unit/`) - Testing individual components in isolation
- **Integration Tests** (`tests/integration/`) - Testing component interactions and full workflows

## Unit Tests Structure

### `tests/unit/` Root
- **Shared fixtures and configuration**
  - `conftest.py` - Shared pytest fixtures and configuration
  - `test_orchestrator.py` - Cross-module orchestration tests
  - `__init__.py` - Package initialization

### `tests/unit/core/` - Core Saga Engine
Mirrors `sagaz/core/` module structure:

```
unit/core/
├── compliance/
│   └── test_compliance.py      # Saga compliance and rules checking
├── context/
│   ├── test_context.py          # SagaContext functionality
│   ├── test_context_s3.py       # S3-backed context storage
│   ├── test_context_streaming.py # Event streaming context
│   └── test_context_validation.py # Context validation rules
├── env/
│   └── (placeholder)
├── exceptions/
│   └── test_exceptions.py       # Custom exception hierarchy
├── execution/
│   └── test_graph.py            # Execution graph and DAG logic
├── outbox/
│   ├── test_outbox.py           # Outbox pattern core functionality
│   ├── test_outbox_brokers.py   # Broker integration
│   ├── test_redis_broker.py     # Redis broker specific
│   └── ...
├── replay/
│   ├── test_replay.py           # Saga replay and recovery
│   └── test_snapshot*.py        # Snapshot storage and retrieval
├── storage/
│   ├── test_storage.py          # Storage base interface
│   ├── test_storage_interfaces.py # Storage protocol definitions
│   ├── backends/
│   │   ├── test_storage_memory.py      # In-memory storage
│   │   ├── test_storage_redis.py       # Redis storage backend
│   │   ├── test_storage_postgresql.py  # PostgreSQL backend
│   │   ├── test_storage_s3.py          # S3 backend
│   │   └── test_storage_sqlite.py      # SQLite backend
│   ├── transfer/
│   │   └── test_storage_transfer.py    # Storage migration utilities
│   └── test_storage_manager.py   # Storage configuration and selection
├── strategies/
│   └── test_strategies.py       # Parallel execution strategies
├── triggers/
│   └── test_triggers.py         # Step trigger conditions
│
├── test_core.py                 # Main saga engine tests
├── test_decorators.py           # @saga, @step decorators
├── test_hooks.py                # Lifecycle hook system
├── test_listeners.py            # Event listener system
├── test_state_machine.py        # Saga state transitions
├── test_mermaid.py              # Mermaid diagram generation
├── test_edge_cases.py           # Edge case scenarios
├── test_replay.py               # Replay mechanisms
├── test_saga_mixins.py          # Saga mixin classes
├── test_pivot.py                # Pivot/point-of-no-return semantics
├── test_time_travel.py          # Time-travel/replay features
├── test_config*.py              # Configuration system
├── test_import_fallbacks.py     # Backward compatibility imports
└── test_idempotency_enforcement.py # Idempotency verification
```

### `tests/unit/cli/` - Command-Line Interface
Mirrors `sagaz/cli/` module:

```
unit/cli/
├── test_init_handlers.py         # Project initialization CLI
├── test_setup_handlers.py        # Setup command handlers  
├── test_examples.py              # Example generation and validation
├── test_project.py               # Project structure generation
├── test_replay.py                # CLI replay functionality
├── test_validate_simulate.py    # Validation and simulation mode
├── test_main.py                  # Main CLI entry point
└── test_dry_run.py              # Dry-run mode
```

### `tests/unit/observability/` - Monitoring & Observability
Mirrors `sagaz/observability/` module:

```
unit/observability/
├── test_monitoring.py            # Metrics and monitoring
└── test_logger.py               # Structured logging
```

### `tests/unit/integrations/` - Framework Integrations
Mirrors `sagaz/integrations/` module:

```
unit/integrations/
├── test_fastapi.py              # FastAPI integration
├── test_flask.py                # Flask integration
├── test_django.py               # Django integration
└── test_base.py                 # Integration base classes
```

### `tests/unit/deployment/` - Deployment Configuration
Placeholder for `sagaz/deployment/` testing (if applicable)

### `tests/unit/examples/` - Example Sagas
Placeholder for `sagaz/examples/` testing (if applicable)

## Integration Tests Structure

Full workflows and component interactions:

```
integration/
├── test_storage_integration.py           # Full storage lifecycle
├── test_saga_replay_integration.py       # Replay and recovery workflows
├── test_snapshot_integration.py          # Snapshot persistence workflows
├── test_broker_containers.py             # Broker container setup and testing
├── test_observability_integration.py    # Monitoring end-to-end
├── test_tracing_integration.py          # Distributed tracing
├── test_performance.py                   # Performance benchmarks
├── test_chaos_engineering.py             # Chaos/failure scenarios
├── test_api_protection.py                # API security testing
└── test_integration_coverage.py          # Coverage validation
```

## Key Benefits

1. **Direct Mapping** - Test structure mirrors source structure for easy navigation
2. **Organization** - Related tests grouped by module/functionality
3. **Scalability** - Easy to add tests in the right location as code grows
4. **Clarity** - Package structure clearly shows what's being tested
5. **Maintainability** - Clear correspondence between tests and source code

## Running Tests

```bash
# All unit tests
pytest tests/unit/

# Specific module unit tests
pytest tests/unit/core/
pytest tests/unit/cli/
pytest tests/unit/observability/

# Specific test file
pytest tests/unit/core/test_saga.py

# All integration tests
pytest tests/integration/

# Full test suite
pytest tests/
```

## Migration Notes

- Old `tests/unit/monitoring/` renamed to `tests/unit/observability/` to match source structure
- Miscellaneous root test files consolidated into their respective module directories
- `__init__.py` files added to all test directories for proper Python package structure
- All tests maintain backward compatibility - no test code changes required
