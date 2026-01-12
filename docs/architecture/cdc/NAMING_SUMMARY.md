# Sagaz Naming Conventions - Complete Guide

**Principle**: Use **domain language** (what users care about), not **implementation details** (how it works internally).

---

## Quick Reference

| Feature | ❌ Avoid (Technical) | ✅ Use (Domain) |
|---------|---------------------|-----------------|
| **Outbox** | `--cdc-mode`, `--enable-cdc` | `--outbox-mode`, `--enable-outbox-cdc` |
| **Storage** | `--oltp-storage`, `--olap-storage` | `--saga-storage`, `--outbox-storage` |
| **Broker** | `--cdc-broker` | `--outbox-broker` |
| **Workers** | `CDC workers` | `Outbox workers (CDC mode)` |
| **Commands** | `sagaz init --cdc-mode=cdc` | `sagaz init` (interactive) |

---

## Complete Naming Conventions

### 1. Outbox Pattern

**What**: Reliable event publishing pattern  
**Implementation**: CDC (Change Data Capture) via Debezium

| Avoid | Use | Why |
|-------|-----|-----|
| `--cdc-mode` | `--outbox-mode` | CDC is implementation, outbox is feature |
| `--cdc-broker` | `--outbox-broker` | User configures outbox, not CDC directly |
| `--enable-cdc` | `--enable-outbox-cdc` | Clarifies you're upgrading outbox pattern |
| `CDC_STREAM_NAME` | `OUTBOX_STREAM_NAME` | Stream contains outbox events |
| `sagaz init --cdc-mode=cdc` | `sagaz init` (interactive) | Don't require flags |

**CLI Examples:**
```bash
# ✅ Correct
sagaz init                                  # Interactive wizard
sagaz init --outbox-mode=cdc --no-interactive
sagaz extend --enable-outbox-cdc --hybrid

# ❌ Wrong
sagaz init --cdc-mode=cdc                   # Exposes implementation
sagaz extend --enable-cdc                   # Unclear what this is
```

---

### 2. Storage

**What**: Where saga data is stored  
**Implementation**: PostgreSQL (OLTP-optimized), potentially separate analytics DB (OLAP)

| Avoid | Use | Why |
|-------|-----|-----|
| `--oltp-storage` | `--saga-storage` | OLTP is database jargon |
| `--olap-storage` | `--history-storage` | OLAP is database jargon |
| "transactional storage" | "saga execution storage" | Vague vs specific |
| `OLTP_DB_URL` | `SAGA_STORAGE_URL` | Clear purpose |

**CLI Examples:**
```bash
# ✅ Correct
? Where to store saga executions?
  > PostgreSQL (production-ready)
    In-memory (testing only)
    SQLite (simple)

? Enable saga history?
  > No
    Yes (same database)
    Yes (separate database for analytics)

# ❌ Wrong
? Select OLTP storage (transaction data):
? Enable OLAP storage?
```

---

### 3. Environment Variables

| Component | ❌ Avoid | ✅ Use |
|-----------|---------|-------|
| **Saga** | `OLTP_STORAGE_URL` | `SAGA_STORAGE_URL` |
| **Outbox mode** | `OUTBOX_WORKER_MODE` | `SAGAZ_OUTBOX_MODE` |
| **Outbox stream** | `CDC_STREAM_NAME` | `OUTBOX_STREAM_NAME` |
| **Broker** | `CDC_BROKER` | `SAGAZ_OUTBOX_BROKER` |
| **History** | `OLAP_STORAGE_URL` | `SAGA_HISTORY_URL` |

**Example `.env`:**
```bash
# ✅ Correct - User-friendly
SAGA_STORAGE_URL=postgresql://localhost/saga_db
OUTBOX_STORAGE_URL=postgresql://localhost/saga_db
SAGAZ_OUTBOX_MODE=cdc
OUTBOX_STREAM_NAME=saga.outbox.events
SAGAZ_OUTBOX_BROKER=kafka

# ❌ Wrong - Implementation details
OLTP_URL=postgresql://localhost/saga_db
CDC_MODE=enabled
CDC_STREAM=saga.outbox.events
```

---

### 4. CLI Commands

| Command | Design | Examples |
|---------|--------|----------|
| `sagaz init` | **Interactive by default** | `sagaz init` (runs wizard) |
| `sagaz extend` | **Interactive with confirmation** | `sagaz extend --enable-outbox-cdc` |
| `sagaz status` | **Shows domain concepts** | `Outbox Mode: CDC` not `CDC: Enabled` |
| `sagaz validate` | **Validates domain** | `Outbox lag: 12ms` not `CDC lag: 12ms` |

---

### 5. Status Output

