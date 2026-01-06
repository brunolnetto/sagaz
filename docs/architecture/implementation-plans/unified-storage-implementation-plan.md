# Unified Storage Layer - Implementation Plan

**Status:** Draft  
**Created:** 2026-01-05  
**Author:** Automated via Sagaz Development  
**Target Version:** 1.2.0  
**ADR:** [ADR-016: Unified Storage Layer](adr/adr-016-unified-storage-layer.md)

---

## Executive Summary

This document outlines the implementation plan for unifying the storage layer in Sagaz. The goal is to:

1. **Eliminate code duplication** between saga storage and outbox storage
2. **Expand storage options** with additional backends (Redis outbox, SQLite)
3. **Enable data transfer** between storage backends for migrations and hybrid deployments
4. **Maintain backward compatibility** with existing APIs

---

## Current State Analysis

### Existing Storage Structure

```
sagaz/
├── storage/                    # Saga state storage
│   ├── base.py                 # SagaStorage ABC (218 lines)
│   ├── memory.py               # InMemorySagaStorage (255 lines)
│   ├── redis.py                # RedisSagaStorage (445 lines)
│   ├── postgresql.py           # PostgreSQLSagaStorage (477 lines)
│   └── factory.py              # create_storage() factory (217 lines)
│
└── outbox/
    └── storage/                # Outbox event storage
        ├── base.py             # OutboxStorage ABC (182 lines)
        ├── memory.py           # InMemoryOutboxStorage (139 lines)
        └── postgresql.py       # PostgreSQLOutboxStorage (550 lines)
```

### Identified Issues

| Issue | Impact | Priority |
|-------|--------|----------|
| Duplicate connection pool logic | Maintenance overhead | High |
| Duplicate health check patterns | Inconsistent monitoring | Medium |
| No Redis outbox storage | Limited deployment options | High |
| No data transfer mechanism | Difficult migrations | High |
| Separate factory patterns | Confusing API | Medium |
| No SQLite for embedded use | Missing use case | Low |

### Feature Matrix (Current)

| Feature | Saga Storage | Outbox Storage |
|---------|--------------|----------------|
| Memory | ✅ | ✅ |
| PostgreSQL | ✅ | ✅ |
| Redis | ✅ | ❌ |
| SQLite | ❌ | ❌ |
| Health Check | ✅ | ❌ |
| Statistics | ✅ | ❌ |
| Cleanup | ✅ | ✅ (archive) |

---

## Target Architecture

### New Storage Structure

```
sagaz/
└── storage/
    ├── __init__.py              # Public API exports
    │
    ├── core/                     # Shared infrastructure (NEW)
    │   ├── __init__.py
    │   ├── base.py              # BaseStorage with common patterns
    │   ├── connection.py        # ConnectionManager for pools
    │   ├── serialization.py     # JSON/data serialization utilities
    │   ├── health.py            # HealthCheckMixin
    │   └── errors.py            # Unified error hierarchy
    │
    ├── backends/                 # Storage implementations (REFACTORED)
    │   ├── __init__.py
    │   ├── memory/
    │   │   ├── __init__.py
    │   │   ├── saga.py          # InMemorySagaStorage
    │   │   └── outbox.py        # InMemoryOutboxStorage
    │   │
    │   ├── postgresql/
    │   │   ├── __init__.py
    │   │   ├── connection.py    # PostgreSQL pool management
    │   │   ├── saga.py          # PostgreSQLSagaStorage
    │   │   ├── outbox.py        # PostgreSQLOutboxStorage
    │   │   └── schema.py        # SQL schema definitions
    │   │
    │   ├── redis/
    │   │   ├── __init__.py
    │   │   ├── connection.py    # Redis connection management
    │   │   ├── saga.py          # RedisSagaStorage
    │   │   └── outbox.py        # RedisOutboxStorage (NEW)
    │   │
    │   └── sqlite/               # (NEW - Phase 3)
    │       ├── __init__.py
    │       ├── saga.py
    │       └── outbox.py
    │
    ├── transfer/                 # Data transfer layer (NEW)
    │   ├── __init__.py
    │   ├── base.py              # TransferProtocol ABC
    │   ├── saga_transfer.py     # Saga state transfer
    │   ├── outbox_transfer.py   # Outbox event transfer
    │   └── migrator.py          # Version-aware migrations
    │
    ├── interfaces/               # Abstract interfaces (REFACTORED)
    │   ├── __init__.py
    │   ├── saga.py              # SagaStorage ABC
    │   └── outbox.py            # OutboxStorage ABC
    │
    ├── factory.py               # Unified create_storage() (ENHANCED)
    │
    └── compat/                   # Backward compatibility (NEW)
        ├── __init__.py
        ├── legacy_saga.py       # Old import paths
        └── legacy_outbox.py     # Old import paths
```

