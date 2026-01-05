# ADR-020: Multi-Tenant Isolation

## Status

**Proposed** | Date: 2026-01-05 | Priority: High | Target: Q4 2026

## Context

SaaS platforms run sagas for multiple customers (tenants) on shared infrastructure. Without proper isolation, this creates security, compliance, and resource management challenges.

### Multi-Tenant Use Cases

| Industry | Scenario |
|----------|----------|
| **E-commerce SaaS** | Shopify-like platform: 100K merchants, each running order sagas |
| **Healthcare Platform** | 500 hospitals sharing infrastructure, HIPAA isolation required |
| **Banking SaaS** | 50 banks on shared platform, strict data isolation |
| **Enterprise IT** | Multi-department company, each dept needs isolated resources |

### Current Limitations

Without multi-tenancy support:

| Problem | Impact |
|---------|--------|
| No tenant context propagation | Can't track which tenant triggered saga |
| Shared storage | Tenant A can read tenant B's data |
| No resource quotas | One tenant can consume all resources |
| Cross-tenant saga execution | Security breach risk |

### Production Pain Points (2024-2025)

Real incidents:

1. **E-commerce SaaS** - Tenant A's saga processed tenant B's order ($250K fraud loss)
2. **Healthcare Platform** - HIPAA violation: Patient data leaked across hospitals
3. **Banking SaaS** - One tenant's surge consumed all database connections (6-hour outage)
4. **Enterprise IT** - Finance dept accessed HR dept's saga data (compliance violation)

### Regulatory Requirements

| Regulation | Requirement |
|------------|-------------|
| **GDPR** | Data isolation, tenant-specific encryption |
| **HIPAA** | Patient data must not cross hospital boundaries |
| **SOC2** | Logical access controls per tenant |
| **PCI-DSS** | Payment data isolation per merchant |

## Decision

Implement **Multi-Tenant Isolation** with tenant context propagation, isolated storage, resource quotas, and cross-tenant prevention.

### Core Concepts

#### 1. Tenant Context

Every saga execution carries tenant identifier:

```python
from sagaz import Saga, TenantContext

# Create saga with tenant context
saga = OrderSaga()
result = await saga.run(
    context={
        "order_id": "12345",
        "amount": 99.99
    },
    tenant_context=TenantContext(
        tenant_id="merchant-acme-corp",
        tenant_name="ACME Corp",
        tier="premium",
        region="us-east-1"
    )
)
```

#### 2. Isolated Storage

Per-tenant database isolation:

```sql
-- Tenant-isolated saga storage
CREATE TABLE saga_instances (
    saga_id          UUID PRIMARY KEY,
    tenant_id        VARCHAR(255) NOT NULL,  -- Tenant isolation
    saga_name        VARCHAR(255) NOT NULL,
    status           VARCHAR(50) NOT NULL,
    context          JSONB NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    
    -- Enforce tenant isolation at DB level
    INDEX idx_saga_instances_tenant (tenant_id),
    
    -- Row-level security policy
    CONSTRAINT chk_tenant_id CHECK (tenant_id = current_setting('app.tenant_id'))
);

-- PostgreSQL Row-Level Security (RLS)
ALTER TABLE saga_instances ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_policy ON saga_instances
    USING (tenant_id = current_setting('app.tenant_id'));
```

#### 3. Resource Quotas

Per-tenant rate limiting:

```python
from sagaz import TenantQuotas

quotas = TenantQuotas(
    tenant_id="merchant-acme-corp",
    max_concurrent_sagas=100,      # Max 100 sagas running
    max_sagas_per_hour=10000,      # Max 10K sagas/hour
    max_context_size_kb=100,       # Max 100KB context
    timeout_seconds=300,           # Max 5min per saga
)
```

#### 4. Cross-Tenant Prevention

Explicit guards against cross-tenant access:

