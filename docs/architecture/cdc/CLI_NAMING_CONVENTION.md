# CLI Naming Convention - Outbox Pattern

**Principle**: CLI flags should use domain terminology (`outbox`), not implementation details (`cdc`).

---

## Rationale

CDC (Change Data Capture) is an **implementation detail** of the outbox pattern. Users interact with the **outbox pattern**, not directly with CDC infrastructure.

**Example analogy:**
- ❌ Bad: `--enable-postgresql-replication` (implementation detail)
- ✅ Good: `--enable-outbox-cdc` (feature name)

---

## Naming Rules

### ✅ Correct (Outbox-centric)

```bash
# Flags use "outbox" terminology
sagaz init --outbox-mode=polling
sagaz init --outbox-mode=cdc
sagaz init --outbox-broker=kafka

# Extension uses full "outbox-cdc" for clarity
sagaz extend --enable-outbox-cdc

# Status shows outbox state
sagaz status
  Outbox Mode: CDC
  Outbox Broker: Kafka

# Environment variables namespace under SAGAZ_OUTBOX_*
export SAGAZ_OUTBOX_MODE=cdc
export OUTBOX_STREAM_NAME=saga.outbox.events
export OUTBOX_CONSUMER_GROUP=sagaz-workers
```

### ❌ Incorrect (CDC-centric)

```bash
# Don't expose CDC in basic flags
sagaz init --cdc-mode=cdc              # Too technical
sagaz init --cdc-broker=kafka          # Exposes implementation

# Don't use bare "cdc" for extension
sagaz extend --enable-cdc              # Unclear what this is

# Don't use CDC terminology in status
sagaz status
  CDC Mode: Enabled                    # Confusing to users

# Don't use CDC-prefixed env vars for public API
export CDC_MODE=cdc                    # Not namespaced
export CDC_STREAM_NAME=...             # Implementation detail
```

---

## Complete CLI API

### `sagaz init`

```bash
sagaz init [OPTIONS]

Options:
  --outbox-mode TEXT      Outbox implementation: polling|cdc|hybrid
                          (default: polling)
  
  --outbox-broker TEXT    Message broker: kafka|redis|rabbitmq
                          (default: kafka)
  
  --local                 Docker Compose setup
  --k8s                   Kubernetes manifests
  
Examples:
  # Default: polling mode
  sagaz init --local
  
  # High-throughput: CDC mode
  sagaz init --local --outbox-mode=cdc --outbox-broker=kafka
  
  # Hybrid mode for migration
  sagaz init --local --outbox-mode=hybrid --outbox-broker=kafka
```

### `sagaz extend`

```bash
sagaz extend [OPTIONS]

Options:
  --enable-outbox-cdc     Upgrade outbox to CDC implementation
  --outbox-broker TEXT    Message broker: kafka|redis|rabbitmq
  --hybrid                Run both polling and CDC workers
  --remove-polling        Remove polling workers (CDC-only)
  
Examples:
  # Upgrade to CDC in hybrid mode
  sagaz extend --enable-outbox-cdc --outbox-broker=kafka --hybrid
  
  # Direct upgrade to CDC
  sagaz extend --enable-outbox-cdc --outbox-broker=redis
  
  # Complete migration: remove polling
  sagaz extend --remove-polling
```

### `sagaz status`

```bash
$ sagaz status

Sagaz Project Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Outbox:
  Mode:            CDC (Kafka)
  Workers:         5 active
  Throughput:      12,500 events/sec
  Lag:             12ms
  Pending:         47 events

Broker:
  Type:            Kafka
  Endpoints:       kafka:9092
  Status:          ✓ Connected

Debezium:
  Status:          ✓ Running
  Connector:       sagaz-outbox
  Lag:             12ms
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### `sagaz validate`

```bash
$ sagaz validate

Validating Outbox Configuration...

✓ Outbox mode: CDC
✓ PostgreSQL WAL level: logical
✓ Broker connection: kafka:9092
✓ Debezium connector: Running
✗ Outbox lag: 1500ms (threshold: 1000ms)

Recommendations:
  - Scale up outbox workers:
    kubectl scale deployment/outbox-worker --replicas=10
```

---

## Environment Variables

### Public API (User-facing)

```bash
# Outbox mode
export SAGAZ_OUTBOX_MODE=polling     # polling | cdc | hybrid