### Feature Matrix (Target)

| Feature | Saga Storage | Outbox Storage |
|---------|--------------|----------------|
| Memory | ✅ | ✅ |
| PostgreSQL | ✅ | ✅ |
| Redis | ✅ | ✅ (NEW) |
| SQLite | ✅ (NEW) | ✅ (NEW) |
| Health Check | ✅ | ✅ (NEW) |
| Statistics | ✅ | ✅ (NEW) |
| Cleanup | ✅ | ✅ |
| Transfer In | ✅ (NEW) | ✅ (NEW) |
| Transfer Out | ✅ (NEW) | ✅ (NEW) |

---

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)

**Goal:** Create shared infrastructure without breaking existing code.

#### Tasks

| ID | Task | Effort | Dependencies |
|----|------|--------|--------------|
| 1.1 | Create `storage/core/` directory structure | 0.5d | - |
| 1.2 | Implement `storage/core/errors.py` - unified error hierarchy | 1d | 1.1 |
| 1.3 | Implement `storage/core/serialization.py` - JSON utils | 1d | 1.1 |
| 1.4 | Implement `storage/core/health.py` - HealthCheckMixin | 1d | 1.2 |
| 1.5 | Implement `storage/core/connection.py` - ConnectionManager | 2d | 1.2 |
| 1.6 | Implement `storage/core/base.py` - BaseStorage | 1d | 1.3, 1.4, 1.5 |
| 1.7 | Add unit tests for core module | 2d | 1.6 |
| 1.8 | Documentation for core module | 0.5d | 1.7 |

**Deliverables:**
- [ ] `sagaz/storage/core/` module with full test coverage
- [ ] No changes to existing storage implementations yet

#### Core Module Design

```python
# storage/core/errors.py
class StorageError(Exception):
    """Base exception for all storage operations."""

class ConnectionError(StorageError):
    """Failed to connect to storage backend."""

class NotFoundError(StorageError):
    """Requested item not found."""

class SerializationError(StorageError):
    """Failed to serialize/deserialize data."""

class TransferError(StorageError):
    """Failed to transfer data between backends."""


# storage/core/connection.py
class ConnectionManager(ABC):
    """Abstract connection/pool manager."""
    
    @abstractmethod
    async def acquire(self) -> Any:
        """Acquire a connection from pool."""
    
    @abstractmethod
    async def release(self, conn: Any) -> None:
        """Release connection back to pool."""
    
    @abstractmethod
    async def close(self) -> None:
        """Close all connections."""
    
    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check connection health."""


# storage/core/base.py
class BaseStorage(ABC):
    """Base class for all storage implementations."""
    
    def __init__(self, connection_manager: ConnectionManager | None = None):
        self._connection_manager = connection_manager
    
    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check storage health."""
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        if self._connection_manager:
            await self._connection_manager.close()
```

---

### Phase 2: Interface Refactoring (Week 2-3)

**Goal:** Move interfaces to dedicated module, add new capabilities.

#### Tasks

| ID | Task | Effort | Dependencies |
|----|------|--------|--------------|
| 2.1 | Create `storage/interfaces/` module | 0.5d | 1.6 |
| 2.2 | Move `SagaStorage` to `interfaces/saga.py` | 1d | 2.1 |
| 2.3 | Move `OutboxStorage` to `interfaces/outbox.py` | 1d | 2.1 |
| 2.4 | Add `Transferable` protocol to interfaces | 1d | 2.2, 2.3 |
| 2.5 | Add `HealthCheckable` protocol | 0.5d | 2.1 |
| 2.6 | Create `storage/compat/` for old imports | 1d | 2.2, 2.3 |
| 2.7 | Update all existing imports (automated) | 1d | 2.6 |
| 2.8 | Add deprecation warnings for old paths | 0.5d | 2.6 |
| 2.9 | Tests for backward compatibility | 1d | 2.7 |

