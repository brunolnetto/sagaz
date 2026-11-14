# Multi-tenancy

Run one sagaz deployment for many isolated tenants (ADR-020). Each tenant's sagas and
outbox events are visible only to that tenant, quotas limit what a tenant can consume,
and PostgreSQL enforces the isolation with row-level security.

## Run a saga as a tenant

```python
from sagaz import Saga, action
from sagaz.core.tenant import TenantContext, TenantQuotas

class OrderSaga(Saga):
    @action("charge")
    async def charge(self, ctx):
        ...  # ctx["tenant_id"] == "acme"

acme = TenantContext("acme", plan="premium", quotas=TenantQuotas(max_concurrent_sagas=50))
await OrderSaga().run({"order_id": "o-1"}, tenant_context=acme)
```

While the saga runs, every storage read and write is scoped to `acme`, the tenant's
quotas apply, and `ctx["tenant_id"]` is set. An initial context that already names a
*different* tenant is rejected.

Imperative sagas run as a tenant through the orchestrator:

```python
from sagaz.core.execution.orchestrator import SagaOrchestrator

orchestrator = SagaOrchestrator(tenant_id="acme", tenant_registry=registry)
await orchestrator.execute_saga(saga)
```

Any other code (for example a request handler querying storage) can open a scope
directly:

```python
from sagaz.core.tenant import tenant_scope

with tenant_scope("acme"):
    state = await storage.load_saga_state(saga_id)  # None if it belongs to another tenant
```

The scope is a `contextvars.ContextVar`, so concurrent asyncio tasks each keep their
own tenant, and it is restored when the block exits, even on error.

## Tenant ids

1–63 characters: lowercase letters, digits, `-`, `_` and `.`, starting with a letter or
digit (`acme`, `acme-corp_eu.1`). The format is safe in Redis keys and PostgreSQL
settings; anything else raises `InvalidTenantIdError`.

## Code without tenants keeps working

Code that never sets a tenant runs as the **`default`** tenant. Existing data belongs to
`default` after upgrading: PostgreSQL rows get `tenant_id = 'default'` through an
idempotent migration, and Redis keys of the default tenant are unchanged. A
single-tenant deployment sees no difference.

## Registry and quotas

`TenantRegistry` stores tenants, their plan, quotas and status. Persist it in the saga
storage so every process sees the same tenants:

```python
from sagaz.core.config import SagaConfig, configure
from sagaz.core.tenant import TenantRegistry

registry = await TenantRegistry.from_storage(storage)
configure(SagaConfig(storage=storage, tenant_registry=registry))

await OrderSaga().run(ctx, tenant_context="acme")  # resolved through the registry
```

With a registry configured, an unregistered tenant id raises `TenantNotFoundError`, and a
suspended tenant raises `TenantSuspendedError`.

| Quota | Effect |
|---|---|
| `max_concurrent_sagas` | Sagas of the tenant running at once **in this process**; one more raises `QuotaExceededError` |
| `max_step_duration_seconds` | Lowers every step timeout (and compensation timeout) to this value |
| `max_retries` | Lowers every step's retry count (and compensation retries) to this value |

`None` means unlimited. Concurrency is counted per process; for a global bound across
workers, put a shared limiter in front of saga submission.

## CLI

```bash
export SAGAZ_STORAGE_URL=postgresql://user:pass@db/sagas   # or --storage-url

sagaz tenant create acme --plan premium --max-concurrent-sagas 50
sagaz tenant quota acme --max-step-duration 30 --max-retries 2
sagaz tenant quota acme              # show
sagaz tenant quota acme --clear      # unlimited
sagaz tenant suspend acme            # stop it from running sagas
sagaz tenant activate acme
sagaz tenant list
sagaz tenant delete acme --yes       # removes the registration, not the tenant's data
```

## How each backend isolates tenants

| Backend | Isolation |
|---|---|
| PostgreSQL | `tenant_id` column on saga, step and outbox tables, plus a **row-level security** policy on `app.tenant_id`, which sagaz sets on every pooled connection it acquires. Queries also filter by tenant explicitly. |
| Redis | Keys of tenant `T` live under `sagaz:T:…`; the default tenant keeps the historical keys. |
| SQLite | `tenant_id` column with an idempotent migration, and tenant filters. |
| In-memory | Records partitioned by tenant. |

**PostgreSQL superusers and roles with `BYPASSRLS` are not subject to row-level
security.** Run the application with an ordinary role so the database itself enforces
isolation. The explicit tenant filters keep isolation even without RLS, but RLS also
protects against queries outside sagaz.

## Infrastructure: the system scope

Some components must see every tenant: the outbox worker, storage transfers and
migrations, and analytics. They run inside `system_scope()`:

```python
from sagaz.core.tenant import system_scope

with system_scope():
    async for record in storage.export_all():  # every tenant, each record with its tenant_id
        ...
```

`sagaz migrate run` and `sagaz migrate status` run in the system scope and move every
tenant's records into the same tenant on the target. When you call `TransferService`
or `SagaStorageMigrator` from your own code, they follow your scope: without
`system_scope()` they move only the current tenant (the `default` tenant if none is set).

sagaz keeps its own records (the tenant registry) in saga storage under names
starting with `__sagaz_`. `cleanup_completed_sagas` never deletes them.

The outbox worker always runs in the system scope. Each event carries its `tenant_id`,
and the worker passes it along with the published message. Tenant-facing outbox reads,
such as DLQ listing and requeue, stay restricted to the current tenant.

## Not yet included

Per-tenant encryption of saga context (AES-256-GCM with tenant keys) and the large-scale
performance benchmark are planned as the second phase of #54.