# Broker configuration
export SAGAZ_OUTBOX_BROKER=kafka     # kafka | redis | rabbitmq
export BROKER_URL=kafka:9092

# Outbox worker settings
export OUTBOX_BATCH_SIZE=100
export OUTBOX_POLL_INTERVAL=1.0
export OUTBOX_MAX_RETRIES=10

# CDC-specific (when mode=cdc)
export OUTBOX_STREAM_NAME=saga.outbox.events
export OUTBOX_CONSUMER_GROUP=sagaz-outbox-workers
```

### Internal (Implementation details)

```bash
# Debezium (users typically don't set these)
export DEBEZIUM_CONNECTOR_NAME=sagaz-outbox
export DEBEZIUM_SNAPSHOT_MODE=initial

# CDC tuning (advanced users only)
export CDC_LAG_THRESHOLD_MS=1000
export CDC_BATCH_SIZE=100
```

---

## Configuration File: `.sagaz-config.yml`

```yaml
version: 1.0
project_name: myproject

# User-facing configuration
outbox:
  mode: cdc                    # polling | cdc | hybrid
  broker: kafka                # kafka | redis | rabbitmq
  
  workers:
    polling:
      enabled: false
      replicas: 0
    cdc:
      enabled: true
      replicas: 5

# Implementation details (auto-generated)
infrastructure:
  debezium:
    version: "2.4"
    connector: sagaz-outbox
    config_file: debezium/kafka.properties
  
  broker:
    type: kafka
    endpoints:
      - kafka:9092
```

---

## User Journey Examples

### New User (Simple)

```bash
# User doesn't need to know about CDC
$ sagaz init --local

✓ Generated configuration
✓ Outbox mode: polling (default)

# Later, when they need more throughput
$ sagaz extend --enable-outbox-cdc --outbox-broker=kafka

✓ Upgraded outbox to CDC implementation
```

### Advanced User (CDC from start)

```bash
# User knows they need high throughput
$ sagaz init --local --outbox-mode=cdc --outbox-broker=kafka

✓ Outbox mode: CDC
✓ Broker: Kafka
✓ Debezium: Configured
```

### Migration User (Safe Upgrade)

```bash
# User wants zero-downtime migration
$ sagaz extend --enable-outbox-cdc --outbox-broker=kafka --hybrid

✓ Hybrid mode enabled
✓ Polling workers: 3 (existing)
✓ CDC workers: 5 (new)

# Monitor for a while...
$ sagaz status
Outbox Mode: Hybrid
Workers: 3 polling, 5 CDC

# Complete migration
$ sagaz extend --remove-polling

✓ Outbox mode: CDC (polling removed)
```

---

## Why This Naming?

| Aspect | Explanation |
|--------|-------------|
| **Abstraction** | "Outbox" is the feature, "CDC" is how it's implemented |
| **Consistency** | All flags use `--outbox-*` prefix |
| **Clarity** | `--enable-outbox-cdc` clearly says "upgrade outbox to CDC" |
| **Future-proof** | Can add `--outbox-mode=kafka-streams` without breaking API |
| **User-friendly** | Beginners don't need to understand CDC internals |

---

## Comparison

### ❌ Implementation-focused (Bad)

```bash
sagaz init --cdc-mode=cdc
sagaz extend --enable-cdc

# Exposes too much internal detail
# User must understand CDC, Debezium, WAL, etc.
```

### ✅ Feature-focused (Good)

```bash
sagaz init --outbox-mode=cdc
sagaz extend --enable-outbox-cdc

# User understands they're configuring the outbox pattern
# CDC is mentioned as the implementation choice
```

---

## Documentation Terminology

### In User-Facing Docs

✅ Use:
- "Outbox pattern"
- "Outbox mode: polling or CDC"
- "Upgrade outbox to CDC implementation"
- "Configure outbox broker"

❌ Avoid:
- "Enable CDC" (what is CDC?)
- "CDC configuration" (too technical)
- "Change Data Capture setup" (jargon)

### In Technical Docs

✅ Use:
- "CDC implementation of outbox pattern"
- "Debezium connector for outbox table"
- "PostgreSQL logical replication for CDC"

---

## See Also

- [CLI Integration](CLI_INTEGRATION.md) - Full CLI design
- [ADR-011](../adr/adr-011-cdc-support.md) - Technical details
- User docs should say "outbox", technical docs can say "CDC"

---

**Key Principle**: The CLI is user-facing, so it uses domain language (outbox), not implementation details (CDC).
