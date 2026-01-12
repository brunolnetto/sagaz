# Storage Terminology - User-Friendly Naming

**Issue**: Current CLI uses "OLTP storage" - database jargon that confuses users.

**Solution**: Use domain terminology that matches what users are actually storing.

---

## Current Problem

```bash
# ❌ Current (confusing)
$ sagaz init

[2/9] Select OLTP storage (transaction data):
  1. postgresql
  2. in-memory
  3. sqlite

# Users ask:
# - "What is OLTP?"
# - "Is this different from OLAP?"
# - "Why do I need to know database theory?"
```

---

## Proposed Solution

Use **user-friendly** terminology based on **what** they're storing, not **how**.

### Storage Types

| Internal | User-Facing Term | What It Stores |
|----------|------------------|----------------|
| Saga storage | **Saga execution storage** | Saga state, step results, compensation |
| Outbox storage | **Outbox storage** | Pending events for publishing |
| Snapshot storage | **Saga history** | Read-only saga execution history |

---

## Correct CLI Flow

```bash
$ sagaz init

Welcome to Sagaz! Let's set up your project.

? Project name: my-saga-app

? Deployment type:
  > Local (Docker Compose)
    Kubernetes

? Saga execution storage:
  ℹ Where to store saga state and execution history
  
  > PostgreSQL (production-ready, recommended)
    In-memory (testing only, no persistence)
    SQLite (simple, file-based)

? Outbox storage:
  ℹ Where to store outbox events before publishing
  
  > Same as saga storage (simplest)
    Separate database (for analytics)
    Redis (high-performance cache)

? Outbox implementation:
  > Polling (simple, <5K events/sec)
    CDC (high-throughput, 50K+ events/sec)

? Message broker:
  > Kafka
    RabbitMQ
    Redis Streams
```

---

## Terminology Guide

### ✅ User-Friendly (Domain Language)

```bash
# Storage by purpose
--saga-storage=postgresql       # Where saga executions are stored
--outbox-storage=postgresql     # Where outbox events are stored  
--history-storage=postgresql    # Where saga history is stored (read-only)

# Configuration questions
"Where to store saga executions?"
"Where to store outbox events?"
"Enable saga history?"
```

### ❌ Technical Jargon (Database Theory)

```bash
# Avoid these terms in user-facing CLI
--oltp-storage=postgresql       # What is OLTP?
--olap-storage=clickhouse       # What is OLAP?
--transactional-storage=...     # Too vague

# Don't ask users
"Select OLTP storage"           # Database jargon
"Choose transactional backend"  # What does this mean?
"Configure write-optimized DB"  # Implementation detail
```

---

## CLI Implementation

### Interactive Wizard (Recommended)

```bash
$ sagaz init

Welcome to Sagaz!

? Project name: my-saga-app

? Deployment type:
  > Local (Docker Compose)
    Kubernetes

? Where to store saga executions?
  ℹ Saga state, step results, and compensation tracking
  
  > PostgreSQL (production-ready)
    In-memory (testing only)
    SQLite (simple, file-based)

? Where to store outbox events?
  ℹ Events waiting to be published to message broker
  
  > Same database (simplest)
    Separate database (for high volume)
    Redis (high-performance)

? Enable saga history?
  ℹ Read-only archive for auditing and analytics
  
  > No (keeps it simple)
    Yes, same database
    Yes, separate database (recommended for analytics)
```

### Non-Interactive (Flags)

```bash
# Clear, purpose-driven flags
sagaz init \
  --saga-storage=postgresql \
  --outbox-storage=postgresql \
  --history-enabled=false \
  --no-interactive
```

---

## Configuration File: `.sagaz-config.yml`

```yaml
version: 1.0
project_name: my-saga-app

# User-friendly storage configuration
storage:
  saga:
    type: postgresql
    url: postgresql://localhost:5432/saga_db
    
  outbox:
    type: postgresql
    url: postgresql://localhost:5432/saga_db  # Same as saga
    
  history:
    enabled: false
    # If enabled:
    # type: postgresql
    # url: postgresql://analytics-db:5432/saga_history

# Outbox configuration
outbox:
  mode: polling
  broker: kafka

# Internal implementation details (auto-configured)
infrastructure:
  database:
    # Note: Still uses optimized indexes for OLTP workload
    # User doesn't need to know this terminology
    connection_pool: transaction
    max_connections: 100
```

---

## Environment Variables

### User-Facing

