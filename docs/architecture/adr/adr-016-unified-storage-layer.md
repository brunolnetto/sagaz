# ADR-016: Unified Storage Layer

## Status

**Accepted** - Implementation planned for v1.2.0

## Dependencies

**Prerequisites**: None (Foundation ADR)

**Enables**:
- ADR-021: Lightweight Context Streaming (needs external storage)
- ADR-024: Saga Replay (needs state snapshots)
- ADR-020: Multi-Tenancy (needs data isolation)
- ADR-011: CDC Support (needs unified PostgreSQL backend)

**Roadmap**: ⭐ **Phase 1 (v1.2.0)** - Critical foundation, blocks 6 other ADRs

## Context

Sagaz currently has **two separate storage hierarchies**:

1. **Saga Storage** (`sagaz/storage/`) - For saga state persistence
   - Implementations: Memory, Redis, PostgreSQL
   - Interface: `SagaStorage` ABC

2. **Outbox Storage** (`sagaz/outbox/storage/`) - For outbox events
   - Implementations: Memory, PostgreSQL (no Redis!)
   - Interface: `OutboxStorage` ABC

### Problems with Current Architecture

| Problem | Impact |
|---------|--------|
| **DRY Violation** | Duplicate connection pool logic, health checks, error handling in PostgreSQL implementations |
| **Inconsistent Features** | Redis has saga storage but no outbox storage |
| **No Data Transfer** | Cannot migrate data between backends (e.g., PostgreSQL → Redis) |
| **Separate Factories** | Two different APIs for creating storage instances |
| **Code Maintenance** | Bug fixes must be applied to multiple places |

### Quantified Duplication

```
sagaz/storage/postgresql.py:        477 lines
sagaz/outbox/storage/postgresql.py: 550 lines
                                   ─────────
Estimated shared logic:            ~200 lines (pool management, health, serialization)
```

## Decision

We will **unify the storage layer** with:

### 1. Shared Core Infrastructure

Create `sagaz/storage/core/` with:
- `ConnectionManager` - Unified connection pool management
- `HealthCheckMixin` - Standard health check patterns
- `SerializationUtils` - JSON/data serialization utilities
- Unified error hierarchy

### 2. Complete Backend Coverage

Ensure all backends support both saga and outbox storage:

| Backend | Saga Storage | Outbox Storage |
|---------|--------------|----------------|
| Memory | ✅ Exists | ✅ Exists |
| PostgreSQL | ✅ Exists | ✅ Exists |
| Redis | ✅ Exists | 🆕 **Add** |
| SQLite | 🆕 **Add** | 🆕 **Add** |

### 3. Data Transfer Layer

Create `sagaz/storage/transfer/` for:
- Storage-to-storage data migration
- CLI commands for data transfer
- Progress reporting and validation

### 4. Unified Factory API

Single entry point for creating any storage:

```python
# Unified API
from sagaz.storage import create_storage

saga_storage = create_storage("postgresql://localhost/db", storage_type="saga")
outbox_storage = create_storage("postgresql://localhost/db", storage_type="outbox")

# Or create both from same backend
saga, outbox = create_storage("postgresql://localhost/db", storage_type="both")
```

### 5. Backward Compatibility

Maintain old import paths with deprecation warnings:

```python
# OLD (deprecated but working)
from sagaz.storage.postgresql import PostgreSQLSagaStorage
from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

# NEW (recommended)
from sagaz.storage.backends import PostgreSQLSagaStorage, PostgreSQLOutboxStorage
```

## Consequences

### ✅ Pros

| Benefit | Description |
|---------|-------------|
| **DRY Compliance** | Single implementation for connection pools, health checks, serialization |
| **Complete Redis Support** | Redis becomes a first-class citizen for both saga and outbox |
| **Data Portability** | Easy migration between backends (dev→prod, vendor switch) |
| **Simpler API** | One factory, one pattern, less cognitive load |
| **Easier Maintenance** | Bug fixes in one place benefit all backends |
| **SQLite Option** | Lightweight embedded storage for local development |

### ❌ Cons

| Drawback | Mitigation |
|----------|------------|
| **Migration Effort** | ~5-6 weeks of development |
| **Breaking Changes Risk** | Comprehensive backward compatibility layer |
| **Learning Curve** | Clear documentation and migration guide |
| **Additional Dependencies** | SQLite via `aiosqlite` (optional extra) |

### 🔄 Trade-offs

| Factor | Current | After Unification |
|--------|---------|-------------------|
| Code duplication | ~200 lines duplicated | Eliminated |
| Redis outbox | Not available | Available |
| Data transfer | Manual/impossible | Built-in CLI |
| Factory complexity | Two separate factories | One unified |
| Import paths | Two hierarchies | One (with compat) |

## Alternatives Considered

### Option A: Keep Separate Hierarchies
- **Pros**: No migration, no risk
- **Cons**: Duplication continues, no Redis outbox, no data transfer
- **Decision**: Rejected - Technical debt accumulates

### Option B: Only Add Redis Outbox
- **Pros**: Smaller change, less risk
- **Cons**: Doesn't address duplication, no data transfer
- **Decision**: Rejected - Misses opportunity for proper refactoring

### Option C: Full Unification (Chosen)
- **Pros**: Addresses all issues, future-proof architecture
- **Cons**: Larger effort, more risk
- **Decision**: Accepted - Benefits outweigh costs

## Implementation

See **[Unified Storage Implementation Plan](../implementation-plans/unified-storage-implementation-plan.md)** for detailed:
- 6-phase implementation approach
- Task breakdowns and timelines
- API designs and code examples
- Risk assessment and success criteria

### Timeline Summary

| Phase | Focus | Duration |
|-------|-------|----------|
| 1 | Core Infrastructure | Week 1-2 |
| 2 | Interface Refactoring | Week 2-3 |
| 3 | Backend Reorganization + Redis Outbox | Week 3-4 |
| 4 | Transfer Layer | Week 4-5 |
| 5 | SQLite Backend (Optional) | Week 5-6 |
| 6 | Factory & Documentation | Week 6 |

**Total**: 5-6 weeks

## Related Decisions

- **ADR-007: Pluggable Storage and Brokers** - Established the plugin architecture we're now unifying
- **ADR-009: Stateless Workers** - Workers consume from unified storage layer

## References

- [Unified Storage Implementation Plan](../unified-storage-implementation-plan.md)
- [ROADMAP v1.2.0](../../ROADMAP.md)
- Current implementations:
  - `sagaz/storage/` (saga storage)
  - `sagaz/outbox/storage/` (outbox storage)
