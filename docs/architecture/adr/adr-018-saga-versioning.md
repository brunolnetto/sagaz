# ADR-018: Saga Versioning & Schema Evolution

## Status

**Proposed** | Date: 2025-01-01 | Target: v2.0.0

## Dependencies

**Prerequisites**:
- ADR-024: Saga Replay (optional - replay across versions)

**Synergies**:
- Blue-green deployments
- Zero-downtime version upgrades

**Roadmap**: **Phase 4 (v2.0.0)** - Enterprise production feature

## Context

In production systems, sagas evolve over time:
- **New steps** added (e.g., fraud detection in payment saga)
- **Steps removed** (e.g., deprecated notification service)
- **Context schema changes** (e.g., add `customer_tier` field)
- **Compensation logic updates** (e.g., new refund API)

### The Problem

**Without versioning:**

```python
# v1 - Running in production
class OrderSaga(Saga):
    @action("reserve_inventory")
    async def reserve(self, ctx):
        return {"reserved": ctx["quantity"]}
    
    @action("charge_payment")
    async def charge(self, ctx):
        return await payment.charge(ctx["amount"])

# v2 - Deploy new version
class OrderSaga(Saga):
    @action("validate_fraud")  # NEW STEP
    async def validate_fraud(self, ctx):
        return await fraud.check(ctx["user_id"])
    
    @action("reserve_inventory", depends_on=["validate_fraud"])
    async def reserve(self, ctx):
        return {"reserved": ctx["quantity"]}
    
    @action("charge_payment")
    async def charge(self, ctx):
        # NEW FIELD REQUIRED
        return await payment.charge(ctx["amount"], ctx["customer_tier"])
```

**What happens to in-flight sagas?**

| Scenario | Problem |
|----------|---------|
| v1 saga at "reserve_inventory" | Replaying fails - no "validate_fraud" step |
| v1 saga context missing "customer_tier" | KeyError in v2 code |
| Rollback v2 to v1 | Can't handle v2 sagas in database |
| Blue-green deployment | Two versions running simultaneously |

### Production Pain Points (2024-2025)

Real incidents:

1. **E-commerce Platform** - Adding fraud check step broke 1,200 in-flight orders during deployment
2. **Healthcare** - Context schema change caused 6-hour outage, couldn't roll back
3. **FinTech** - Blue-green deployment with different saga versions caused data corruption
4. **IoT Platform** - Removing deprecated step made old sagas unrecoverable

## Decision

Implement **Saga Versioning & Schema Evolution** with semantic versioning and migration strategies.

### Core Concepts

#### 1. Semantic Versioning

```python
class OrderSaga(Saga):
    saga_name = "order-processing"
    version = "2.1.0"  # MAJOR.MINOR.PATCH
    
    # MAJOR: Breaking changes (new required steps, removed steps)
    # MINOR: Backward-compatible additions (new optional steps)
    # PATCH: Bug fixes in compensation logic
```

#### 2. Version Registry

```python
# saga_versions table
CREATE TABLE saga_versions (
    saga_name        VARCHAR(255) NOT NULL,
    version          VARCHAR(20) NOT NULL,
    schema           JSONB NOT NULL,        -- Context schema
    step_names       JSONB NOT NULL,        -- Array of steps
    deployed_at      TIMESTAMPTZ NOT NULL,
    deprecated_at    TIMESTAMPTZ,           -- When marked deprecated
    removed_at       TIMESTAMPTZ,           -- When removed from codebase
    
    PRIMARY KEY (saga_name, version)
);

-- Track running sagas by version
CREATE TABLE saga_instances (
    saga_id          UUID PRIMARY KEY,
    saga_name        VARCHAR(255) NOT NULL,
    version          VARCHAR(20) NOT NULL,
    status           VARCHAR(50) NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    
    FOREIGN KEY (saga_name, version) 
        REFERENCES saga_versions(saga_name, version)
);
```

#### 3. Schema Migration

```python
class OrderSagaV2(Saga):
    saga_name = "order-processing"
    version = "2.0.0"
    
    @classmethod
    def migrate_from_v1(cls, v1_context: dict) -> dict:
        """Migrate v1 context to v2 schema."""
        return {
            **v1_context,
            "customer_tier": v1_context.get("customer_tier", "standard"),  # Default
            "fraud_check_required": True  # New field
        }
    
    @action("validate_fraud")
    async def validate_fraud(self, ctx):
        if not ctx.get("fraud_check_required"):
            return {"fraud_score": 0}  # Skip for migrated v1 sagas
        return await fraud.check(ctx["user_id"])
```

