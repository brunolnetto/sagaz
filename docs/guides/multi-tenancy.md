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
await OrderSaga().run({"order_id": "o-1"}, tenant=acme)
```

While the saga runs, every storage read and write is scoped to `acme`, the tenant's
quotas apply, and `ctx["tenant_id"]` is set. An initial context that already names a
*different* tenant is rejected.

A `SagaOrchestrator` runs every saga it is given as its tenant, and tracks their
outcome:

```python
from sagaz.core.execution.orchestrator import SagaOrchestrator

orchestrator = SagaOrchestrator(tenant="acme", tenant_registry=registry)
await orchestrator.run(OrderSaga(), {"order_id": "o-1"})   # a sagaz.Saga
await orchestrator.execute_saga(saga)                       # a classic saga (deprecated)
await orchestrator.get_statistics()                         # both kinds
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

await OrderSaga().run(ctx, tenant="acme")  # resolved through the registry
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

Choreographed participants use the same registry and quotas
(`ChoreographyEngine(tenant_registry=...)`, default the configured one). A delivered
event of an unknown or suspended tenant is not handled but compensated. A transaction
counts as one saga of its tenant in each process handling it, and a delivery over the
quota waits instead of raising. See
[Choreography: Tenants](../patterns/choreography.md#tenants).

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

## Encryption at rest

Wrap the saga storage to encrypt each tenant's saga context and step results with that
tenant's own key (AES-256-GCM). Install the extra with `pip install 'sagaz[encryption]'`
(and `sagaz[aws]` for KMS).

```python
from sagaz.core.tenant.encryption import EncryptedSagaStorage, EnvKeyProvider

storage = EncryptedSagaStorage(PostgreSQLSagaStorage(url), EnvKeyProvider())
configure(SagaConfig(storage=storage, tenant_registry=registry))
```

Everything else stays the same: sagas run as before, and `load_saga_state` returns
plaintext.

**What is encrypted:** the saga `context` and every step `result`. **Stays in plaintext**,
because listing, statistics and cleanup need it: saga ids and names, statuses, step
names, step errors and timestamps, plus sagaz's own `__sagaz_*` records (the tenant
registry, so `sagaz tenant` works without keys). Outbox payloads are not encrypted,
since brokers and consumers read them; leave secrets out of event payloads.

### Key providers

| Provider | Keys | Notes |
|---|---|---|
| `EnvKeyProvider()` | `SAGAZ_TENANT_KEY_<TENANT>` per tenant, or one `SAGAZ_TENANT_MASTER_KEY` from which each tenant's key is derived (HKDF-SHA256) | Base64 32-byte keys. `<TENANT>` is the id upper-cased, with every character outside `A-Z0-9` replaced by `_` (`acme-eu` → `SAGAZ_TENANT_KEY_ACME_EU`) |
| `AwsKmsKeyProvider("alias/sagaz-{tenant_id}")` | One KMS key per tenant; data keys from `GenerateDataKey` | The encryption context `{"sagaz:tenant": <tenant>}` makes KMS refuse to unwrap a tenant's data key for another tenant |
| `VaultTransitKeyProvider(url, token)` | One Transit key per tenant (`sagaz-<tenant>`), data keys from `transit/datakey` | Defaults to `VAULT_ADDR` / `VAULT_TOKEN`. Create the keys yourself: `vault write -f transit/keys/sagaz-acme` |

Generate a key with `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`.

**Rotation (environment keys).** List several keys as `new-id:<key>,old-id:<key>`: the
first one encrypts, and all of them decrypt. Records are re-encrypted with the new key
the next time they are saved. With KMS or Vault, rotate the tenant's key in the service;
the stored wrapped data keys keep working.

**Failure is closed.** A tenant without a key cannot write: `TenantKeyError` is raised
and nothing is stored in plaintext. Each ciphertext is bound to its tenant, saga and
field, so one copied into another tenant's row raises `TenantDecryptionError` instead of
decrypting.

**Caching.** KMS and Vault data keys are reused for 5 minutes or 100,000 encryptions
(`data_key_ttl`, `max_key_uses`), and unwrapped keys are cached, so the key service is
called once per data key rather than once per record.

**Existing data.** Records written before encryption was enabled stay readable and are
encrypted the next time they are saved. `sagaz migrate` copies ciphertext as it is, so
the target needs the same keys; importing plaintext records through an
`EncryptedSagaStorage` encrypts them.

## Performance

Running sagas as many tenants instead of one costs little: see the
[multi-tenancy overhead benchmark](../benchmarks/tenancy-overhead.md) for measured
numbers on every backend, what PostgreSQL row-level security and the per-connection
`set_config` cost, and how to run the full 1000 tenants × 10 concurrent sagas
configuration yourself.