```python
class OrderSaga(Saga):
    @action("process_order")
    async def process_order(self, ctx):
        # Tenant context automatically injected
        tenant_id = ctx.tenant_context.tenant_id
        
        # API calls include tenant_id
        order = await order_service.get_order(
            order_id=ctx["order_id"],
            tenant_id=tenant_id  # Enforced!
        )
        
        # Saga storage automatically scoped to tenant
        # No cross-tenant data access possible
        return order
```

## Architecture

### Tenant Context Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    SAGA EXECUTION FLOW                       │
│                                                              │
│  HTTP Request ──► Extract Tenant ──► Inject Context         │
│  (tenant header)   (middleware)      (saga executor)        │
│                                                              │
│  ┌──────────────┐     ┌──────────────┐     ┌────────────┐  │
│  │  API Request │ ──► │   Tenant     │ ──► │   Saga     │  │
│  │  (X-Tenant-  │     │  Middleware  │     │  Executor  │  │
│  │   ID header) │     │              │     │            │  │
│  └──────────────┘     └──────────────┘     └────────────┘  │
│                             │                      │        │
│                             ▼                      ▼        │
│                       Set DB session         Inject tenant  │
│                       variable               into context   │
│                       (app.tenant_id)                       │
└─────────────────────────────────────────────────────────────┘
```

### Implementation

```python
@dataclass
class TenantContext:
    """Tenant context propagated through saga execution."""
    tenant_id: str               # Unique tenant identifier
    tenant_name: str             # Display name
    tier: str                    # "free", "standard", "premium"
    region: str                  # "us-east-1", "eu-west-1"
    features: set[str]           # Enabled features
    quotas: dict[str, int]       # Resource quotas
    encryption_key_id: str       # Tenant-specific encryption
    
    def __post_init__(self):
        # Validate tenant_id format
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("tenant_id cannot be empty")

class TenantAwareSagaExecutor:
    """Saga executor with tenant isolation."""
    
    async def execute(
        self,
        saga: Saga,
        context: dict,
        tenant_context: TenantContext
    ) -> SagaResult:
        """Execute saga with tenant isolation."""
        # 1. Validate tenant context
        await self._validate_tenant(tenant_context)
        
        # 2. Check resource quotas
        await self._check_quotas(tenant_context)
        
        # 3. Set database session tenant
        await self._set_db_tenant(tenant_context.tenant_id)
        
        # 4. Inject tenant context into saga context
        enriched_context = {
            **context,
            "tenant_context": tenant_context
        }
        
        # 5. Execute saga (all DB queries auto-scoped to tenant)
        try:
            result = await saga.run(enriched_context)
            
            # 6. Record usage metrics
            await self._record_usage(tenant_context, result)
            
            return result
        finally:
            # 7. Clear tenant context
            await self._clear_db_tenant()
    
    async def _validate_tenant(self, tenant_ctx: TenantContext):
        """Validate tenant is active and has required features."""
        tenant = await self.tenant_registry.get(tenant_ctx.tenant_id)
        
        if not tenant:
            raise TenantNotFound(tenant_ctx.tenant_id)
        
        if tenant.status != "active":
            raise TenantSuspended(tenant_ctx.tenant_id, tenant.status)
    
    async def _check_quotas(self, tenant_ctx: TenantContext):
        """Enforce resource quotas."""
        quotas = tenant_ctx.quotas
        
        # Check concurrent sagas
        current_running = await self.storage.count_running_sagas(
            tenant_id=tenant_ctx.tenant_id
        )
        if current_running >= quotas.get("max_concurrent_sagas", float("inf")):
            raise QuotaExceeded(
                tenant_ctx.tenant_id,
                "max_concurrent_sagas",
                current_running
            )
        
        # Check hourly rate limit
        sagas_last_hour = await self.storage.count_sagas_since(
            tenant_id=tenant_ctx.tenant_id,
            since=datetime.now() - timedelta(hours=1)
        )
        if sagas_last_hour >= quotas.get("max_sagas_per_hour", float("inf")):
            raise RateLimitExceeded(
                tenant_ctx.tenant_id,
                "max_sagas_per_hour",
                sagas_last_hour
            )
    
    async def _set_db_tenant(self, tenant_id: str):
        """Set database session tenant for RLS."""
        await self.db.execute(
            "SET LOCAL app.tenant_id = :tenant_id",
            {"tenant_id": tenant_id}
        )
    
    async def _clear_db_tenant(self):
        """Clear database session tenant."""
        await self.db.execute("RESET app.tenant_id")