```bash
# Clear purpose
export SAGA_STORAGE_URL=postgresql://localhost/saga_db
export OUTBOX_STORAGE_URL=postgresql://localhost/saga_db
export HISTORY_STORAGE_URL=postgresql://analytics/saga_history

# Storage types
export SAGA_STORAGE_TYPE=postgresql
export OUTBOX_STORAGE_TYPE=postgresql
```

### Internal (Advanced Users)

```bash
# Advanced tuning (documented in advanced guide)
export SAGA_DB_POOL_MODE=transaction      # OLTP optimization
export SAGA_DB_MAX_CONNECTIONS=100
export SAGA_DB_STATEMENT_TIMEOUT=30s
```

---

## Documentation Terminology

### In User Docs

✅ Use:
- "Saga execution storage" or "Saga storage"
- "Outbox event storage" or "Outbox storage"
- "Saga history" or "Saga archive"
- "Where to store saga executions?"

❌ Avoid:
- "OLTP storage"
- "OLAP storage"
- "Transactional database"
- "Write-optimized database"

### In Technical Docs

✅ Use (but explain):
- "Saga storage (OLTP-optimized for transactions)"
- "History storage (OLAP-optimized for analytics)"
- Note: Explain OLTP/OLAP in glossary

### In Architecture Diagrams

```
┌─────────────────────────────────────────┐
│         Saga Execution Storage          │
│      (PostgreSQL, OLTP-optimized)       │
│                                         │
│  • Saga state                          │
│  • Step execution results              │
│  • Compensation tracking               │
│  • Outbox events (transactional)       │
└─────────────────────────────────────────┘
          │
          │ (optional replication)
          ▼
┌─────────────────────────────────────────┐
│          Saga History Storage           │
│      (PostgreSQL, OLAP-optimized)       │
│                                         │
│  • Completed sagas (read-only)         │
│  • Analytics and reporting             │
│  • Audit trail                         │
└─────────────────────────────────────────┘
```

---

## Migration from Current Code

### Changes Needed

**1. CLI Prompts (`sagaz/cli/app.py`)**

```python
# Before
click.echo("[2/9] Select OLTP storage (transaction data):")

# After  
click.echo("[2/9] Where to store saga executions?")
click.echo("    ℹ Saga state, step results, and compensation tracking")
```

**2. Flag Names**

```python
# Before
@click.option('--oltp-storage', type=click.Choice(['postgresql', 'sqlite', 'in-memory']))

# After
@click.option('--saga-storage', type=click.Choice(['postgresql', 'sqlite', 'in-memory']),
              help='Where to store saga executions')
```

**3. Configuration Keys**

```python
# Before
config["oltp_storage"]

# After
config["saga_storage"]
```

---

## Rationale

| Aspect | Explanation |
|--------|-------------|
| **Clarity** | "Saga storage" tells you **what** it stores |
| **Simplicity** | No need to understand OLTP/OLAP concepts |
| **Discoverability** | User can guess what "--saga-storage" means |
| **Future-proof** | Can add --history-storage without confusion |
| **Consistency** | Matches "outbox storage", "saga execution" terminology |

---

## Comparison

### ❌ Database-Centric (Current)

```
User mental model:
"I need to choose between OLTP and OLAP databases"
↓
User confused: "What's the difference? I just want to store my sagas"
```

### ✅ Domain-Centric (Proposed)

```
User mental model:
"Where do I want to store my saga executions?"
↓
User understands: "PostgreSQL for production, in-memory for testing"
```

---

## Implementation Checklist

- [ ] Update CLI prompts to use "saga storage" instead of "OLTP storage"
- [ ] Rename `--oltp-storage` flag to `--saga-storage`
- [ ] Update config keys: `oltp_storage` → `saga_storage`
- [ ] Update environment variables: `OLTP_*` → `SAGA_STORAGE_*`
- [ ] Update documentation to avoid OLTP/OLAP jargon
- [ ] Add glossary entry explaining OLTP/OLAP for advanced users
- [ ] Update CLI help text to be user-friendly
- [ ] Update `.sagaz-config.yml` schema

---

## See Also

- [CLI Naming Convention](CLI_NAMING_CONVENTION.md) - Why "outbox" not "CDC"
- [CLI Correct API](CLI_CORRECT_API.md) - Interactive-first design
- This follows same principle: **domain language** over **implementation details**

---

**Key Principle**: CLI uses domain terminology (saga, outbox), not database theory (OLTP, OLAP).