**Deliverables:**
- [ ] `sagaz/storage/interfaces/` with enhanced ABCs
- [ ] `sagaz/storage/compat/` for backward compatibility
- [ ] All old import paths still work with deprecation warnings

#### Interface Enhancements

```python
# storage/interfaces/saga.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class Transferable(Protocol):
    """Protocol for storages that support data transfer."""
    
    async def export_all(self) -> AsyncIterator[dict[str, Any]]:
        """Export all records as dictionaries."""
        ...
    
    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a single record."""
        ...
    
    async def count(self) -> int:
        """Get total record count."""
        ...


class SagaStorage(BaseStorage, ABC):
    """Enhanced saga storage with transfer support."""
    
    # ... existing methods ...
    
    # NEW: Transfer support
    async def export_all(self) -> AsyncIterator[dict[str, Any]]:
        """Export all saga states."""
        raise NotImplementedError("Subclass must implement for transfer support")
    
    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a saga state record."""
        raise NotImplementedError("Subclass must implement for transfer support")
```

---

### Phase 3: Backend Reorganization (Week 3-4)

**Goal:** Reorganize backends into new structure, add Redis outbox.

#### Tasks

| ID | Task | Effort | Dependencies |
|----|------|--------|--------------|
| 3.1 | Create `storage/backends/` structure | 0.5d | 2.9 |
| 3.2 | Refactor Memory backends to use core | 1d | 3.1 |
| 3.3 | Create PostgreSQL connection module | 1d | 3.1 |
| 3.4 | Refactor PostgreSQL saga storage | 2d | 3.3 |
| 3.5 | Refactor PostgreSQL outbox storage | 2d | 3.3 |
| 3.6 | Create Redis connection module | 1d | 3.1 |
| 3.7 | Refactor Redis saga storage | 1d | 3.6 |
| 3.8 | **Implement Redis outbox storage (NEW)** | 3d | 3.6 |
| 3.9 | Add export/import to all backends | 2d | 3.2-3.8 |
| 3.10 | Integration tests for all backends | 2d | 3.9 |

**Deliverables:**
- [ ] All backends in `sagaz/storage/backends/`
- [ ] **New Redis outbox storage**
- [ ] All backends support export/import
- [ ] All backends share connection management

#### Redis Outbox Storage Design

```python
# storage/backends/redis/outbox.py
class RedisOutboxStorage(OutboxStorage):
    """
    Redis-based outbox storage.
    
    Uses Redis Streams for reliable event delivery:
    - XADD for inserting events
    - XREADGROUP for claiming batches (consumer groups)
    - XACK for acknowledging processed events
    
    Schema:
        outbox:events       - Stream of pending events
        outbox:claimed:{id} - Hash of claimed event data
        outbox:dlq          - Stream of dead-letter events
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        stream_key: str = "sagaz:outbox:events",
        consumer_group: str = "sagaz-workers",
        max_stream_length: int = 100000,
        **redis_kwargs,
    ):
        ...
    
    async def insert(self, event: OutboxEvent, connection: Any = None) -> OutboxEvent:
        """Add event to Redis stream."""
        ...
    
    async def claim_batch(
        self, 
        worker_id: str, 
        batch_size: int = 100,
        older_than_seconds: float = 0.0,
    ) -> list[OutboxEvent]:
        """Claim events using XREADGROUP with consumer groups."""
        ...
```

---

### Phase 4: Transfer Layer (Week 4-5)

**Goal:** Implement data transfer between backends.

#### Tasks

| ID | Task | Effort | Dependencies |
|----|------|--------|--------------|
| 4.1 | Create `storage/transfer/` module | 0.5d | 3.10 |
| 4.2 | Implement `TransferProtocol` ABC | 1d | 4.1 |
| 4.3 | Implement `SagaTransfer` | 2d | 4.2 |
| 4.4 | Implement `OutboxTransfer` | 2d | 4.2 |
| 4.5 | Implement `StorageMigrator` | 2d | 4.3, 4.4 |
| 4.6 | Add progress callbacks and logging | 1d | 4.5 |
| 4.7 | Add CLI commands for transfer | 1d | 4.6 |
| 4.8 | Integration tests for transfer | 2d | 4.7 |
| 4.9 | Documentation for transfer | 1d | 4.8 |