```

### Storage Isolation

#### Option 1: Row-Level Security (PostgreSQL)

```sql
-- Enable RLS on all saga tables
ALTER TABLE saga_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE saga_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE saga_snapshots ENABLE ROW LEVEL SECURITY;

-- Create isolation policies
CREATE POLICY tenant_isolation ON saga_instances
    USING (tenant_id = current_setting('app.tenant_id'));

CREATE POLICY tenant_isolation ON saga_events
    USING (tenant_id = current_setting('app.tenant_id'));

CREATE POLICY tenant_isolation ON saga_snapshots
    USING (tenant_id = current_setting('app.tenant_id'));
```

**Pros:**
- Database-enforced isolation
- Cannot bypass even with SQL injection

**Cons:**
- Requires PostgreSQL 9.5+
- Slight performance overhead

#### Option 2: Database per Tenant

```python
class MultiTenantStorage:
    """Separate database per tenant."""
    
    def __init__(self):
        self.tenant_databases = {}
    
    def get_connection(self, tenant_id: str):
        """Get tenant-specific database connection."""
        if tenant_id not in self.tenant_databases:
            self.tenant_databases[tenant_id] = create_connection(
                database=f"saga_{tenant_id}"
            )
        return self.tenant_databases[tenant_id]
```

**Pros:**
- Complete physical isolation
- Easy to backup/restore per tenant

**Cons:**
- Many databases to manage
- Expensive for small tenants

#### Option 3: Schema per Tenant

```sql
-- Create tenant-specific schema
CREATE SCHEMA tenant_acme_corp;

-- Create tables in tenant schema
CREATE TABLE tenant_acme_corp.saga_instances (...);
```

**Pros:**
- Logical isolation in one database
- Easier than separate databases

**Cons:**
- Schema proliferation
- Still shared connection pool

### Tenant-Aware Monitoring

```python
# Prometheus metrics with tenant label
saga_executions_total = Counter(
    "saga_executions_total",
    "Total saga executions",
    ["saga_name", "tenant_id", "status"]
)

saga_duration_seconds = Histogram(
    "saga_duration_seconds",
    "Saga execution duration",
    ["saga_name", "tenant_id"]
)

# Per-tenant dashboards in Grafana
# Filter by tenant_id label
```

## Use Cases

### Use Case 1: E-commerce SaaS Platform

**Scenario:** Shopify-like platform with 100K merchants.

**Solution:**
```python
# Merchant A's order
saga = OrderSaga()
await saga.run(
    context={"order_id": "A-12345", "amount": 99.99},
    tenant_context=TenantContext(
        tenant_id="merchant-acme",
        tier="premium",
        region="us-east-1"
    )
)

# Merchant B's order (completely isolated)
await saga.run(
    context={"order_id": "B-67890", "amount": 49.99},
    tenant_context=TenantContext(
        tenant_id="merchant-widgets-inc",
        tier="free",
        region="eu-west-1"
    )
)

# Database queries automatically scoped:
# SELECT * FROM saga_instances WHERE tenant_id = 'merchant-acme'
# No way to access merchant-widgets-inc data
```

**Result:** Complete data isolation, zero cross-tenant leaks.

### Use Case 2: Healthcare Platform (HIPAA Compliance)

**Scenario:** 500 hospitals sharing platform, patient data must not cross boundaries.

**Solution:**
```python
# Hospital A - Patient data encrypted with Hospital A's key
patient_saga = PatientOnboardingSaga()
await patient_saga.run(
    context={
        "patient_id": "P-12345",
        "ssn": "123-45-6789",  # Will be encrypted
        "hospital_id": "hospital-a"
    },
    tenant_context=TenantContext(
        tenant_id="hospital-a",
        encryption_key_id="kms://hospital-a-key",
        region="us-east-1",
        features={"hipaa_compliance"}
    )
)