## Architecture

### Version Resolution Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    SAGA EXECUTION REQUEST                    │
│                                                              │
│  1. Determine version (new saga vs. resuming)               │
│  2. Load appropriate saga class                             │
│  3. Apply migrations if needed                              │
│  4. Execute with version-specific logic                     │
│                                                              │
│  ┌───────────────┐     ┌────────────────┐     ┌─────────┐  │
│  │   Version     │ ──► │   Migration    │ ──► │  Saga   │  │
│  │   Resolver    │     │   Engine       │     │ Executor│  │
│  └───────────────┘     └────────────────┘     └─────────┘  │
│         │                     │                     │       │
│         ▼                     ▼                     ▼       │
│  saga_versions         migrations.py         OrderSagaV2   │
└─────────────────────────────────────────────────────────────┘
```

### Version Resolver Implementation

```python
class SagaVersionResolver:
    """Resolve and load appropriate saga version."""
    
    async def resolve_version(
        self,
        saga_name: str,
        saga_id: str | None = None
    ) -> tuple[type[Saga], str]:
        """
        Resolve which saga version to use.
        
        For new sagas: use latest version
        For existing sagas: use version from saga_instances
        """
        if saga_id:
            # Resuming existing saga - use original version
            instance = await self.storage.get_saga_instance(saga_id)
            version = instance.version
        else:
            # New saga - use latest version
            version = await self.storage.get_latest_version(saga_name)
        
        # Load saga class
        saga_class = self._load_saga_class(saga_name, version)
        return saga_class, version
    
    def _load_saga_class(
        self,
        saga_name: str,
        version: str
    ) -> type[Saga]:
        """
        Load saga class for specific version.
        
        Supports:
        1. Version-specific classes (OrderSagaV1, OrderSagaV2)
        2. Version registry (plugin system)
        3. Backward compatibility shims
        """
        # Try version-specific class
        class_name = f"{saga_name.title().replace('-', '')}V{version.replace('.', '_')}"
        if class_name in self.registry:
            return self.registry[class_name]
        
        # Try latest with compatibility mode
        latest_class = self.registry.get(saga_name)
        if latest_class and self._is_compatible(latest_class.version, version):
            return latest_class
        
        raise SagaVersionNotFound(saga_name, version)
```

### Migration Engine

```python
class MigrationEngine:
    """Handle context schema migrations between versions."""
    
    def __init__(self):
        self.migrations: dict[str, dict[str, Callable]] = {}
    
    def register_migration(
        self,
        saga_name: str,
        from_version: str,
        to_version: str,
        migrate_fn: Callable[[dict], dict]
    ):
        """Register a migration function."""
        key = f"{saga_name}:{from_version}:{to_version}"
        self.migrations[key] = migrate_fn
    
    async def migrate_context(
        self,
        saga_name: str,
        from_version: str,
        to_version: str,
        context: dict
    ) -> dict:
        """
        Migrate context from one version to another.
        
        Handles multi-hop migrations: v1 → v1.1 → v2.0
        """
        if from_version == to_version:
            return context  # No migration needed
        
        # Find migration path
        path = self._find_migration_path(saga_name, from_version, to_version)
        
        # Apply migrations in sequence
        migrated = context
        for step in path:
            migrate_fn = self.migrations[step]
            migrated = migrate_fn(migrated)
        
        return migrated
    
    def _find_migration_path(
        self,
        saga_name: str,
        from_ver: str,
        to_ver: str
    ) -> list[str]:
        """Find shortest migration path using BFS."""
        # Graph search algorithm to find v1→v1.1→v2 path
        # Returns list of migration keys to apply
        pass
```

## Deployment Strategies

### Strategy 1: Blue-Green with Version Pinning

```python
# Blue deployment (v1)
saga = OrderSagaV1()
await saga.run(context)

# Green deployment (v2)
saga = OrderSagaV2()
await saga.run(context)

# Both versions coexist during switchover
# Version resolver ensures continuity
```

**Workflow:**
1. Deploy v2 alongside v1 (both running)
2. New sagas use v2, existing sagas use v1
3. Wait for all v1 sagas to complete
4. Remove v1 deployment

**Duration:** Minutes to hours (depends on saga duration)

### Strategy 2: Rolling Deployment with Backward Compatibility

```python
class OrderSaga(Saga):
    saga_name = "order-processing"
    version = "2.0.0"
    backward_compatible_with = ["1.9.0", "1.8.0"]
    
    @action("validate_fraud")
    async def validate_fraud(self, ctx):
        # Gracefully handle missing field from v1
        if "customer_tier" not in ctx:
            ctx["customer_tier"] = "standard"
        return await fraud.check(ctx)