**Deliverables:**
- [ ] `sagaz/storage/transfer/` module
- [ ] CLI commands: `sagaz storage transfer`, `sagaz storage migrate`
- [ ] Full documentation with examples

#### Transfer API Design

```python
# storage/transfer/base.py
@dataclass
class TransferProgress:
    """Progress of a transfer operation."""
    total: int
    transferred: int
    failed: int
    elapsed_seconds: float
    
    @property
    def percent_complete(self) -> float:
        return (self.transferred / self.total * 100) if self.total > 0 else 0


class StorageTransfer:
    """
    Transfer data between storage backends.
    
    Usage:
        >>> source = PostgreSQLSagaStorage(...)
        >>> target = RedisSagaStorage(...)
        >>> 
        >>> transfer = StorageTransfer(source, target)
        >>> async for progress in transfer.execute():
        ...     print(f"Progress: {progress.percent_complete:.1f}%")
    """
    
    def __init__(
        self,
        source: SagaStorage | OutboxStorage,
        target: SagaStorage | OutboxStorage,
        batch_size: int = 100,
        on_error: Literal["skip", "fail"] = "fail",
    ):
        ...
    
    async def execute(self) -> AsyncIterator[TransferProgress]:
        """Execute transfer, yielding progress updates."""
        ...
    
    async def validate(self) -> TransferValidation:
        """Validate source and target compatibility."""
        ...


# CLI integration
# sagaz storage transfer --source postgresql://... --target redis://... --type saga
# sagaz storage transfer --source redis://... --target postgresql://... --type outbox
```

---

### Phase 5: SQLite Backend (Week 5-6) - Optional

**Goal:** Add SQLite support for embedded/local deployments.

#### Tasks

| ID | Task | Effort | Dependencies |
|----|------|--------|--------------|
| 5.1 | Create `storage/backends/sqlite/` | 0.5d | 3.10 |
| 5.2 | Implement SQLite connection (aiosqlite) | 1d | 5.1 |
| 5.3 | Implement SQLite saga storage | 2d | 5.2 |
| 5.4 | Implement SQLite outbox storage | 2d | 5.2 |
| 5.5 | Add export/import support | 1d | 5.3, 5.4 |
| 5.6 | Tests for SQLite backend | 1d | 5.5 |
| 5.7 | Update factory and docs | 0.5d | 5.6 |

**Deliverables:**
- [ ] SQLite backend for both saga and outbox storage
- [ ] Great for local development and embedded use cases

---

### Phase 6: Factory Enhancement & Documentation (Week 6)

**Goal:** Unified factory API and comprehensive documentation.

#### Tasks

| ID | Task | Effort | Dependencies |
|----|------|--------|--------------|
| 6.1 | Enhance `create_storage()` for unified API | 1d | 4.9 |
| 6.2 | Add `create_outbox_storage()` function | 1d | 6.1 |
| 6.3 | Add storage auto-detection from URL | 1d | 6.2 |
| 6.4 | Update `SagaConfig` integration | 1d | 6.3 |
| 6.5 | Write migration guide | 1d | 6.4 |
| 6.6 | Update README and API docs | 1d | 6.5 |
| 6.7 | Add storage comparison guide | 0.5d | 6.6 |
| 6.8 | Final integration testing | 1d | 6.7 |

**Deliverables:**
- [ ] Unified factory API
- [ ] Complete migration guide
- [ ] Updated documentation

#### Enhanced Factory API

```python
# storage/factory.py

def create_storage(
    url: str,
    storage_type: Literal["saga", "outbox", "both"] = "saga",
    **options,
) -> SagaStorage | OutboxStorage | tuple[SagaStorage, OutboxStorage]:
    """
    Create storage from URL with auto-detection.
    
    URL formats:
        memory://
        redis://host:port/db
        postgresql://user:pass@host:port/db
        sqlite:///path/to/file.db
    
    Examples:
        # Create saga storage
        >>> saga = create_storage("postgresql://localhost/db")
        
        # Create outbox storage
        >>> outbox = create_storage("redis://localhost", storage_type="outbox")
        
        # Create both from same backend
        >>> saga, outbox = create_storage("postgresql://...", storage_type="both")
    """
    ...
```