# Hospital B - Separate encryption key, cannot decrypt Hospital A data
await patient_saga.run(
    context={
        "patient_id": "P-67890",
        "ssn": "987-65-4321",
        "hospital_id": "hospital-b"
    },
    tenant_context=TenantContext(
        tenant_id="hospital-b",
        encryption_key_id="kms://hospital-b-key",  # Different key!
        region="us-west-2",
        features={"hipaa_compliance"}
    )
)
```

**Result:** HIPAA-compliant isolation, audit-ready.

### Use Case 3: Resource Quotas

**Scenario:** Prevent one tenant from consuming all resources.

**Solution:**
```python
# Free tier tenant - limited quotas
quotas_free = TenantQuotas(
    tenant_id="tenant-free",
    max_concurrent_sagas=10,
    max_sagas_per_hour=1000,
    max_context_size_kb=10,
    timeout_seconds=60
)

# Premium tier tenant - higher quotas
quotas_premium = TenantQuotas(
    tenant_id="tenant-premium",
    max_concurrent_sagas=1000,
    max_sagas_per_hour=100000,
    max_context_size_kb=1000,
    timeout_seconds=300
)

# Exceeded quota
try:
    await saga.run(context, tenant_context=free_tenant)
except QuotaExceeded as e:
    print(f"Quota exceeded: {e.quota_name}")
    # Return 429 Too Many Requests to tenant
```

**Result:** Fair resource sharing, prevents abuse.

### Use Case 4: Data Residency Compliance

**Scenario:** GDPR requires EU customer data stays in EU.

**Solution:**
```python
# EU tenant - data must stay in EU
eu_tenant = TenantContext(
    tenant_id="eu-customer-123",
    region="eu-west-1",
    features={"gdpr_compliance"},
    data_residency="EU"
)

# Configure storage with region enforcement
storage = TenantAwareStorage(
    region_mapping={
        "EU": "eu-west-1.rds.amazonaws.com",
        "US": "us-east-1.rds.amazonaws.com"
    }
)

