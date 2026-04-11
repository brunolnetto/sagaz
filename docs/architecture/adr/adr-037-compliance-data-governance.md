# ADR-037: Compliance & Data Governance

## Status

**Accepted** — ✅ **FULLY IMPLEMENTED** (v2.1.0)

## Context

Sagaz persists saga execution state — including step inputs, outputs, and
compensation results — in snapshot storage to enable replay and time-travel
debugging (see ADR-024).  This persistence raises data-governance concerns in
regulated environments:

| Concern | Regulation / Requirement |
|---------|--------------------------|
| Sensitive fields stored in plaintext | Financial, healthcare, PII data |
| Right to erasure | GDPR Article 17 |
| Replay operations executed by arbitrary callers | Internal security policy |
| No record of who accessed or modified saga state | Audit requirements (SOC 2, ISO 27001) |

Without built-in governance controls, users were forced to implement these
concerns outside the library, often inconsistently, or avoid using replay
entirely in regulated contexts.

## Decision

Add an opt-in `ComplianceManager` in `sagaz/core/compliance.py`, configured
via `ComplianceConfig` and attached to the replay infrastructure.  The feature
set covers four independent pillars:

### 1. Context Encryption

Sensitive fields are identified by heuristic key matching (configurable
patterns such as `ssn`, `card_number`, `password`).  Matching values are
encrypted before being written to snapshot storage and decrypted transparently
on read.

```python
compliance = ComplianceConfig(
    enable_encryption=True,
    encryption_key="...",   # Use a KMS-backed key in production
)
```

> **Note**: The shipped `_simple_encrypt` XOR implementation is intentionally
> minimal.  Production deployments must replace it with a proper cipher
> (AES-256-GCM via the `cryptography` package or a KMS envelope).  The
> interface is stable; the backend is swappable.

### 2. GDPR Right to Erasure

`ComplianceManager.delete_user_data(user_id)` deletes all saga snapshots
associated with a given user from the configured `SnapshotStorage`.  This
satisfies GDPR Article 17 without requiring operators to write custom deletion
scripts.

```python
await manager.delete_user_data(user_id="u-123456")
```

A `retention_days` ceiling (default 7 years / 2555 days) is enforced at the
storage layer; snapshots older than the threshold are eligible for automated
pruning.

### 3. Access Control

`AccessLevel` defines four roles with progressive permissions:

```
READ    → view snapshots and history
REPLAY  → execute replay operations
DELETE  → delete snapshots (GDPR)
ADMIN   → full access
```

`ComplianceManager.check_access(user_id, required_level)` enforces the
minimum access level before sensitive replay operations proceed.

```python
if not manager.check_access(user_id, AccessLevel.REPLAY):
    raise PermissionError("replay not authorized")
```

### 4. Audit Trail

`ComplianceManager.create_audit_log(operation, user_id, saga_id, details)`
writes a timestamped, structured audit record.  When `log_all_operations=True`
(default), every compliance-protected operation is recorded automatically.

`anonymize_context(context)` replaces sensitive field values with their
SHA-256 hash, enabling audit records to reference context shapes without
storing raw data.

## Alternatives Considered

### A: External Authorization Service

Delegate access decisions to an external policy engine (OPA, Casbin).
Rejected for v1: adds a network dependency; the built-in role model covers
the primary use cases.  The `check_access` interface is designed for
drop-in replacement if a richer policy engine is needed later.

### B: Transparent Encryption at the Storage Layer

Encrypt entire snapshot blobs rather than individual fields.  Rejected:
field-level encryption allows legitimate observability tooling to inspect
non-sensitive fields without decryption keys, which is valuable for
incident response.

### C: Require Users to Encrypt Before Storing

Shift responsibility entirely to the caller.  Rejected: inconsistent
implementations across teams create compliance gaps, and replay tooling
needs to understand encryption metadata to round-trip contexts correctly.

## Consequences

### Positive

- Saga replay is now usable in GDPR, HIPAA, PCI-DSS, and SOC 2 environments.
- All four pillars are independently opt-in — adding compliance to an existing
  deployment requires only a `ComplianceConfig` with the relevant flags set.
- Audit trail is structured (dict, not free-text) and suitable for ingestion
  into SIEM tooling.
- Anonymisation preserves referential integrity via deterministic hashing.

### Negative

- The default encryption implementation is intentionally weak; operators must
  replace it before enabling encryption in production.  The documentation makes
  this explicit.
- Access control is in-process; a compromised process bypasses it.  For
  network-boundary enforcement, an external gateway is still required.
- Retention enforcement relies on the storage backend implementing
  `prune_snapshots`; not all backends do (e.g. in-memory).

## Implementation Reference

| File | Purpose |
|------|---------|
| `sagaz/core/compliance.py` | `ComplianceConfig`, `ComplianceManager`, `AccessLevel` |
| `sagaz/core/replay.py` | Wires `ComplianceManager` into replay pipeline |
| `sagaz/core/context.py` | `ExternalStorage` supports encrypted artefact URIs |
| `sagaz/storage/interfaces/snapshot.py` | `SnapshotStorage.prune_snapshots` used by GDPR deletion |

## Links

- [ADR-024: Saga Replay & Time-Travel](adr-024-saga-replay.md)
- [ADR-021: Lightweight Context Streaming](adr-021-lightweight-context-streaming.md)
- [ADR-016: Unified Storage Layer](adr-016-unified-storage-layer.md)