---

## Timeline Summary

```
Week 1-2: Phase 1 - Core Infrastructure
Week 2-3: Phase 2 - Interface Refactoring  
Week 3-4: Phase 3 - Backend Reorganization + Redis Outbox
Week 4-5: Phase 4 - Transfer Layer
Week 5-6: Phase 5 - SQLite Backend (Optional)
Week 6:   Phase 6 - Factory Enhancement & Documentation
```

**Total Estimated Effort:** 6 weeks (with SQLite) or 5 weeks (without SQLite)

---

## Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Breaking backward compatibility | High | Medium | Comprehensive compat layer with deprecation warnings |
| Performance regression | Medium | Low | Benchmark suite before/after |
| Redis Streams complexity | Medium | Medium | Start with simple implementation, iterate |
| Scope creep | Medium | Medium | Defer SQLite if needed |
| Test coverage gaps | Medium | Low | Maintain >90% coverage requirement |

---

## Success Criteria

### Phase 1 Complete
- [ ] Core module passes all unit tests
- [ ] No changes to existing public API

### Phase 2 Complete  
- [ ] Old imports work with deprecation warnings
- [ ] New interface location documented

### Phase 3 Complete
- [ ] All backends refactored to use core
- [ ] Redis outbox storage fully functional
- [ ] Integration tests pass for all backends

### Phase 4 Complete
- [ ] Can transfer data between any two backends
- [ ] CLI commands work
- [ ] Performance acceptable (>1000 records/sec)

### Phase 5 Complete (Optional)
- [ ] SQLite works for both saga and outbox
- [ ] Suitable for local development

### Phase 6 Complete
- [ ] Factory API unified and documented
- [ ] Migration guide published
- [ ] All tests pass, coverage >90%

---

## Dependencies to Add

```toml
# pyproject.toml additions

[project.optional-dependencies]
storage = [
    "asyncpg>=0.30.0",      # PostgreSQL
    "redis>=7.0.0",         # Redis
    "aiosqlite>=0.20.0",    # SQLite (NEW)
]

# For transfer progress bars in CLI
cli = [
    "typer>=0.9.0",
    "rich>=13.0.0",         # Progress bars (already included)
]
```

---

## Next Steps

1. **Review and approve this plan**
2. **Create GitHub issues** for each phase/task
3. **Begin Phase 1** implementation
4. **Weekly check-ins** on progress

---

## Appendix A: API Backward Compatibility

All existing import paths will continue to work:

```python
# OLD (deprecated but working)
from sagaz.storage.base import SagaStorage
from sagaz.storage.memory import InMemorySagaStorage
from sagaz.storage.postgresql import PostgreSQLSagaStorage
from sagaz.outbox.storage.base import OutboxStorage

# NEW (recommended)
from sagaz.storage import SagaStorage, OutboxStorage
from sagaz.storage import create_storage
from sagaz.storage.backends import PostgreSQLSagaStorage, RedisSagaStorage
```

---

## Appendix B: Data Transfer Examples

```python
# Transfer saga state from PostgreSQL to Redis
from sagaz.storage import create_storage
from sagaz.storage.transfer import StorageTransfer

async def migrate_to_redis():
    source = create_storage("postgresql://localhost/sagaz")
    target = create_storage("redis://localhost:6379")
    
    transfer = StorageTransfer(source, target)
    
    # Validate compatibility
    validation = await transfer.validate()
    if not validation.compatible:
        print(f"Incompatible: {validation.issues}")
        return
    
    # Execute transfer with progress
    async for progress in transfer.execute():
        print(f"Transferred: {progress.transferred}/{progress.total}")
    
    print("Migration complete!")


# CLI equivalent
# $ sagaz storage transfer \
#     --source "postgresql://localhost/sagaz" \
#     --target "redis://localhost:6379" \
#     --type saga \
#     --batch-size 500
```