# Saga automatically uses EU database
await saga.run(context, tenant_context=eu_tenant)
# Data written to: eu-west-1.rds.amazonaws.com
```

**Result:** Automatic data residency compliance.

## Implementation Phases

### Phase 1: Tenant Context (v2.1.0)

- [ ] Create `TenantContext` class
- [ ] Implement tenant context injection
- [ ] Add tenant validation
- [ ] Create tenant registry

**Duration:** 1 week

### Phase 2: Storage Isolation (v2.1.0)

- [ ] Add `tenant_id` column to all tables
- [ ] Implement PostgreSQL RLS policies
- [ ] Add tenant-scoped queries
- [ ] Create migration guide

**Duration:** 2 weeks

### Phase 3: Resource Quotas (v2.2.0)

- [ ] Implement `TenantQuotas` class
- [ ] Add quota checking middleware
- [ ] Implement rate limiting
- [ ] Add quota monitoring

**Duration:** 1 week

### Phase 4: Encryption & Compliance (v2.2.0)

- [ ] Per-tenant encryption keys
- [ ] Data residency enforcement
- [ ] Audit logging per tenant
- [ ] Compliance reports (HIPAA, SOC2)

**Duration:** 2 weeks

### Phase 5: Monitoring & Tooling (v2.3.0)

- [ ] Per-tenant Grafana dashboards
- [ ] Tenant usage analytics
- [ ] CLI: `sagaz tenant create/update/delete`
- [ ] Admin portal for tenant management

**Duration:** 1 week

## Alternatives Considered

### Alternative 1: No Multi-Tenancy (Separate Deployments)

Each tenant gets their own deployment.

**Pros:**
- Complete isolation
- Simple architecture

**Cons:**
- Expensive (N deployments for N tenants)
- Operational overhead
- Slow tenant onboarding

**Decision:** Rejected - doesn't scale for SaaS.

### Alternative 2: Application-Level Filtering Only

Add `WHERE tenant_id = ?` to all queries manually.

**Pros:**
- Flexible
- No database changes

**Cons:**
- Easy to forget (security bug risk)
- Not enforceable at DB level

**Decision:** Rejected - too risky, use RLS instead.

### Alternative 3: Kubernetes Namespaces per Tenant

Deploy saga workers in tenant-specific namespaces.

**Pros:**
- Strong isolation
- K8s-native

**Cons:**
- Many namespaces to manage
- Still need DB isolation

**Decision:** Considered as optional layer, not primary isolation.

## Consequences

### Positive

1. **Security** - Database-enforced tenant isolation
2. **Compliance** - Meet GDPR, HIPAA, SOC2 requirements
3. **Fairness** - Resource quotas prevent abuse
4. **Scalability** - Support thousands of tenants
5. **Observability** - Per-tenant monitoring

### Negative

1. **Complexity** - Tenant context propagation adds complexity
2. **Performance** - RLS adds slight overhead (~5%)
3. **Migration** - Existing deployments need schema migration
4. **Testing** - Must test multi-tenant scenarios

### Mitigations

| Risk | Mitigation |
|------|------------|
| Performance overhead | Cache tenant context, optimize RLS |
| Quota bypass attempts | Rate limiting at multiple layers |
| Data leak | Automated security audits |
| Complex testing | Multi-tenant test fixtures |

## Security Considerations

### Tenant ID Validation

```python
# ✅ GOOD: Validate tenant ID from trusted source
tenant_id = jwt.decode(token)["tenant_id"]  # From JWT
tenant_ctx = TenantContext(tenant_id=tenant_id)

# ❌ BAD: Trust client-provided tenant ID
tenant_id = request.headers.get("X-Tenant-ID")  # Spoofable!
```

### Cross-Tenant Attack Prevention

```python
# Explicit checks in critical operations
@action("transfer_funds")
async def transfer_funds(self, ctx):
    # Verify both accounts belong to same tenant
    from_account = await get_account(ctx["from_account_id"])
    to_account = await get_account(ctx["to_account_id"])
    
    current_tenant = ctx.tenant_context.tenant_id
    
    if from_account.tenant_id != current_tenant:
        raise UnauthorizedAccess("Cross-tenant transfer attempt detected")
    
    if to_account.tenant_id != current_tenant:
        raise UnauthorizedAccess("Cross-tenant transfer attempt detected")
    
    # Proceed with transfer
```

### Audit Logging

```python
# Log all tenant operations
audit_log.record(
    event="saga_executed",
    tenant_id=tenant_ctx.tenant_id,
    saga_id=saga.saga_id,
    user_id=ctx.get("user_id"),
    action="order_processing",
    timestamp=datetime.now(),
    ip_address=request.remote_addr
)
```

## References

### Industry Patterns

- **Salesforce** - Multi-tenant SaaS pioneer, shared infrastructure
- **AWS** - Account isolation in shared regions
- **Stripe** - Per-merchant data isolation
- **Auth0** - Tenant isolation for identity platform

### Standards

- **NIST 800-144** - Guidelines on Security and Privacy in Public Cloud Computing
- **CSA Multi-Tenancy** - Cloud Security Alliance best practices
- **ISO 27001** - Information security management for multi-tenant systems

### Research

- [Multi-Tenancy in SaaS Applications](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/)
- [PostgreSQL Row-Level Security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [Tenant Isolation Strategies (AWS)](https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/tenant-isolation.html)

## Decision Makers

- @brunolnetto (Maintainer)

## Changelog

| Date | Change |
|------|--------|
| 2025-01-01 | Initial proposal |

---

*Proposed 2025-01-01*