```bash
# ✅ Correct - Domain language
$ sagaz status

Sagaz Project Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Storage:
  Saga executions:  PostgreSQL (localhost:5432)
  Outbox events:    PostgreSQL (same)
  History:          Disabled

Outbox:
  Mode:             CDC (Kafka)
  Workers:          5 active
  Throughput:       48,000 events/sec
  Lag:              12ms

Broker:
  Type:             Kafka
  Endpoints:        kafka:9092
  Status:           ✓ Connected

Debezium:
  Status:           ✓ Running
  Connector:        sagaz-outbox
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

```bash
# ❌ Wrong - Technical jargon
$ sagaz status

OLTP Storage:     PostgreSQL
OLAP Storage:     Disabled
CDC Mode:         Enabled
CDC Stream:       Running
```

---

### 6. Configuration File

```yaml
# ✅ Correct - .sagaz-config.yml
version: 1.0
project_name: my-saga-app

# Domain-focused configuration
storage:
  saga:
    type: postgresql
    url: postgresql://localhost/saga_db
  
  outbox:
    type: postgresql
    url: postgresql://localhost/saga_db
  
  history:
    enabled: false

outbox:
  mode: cdc              # polling | cdc | hybrid
  broker: kafka

# Implementation details (auto-configured)
infrastructure:
  database:
    pool_mode: transaction    # OLTP optimization (internal)
  
  debezium:
    enabled: true
    connector: sagaz-outbox
```

```yaml
# ❌ Wrong
oltp:
  type: postgresql

cdc:
  enabled: true
  mode: debezium
```

---

### 7. Documentation Terminology

#### User-Facing Docs

**✅ Use:**
- "Saga storage" or "Saga execution storage"
- "Outbox pattern" or "Outbox storage"
- "Saga history" or "Saga archive"
- "Outbox mode: polling or CDC"
- "Message broker" or "Event broker"

**❌ Avoid:**
- "OLTP storage"
- "OLAP storage"  
- "CDC pipeline"
- "Transactional outbox CDC implementation"
- "WAL-based replication"

#### Technical/Architecture Docs

**✅ Use (with explanation):**
- "Saga storage (OLTP-optimized for high write throughput)"
- "History storage (OLAP-optimized for analytics queries)"
- "CDC implementation of outbox pattern via Debezium"
- "PostgreSQL logical replication (WAL streaming)"

**Note**: Always explain acronyms on first use.

---

## Rationale by Category

### Outbox → CDC

**Why**: CDC (Change Data Capture) is a database technique. Users don't need to know database internals. They're configuring the **outbox pattern**, which happens to use CDC for performance.

**Analogy**: You don't say "HTTP/2 server", you say "web server that uses HTTP/2"

### OLTP → Saga Storage

**Why**: OLTP (Online Transaction Processing) is database theory. Users want to know **where their sagas are stored**, not what database optimization technique is used.

**Analogy**: You don't ask users "Choose ACID-compliant storage", you ask "Where to store your data?"

### Interactive First

**Why**: CLI tools should be beginner-friendly by default. Advanced users can use flags, but beginners get guided through setup.

**Examples**: `npm init`, `create-react-app`, `rails new` - all interactive by default.

---

## Implementation Priority

| Component | Priority | Effort | Status |
|-----------|----------|--------|--------|
| Outbox CLI naming | High | 4 hours | ✅ Documented |
| Storage CLI naming | High | 2 hours | ✅ Documented |
| Interactive init | High | 8 hours | 📋 Planned |
| Environment variables | Medium | 2 hours | 📋 Planned |
| Documentation update | High | 4 hours | 📋 Planned |

**Total**: ~20 hours

---

## Checklist for Contributors

When adding new features:

- [ ] Use domain terminology in CLI flags
- [ ] Make commands interactive by default
- [ ] Provide `--no-interactive` for automation
- [ ] Use clear help text (no jargon)
- [ ] Namespace environment variables (`SAGAZ_*`)
- [ ] Document acronyms (OLTP, OLAP, CDC) in glossary
- [ ] Test with non-technical users
- [ ] Update this guide if adding new terminology

---

## Resources

- [CLI Naming Convention](CLI_NAMING_CONVENTION.md) - Outbox terminology
- [Storage Naming](STORAGE_NAMING.md) - Saga storage terminology
- [CLI Correct API](CLI_CORRECT_API.md) - Interactive design
- [CLI Examples](CLI_EXAMPLES.md) - Usage examples

---

**Key Principle**: If your grandma wouldn't understand the term, use a simpler one.

**Examples**:
- ✅ "Where to store saga executions?" - Clear
- ❌ "Select OLTP storage backend" - Jargon
- ✅ "Outbox mode: polling or CDC" - Feature-focused
- ❌ "Enable Debezium WAL replication" - Implementation detail