```

**Workflow:**
1. Deploy v2 with backward compatibility
2. v2 can handle v1 sagas
3. Gradual pod replacement
4. No downtime

**Duration:** Seconds (standard rolling update)

### Strategy 3: In-Place Migration

```python
# Run migration job
migration = SagaMigration(
    saga_name="order-processing",
    from_version="1.0.0",
    to_version="2.0.0"
)

# Migrate all in-flight sagas
migrated_count = await migration.migrate_all(dry_run=False)
print(f"Migrated {migrated_count} sagas")

# Deploy v2
# All sagas now v2-compatible
```

**Workflow:**
1. Pause saga execution
2. Run migration script
3. Deploy v2
4. Resume execution

**Duration:** Minutes (migration + deploy)

## Use Cases

### Use Case 1: Adding New Required Step

**Scenario:** Add fraud detection step to payment saga.

**v1 → v2 Migration:**
```python
# v1 (old)
class PaymentSaga(Saga):
    version = "1.0.0"
    
    @action("charge")
    async def charge(self, ctx):
        return await payment.charge(ctx["amount"])

# v2 (new)
class PaymentSaga(Saga):
    version = "2.0.0"  # MAJOR bump
    
    @action("validate_fraud")
    async def validate_fraud(self, ctx):
        return await fraud.check(ctx["user_id"])
    
    @action("charge", depends_on=["validate_fraud"])
    async def charge(self, ctx):
        return await payment.charge(ctx["amount"])
    
    @classmethod
    def migrate_from_v1(cls, v1_context):
        # For migrated v1 sagas, fraud check already passed implicitly
        return {
            **v1_context,
            "fraud_validated": True,  # Skip for old sagas
            "fraud_score": 0
        }
```

### Use Case 2: Context Schema Change

**Scenario:** Add `customer_tier` field to enable tiered pricing.

**Migration:**
```python
# v1 → v2 context migration
def migrate_v1_to_v2(ctx: dict) -> dict:
    # Infer tier from existing data
    order_count = ctx.get("order_count", 0)
    tier = "platinum" if order_count > 100 else "standard"
    
    return {
        **ctx,
        "customer_tier": tier,
        "tier_inferred": True  # Mark as inferred
    }

# Register migration
migration_engine.register_migration(
    saga_name="order-processing",
    from_version="1.0.0",
    to_version="2.0.0",
    migrate_fn=migrate_v1_to_v2
)
```

### Use Case 3: Removing Deprecated Step

**Scenario:** Remove old notification service step.

**v2 → v3 Migration:**
```python
# v2 (with deprecated step)
class OrderSaga(Saga):
    version = "2.0.0"
    
    @action("notify_old_service")  # DEPRECATED
    @deprecated(since="2.0.0", remove_in="3.0.0")
    async def notify_old(self, ctx):
        return {}  # No-op, but preserved for v2 sagas
    
    @action("notify_new_service")
    async def notify_new(self, ctx):
        return await new_notification.send(ctx)

# v3 (removed old step)
class OrderSaga(Saga):
    version = "3.0.0"  # MAJOR bump
    
    @action("notify_new_service")
    async def notify_new(self, ctx):
        return await new_notification.send(ctx)
    
    # No migration needed - step removal is backward compatible
    # v2 sagas skip missing step
```

### Use Case 4: Blue-Green Deployment

**Scenario:** Deploy new saga version with zero downtime.

**Solution:**
```bash
# 1. Deploy v2 alongside v1
kubectl apply -f saga-v2-deployment.yml

# 2. Traffic split (50/50)
kubectl annotate deployment saga-v1 traffic-weight=50
kubectl annotate deployment saga-v2 traffic-weight=50

# 3. Monitor metrics
# - Error rate
# - Saga completion rate
# - Compensation rate

# 4. Full cutover to v2
kubectl annotate deployment saga-v2 traffic-weight=100

# 5. Wait for v1 sagas to drain
watch 'kubectl get pods -l version=v1'

# 6. Remove v1
kubectl delete deployment saga-v1
```

## Implementation Phases

### Phase 1: Version Infrastructure (v2.1.0)

- [ ] Create `saga_versions` table
- [ ] Create `saga_instances` table
- [ ] Implement `SagaVersionResolver`
- [ ] Add version attribute to Saga class

**Duration:** 1 week

### Phase 2: Migration Engine (v2.1.0)

- [ ] Implement `MigrationEngine`
- [ ] Add migration registration API
- [ ] Implement multi-hop migration path finding
- [ ] Add dry-run migration mode

**Duration:** 1 week

### Phase 3: Backward Compatibility (v2.2.0)

- [ ] Add `backward_compatible_with` attribute
- [ ] Implement compatibility checking
- [ ] Add graceful degradation for missing steps
- [ ] Handle optional vs required fields

**Duration:** 1 week

### Phase 4: Deployment Tooling (v2.2.0)

- [ ] CLI: `sagaz migrate --from 1.0.0 --to 2.0.0`
- [ ] CLI: `sagaz version list`
- [ ] CLI: `sagaz version deprecate 1.0.0`
- [ ] Kubernetes integration examples

**Duration:** 3 days

### Phase 5: Monitoring & Safety (v2.3.0)

- [ ] Version distribution dashboard
- [ ] Migration monitoring
- [ ] Rollback procedures
- [ ] Canary deployment support

**Duration:** 1 week

## Alternatives Considered

### Alternative 1: No Versioning (Always Latest)

Force all sagas to use latest code.

**Pros:**
- Simple, no version tracking

**Cons:**
- Breaking changes break in-flight sagas
- Can't do blue-green deployments
- Rollbacks impossible

**Decision:** Rejected - too risky.

### Alternative 2: Version per Saga Instance

Each saga tracks its own version independently.

**Pros:**
- Fine-grained control

**Cons:**
- Complex - saga code must handle all versions
- No deprecation path

**Decision:** Rejected - too complex.

### Alternative 3: Copy-Paste Versioning

Duplicate entire saga class for each version.

**Pros:**
- Clear separation

**Cons:**
- Code duplication
- No migration support
- Maintenance nightmare

**Decision:** Rejected - doesn't scale.

## Consequences

### Positive

1. **Zero-Downtime Deployments** - Blue-green with version coexistence
2. **Safe Rollbacks** - Revert to previous version without data loss
3. **Schema Evolution** - Add/remove fields safely
4. **Gradual Migration** - Migrate sagas at own pace
5. **Audit Trail** - Track which version processed each saga

### Negative

1. **Complexity** - Version resolution adds system complexity
2. **Storage Overhead** - Store version metadata
3. **Migration Effort** - Writing migration functions takes time
4. **Testing Burden** - Test multiple versions simultaneously

### Mitigations

| Risk | Mitigation |
|------|------------|
| Version explosion | Deprecation policy (remove after 90 days) |
| Migration bugs | Dry-run mode, automated testing |
| Complexity | Good tooling and documentation |
| Storage overhead | Archive old versions |

## Best Practices

### Versioning Guidelines

```python
# ✅ GOOD: Semantic versioning
class OrderSaga(Saga):
    version = "2.1.0"  # Clear, parseable

# ❌ BAD: Ambiguous versioning
class OrderSaga(Saga):
    version = "v2-final"  # Can't compare
```

### Migration Guidelines

```python
# ✅ GOOD: Explicit default values
def migrate(ctx: dict) -> dict:
    return {
        **ctx,
        "new_field": ctx.get("new_field", "default_value")
    }

# ❌ BAD: Assume field exists
def migrate(ctx: dict) -> dict:
    return {
        **ctx,
        "new_field": ctx["old_field"]  # KeyError if missing
    }
```

### Deprecation Policy

```python
class OrderSaga(Saga):
    version = "2.0.0"
    
    @action("old_step")
    @deprecated(
        since="2.0.0",
        remove_in="3.0.0",
        alternative="new_step",
        reason="Performance improvement"
    )
    async def old_step(self, ctx):
        warnings.warn("old_step deprecated, use new_step")
        return await self.new_step(ctx)
```

## References

### Industry Patterns

- **Temporal.io** - Workflow versioning with deterministic execution
- **Stripe API** - Version headers for API compatibility
- **Kubernetes** - API versioning (v1, v1beta1)
- **Protobuf** - Schema evolution with field numbers

### Standards

- [Semantic Versioning 2.0.0](https://semver.org/)
- [API Versioning Best Practices](https://www.baeldung.com/rest-versioning)

### Research

- [Schema Evolution in Event Sourcing](https://arkwright.github.io/event-sourcing.html)
- [Database Schema Migration Patterns](https://www.martinfowler.com/articles/evodb.html)

## Decision Makers

- @brunolnetto (Maintainer)

## Changelog

| Date | Change |
|------|--------|
| 2025-01-01 | Initial proposal |

---

*Proposed 2025-01-01*
