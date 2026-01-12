# CDC CLI Integration Design

**Related**: [ADR-011: CDC Support](docs/architecture/adr/adr-011-cdc-support.md)

## Overview

CDC should be seamlessly integrated into the Sagaz CLI for turnkey setup and graceful migration.

---

## User Journeys

### Journey 1: New Project with CDC

```bash
# User wants CDC from day one
$ sagaz init --local --outbox-mode=cdc --outbox-broker=kafka

✓ Generated docker-compose.yml (PostgreSQL + Kafka + Debezium)
✓ Generated debezium/kafka.properties
✓ Generated .env (SAGAZ_OUTBOX_MODE=cdc)
✓ Generated k8s/debezium-server.yaml
✓ Generated k8s/outbox-worker.yaml

Project initialized with CDC mode!

Next steps:
  1. Start services: docker-compose up -d
  2. Run your saga: python my_saga.py
  3. Monitor: sagaz status
```

### Journey 2: Migrate Existing Project to CDC

```bash
# User has polling mode, wants to upgrade
$ sagaz extend --enable-outbox-cdc --outbox-broker=kafka --hybrid

✓ Detected polling mode setup
✓ Backed up to .sagaz-backup/
✓ Added Debezium to docker-compose.yml
✓ Generated debezium/kafka.properties
✓ Generated k8s/outbox-worker-cdc.yaml (5 replicas)
✓ Updated .env (kept polling workers running)

Migration to hybrid mode complete!

Current setup:
  - 3 polling workers (existing)
  - 5 CDC workers (new)
  - Debezium Server (new)

Next steps:
  1. Start Debezium: docker-compose up -d debezium-server
  2. Monitor: sagaz status
  3. When ready: sagaz extend --remove-polling
```

### Journey 3: Complete Cutover

```bash
# User has verified CDC is working, remove polling
$ sagaz status
Outbox Mode:       Hybrid (polling + CDC)
Workers:           3 polling, 5 cdc
CDC Throughput:    15,000 events/sec (stable)
CDC Lag:           8ms

$ sagaz extend --remove-polling

⚠ This will remove polling workers. CDC workers must be healthy.

? Are you sure? [y/N]: y

✓ Scaled down polling workers (replicas=0)
✓ Updated docker-compose.yml
✓ Updated .env (SAGAZ_OUTBOX_MODE=cdc)

Cutover complete! Now running CDC-only.
```

---

## CLI Commands

### `sagaz init`

```
Usage: sagaz init [OPTIONS]

  Initialize a new Sagaz project with customizable outbox mode.

Options:
  --local              Generate Docker Compose setup (default)
  --k8s                Generate Kubernetes manifests
  --outbox-mode TEXT      Outbox mode: polling|cdc|hybrid (default: polling)
  --outbox-broker TEXT    CDC broker: kafka|redis|rabbitmq (required if cdc)
  --project-name TEXT  Project name (default: current directory name)
  --help               Show this message and exit

Examples:
  # Simple polling mode (default)
  sagaz init --local
  
  # CDC with Kafka
  sagaz init --local --outbox-mode=cdc --outbox-broker=kafka
  
  # CDC with Redis Streams
  sagaz init --local --outbox-mode=cdc --outbox-broker=redis
  
  # Kubernetes with CDC
  sagaz init --k8s --outbox-mode=cdc --outbox-broker=kafka
  
  # Hybrid mode (both polling + CDC from start)
  sagaz init --local --outbox-mode=hybrid --outbox-broker=kafka
```

### `sagaz extend`

```
Usage: sagaz extend [OPTIONS]

  Extend an existing Sagaz project with new capabilities.

Options:
  --enable-outbox-cdc         Add CDC support to existing project
  --outbox-broker TEXT    CDC broker: kafka|redis|rabbitmq
  --hybrid             Run in hybrid mode (recommended for migration)
  --remove-polling     Remove polling workers (CDC-only mode)
  --no-backup          Skip backing up existing files
  --dry-run            Show what would be changed without modifying files
  --help               Show this message and exit

Examples:
  # Add CDC in hybrid mode (safe migration)
  sagaz extend --enable-outbox-cdc --outbox-broker=kafka --hybrid
  
  # Add CDC directly (no hybrid)
  sagaz extend --enable-outbox-cdc --outbox-broker=redis
  
  # Remove polling after CDC is stable
  sagaz extend --remove-polling
  
  # See what would change
  sagaz extend --enable-outbox-cdc --outbox-broker=kafka --dry-run
```

### `sagaz status`

```
Usage: sagaz status [OPTIONS]

  Display current status of Sagaz infrastructure.

Options:
  --watch              Refresh status every 5 seconds
  --json               Output as JSON
  --help               Show this message and exit

Example output:

  $ sagaz status

  Sagaz Project Status
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Outbox Mode:       CDC (Kafka)
  Workers:           5 CDC workers
  Debezium:          ✓ Running
  CDC Lag:           12ms
  Pending Events:    47
  Throughput:        12,500 events/sec
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  
  Services:
    ✓ PostgreSQL        localhost:5432
    ✓ Kafka             localhost:9092
    ✓ Debezium Server   Running (1 replica)
    ✓ Outbox Workers    5 running (cdc mode)
    ✓ Prometheus        localhost:9090
  
  Run 'sagaz logs' to view worker logs
  Run 'sagaz validate' to check configuration
```

### `sagaz validate`

```
Usage: sagaz validate [OPTIONS]

  Validate Sagaz configuration and health.

Options:
  --fix                Attempt to fix issues automatically
  --strict             Fail on warnings
  --help               Show this message and exit

Example output:

  $ sagaz validate

  Validating Sagaz Configuration...

  ✓ PostgreSQL connection: OK
  ✓ PostgreSQL WAL level: logical (OK for CDC)
  ✓ Kafka broker: OK
  ✓ Debezium Server: Running
  ✓ Replication slot: sagaz_cdc (OK)
  ✗ CDC lag too high: 5000ms (threshold: 1000ms)
  ⚠ Polling workers still running (consider scaling down)

  Errors: 1
  Warnings: 1

  Recommendations:
    - Scale up CDC workers:
      kubectl scale deployment/outbox-worker-cdc --replicas=10
    
    - Check Debezium logs:
      docker-compose logs debezium-server
    
    - Scale down polling workers:
      kubectl scale deployment/outbox-worker-polling --replicas=0

  Run 'sagaz validate --fix' to apply recommendations
```

---

## Generated Files

### Polling Mode (`sagaz init --local`)

```
myproject/
├── docker-compose.yml
├── .env
├── .sagaz-config.yml
├── k8s/
│   └── outbox-worker.yaml
└── README.md
```

### CDC Mode (`sagaz init --local --outbox-mode=cdc --outbox-broker=kafka`)

```
myproject/
├── docker-compose.yml          # Includes Debezium service
├── debezium/
│   └── kafka.properties        # Debezium config
├── .env                        # CDC env vars
├── .sagaz-config.yml           # Project metadata
├── k8s/
│   ├── debezium-server.yaml
│   └── outbox-worker.yaml      # CDC mode
└── README.md
```

### After `sagaz extend --enable-outbox-cdc --hybrid`

```
myproject/
├── docker-compose.yml          # Updated (added Debezium)
├── debezium/
│   └── kafka.properties        # NEW
├── .env                        # Updated (added CDC vars)
├── .sagaz-backup/              # Backup of original files
│   ├── docker-compose.yml
│   └── .env
├── .sagaz-config.yml           # Updated (mode=hybrid)
├── k8s/
│   ├── debezium-server.yaml            # NEW
│   ├── outbox-worker-polling.yaml      # Existing
│   └── outbox-worker-cdc.yaml          # NEW
└── README.md
```

---

## Configuration File: `.sagaz-config.yml`

The CLI tracks project state:

```yaml
version: 1.0
project_name: myproject
outbox_mode: hybrid  # polling | cdc | hybrid

cdc:
  enabled: true
  broker: kafka
  debezium:
    version: "2.4"
    config_file: debezium/kafka.properties

workers:
  polling:
    enabled: true
    replicas: 3
  cdc:
    enabled: true
    replicas: 5

infrastructure:
  local: docker-compose
  k8s:
    namespace: sagaz

created_at: "2026-01-12T12:00:00Z"
last_extended: "2026-01-12T12:30:00Z"
```

---

## Interactive Wizard

For users who prefer guided setup:

```bash
$ sagaz init

Welcome to Sagaz! Let's set up your project.

? Project name: my-saga-project
? Deployment mode:
  > Local (Docker Compose)
    Kubernetes

? Outbox mode:
  > Polling (simple, recommended for <5K events/sec)
    CDC (high-throughput, requires Debezium)
    Hybrid (both modes, for migration)

? Select message broker:
  > Kafka
    RabbitMQ
    Redis Streams

? Enable monitoring (Prometheus + Grafana)?
  > Yes
    No

✓ Generating project files...
✓ Created docker-compose.yml
✓ Created .env
✓ Created k8s/ manifests
✓ Created README.md

Project initialized successfully!

Next steps:
  1. cd my-saga-project
  2. docker-compose up -d
  3. python examples/simple_saga.py
  4. sagaz status

For detailed documentation, see:
  README.md
  docs.sagaz.io/quickstart
```

---

## Template Rendering

The CLI uses Jinja2 templates:

```python
# sagaz/cli/templates.py
from jinja2 import Environment, PackageLoader

env = Environment(loader=PackageLoader('sagaz', 'templates'))

def render_docker_compose(mode: str, broker: str):
    template = env.get_template(f'init/{mode}/docker-compose.yml.j2')
    return template.render(broker=broker)

def render_debezium_config(broker: str):
    template = env.get_template(f'init/cdc/debezium/{broker}.properties.j2')
    return template.render()
```

---

## Validation Logic

```python
# sagaz/cli/validate.py
from dataclasses import dataclass
from enum import Enum

class Severity(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"

@dataclass
class ValidationResult:
    check: str
    severity: Severity
    message: str
    recommendation: str | None = None

async def validate_cdc_setup() -> list[ValidationResult]:
    results = []
    
    # Check PostgreSQL WAL level
    wal_level = await check_postgres_wal_level()
    if wal_level != "logical":
        results.append(ValidationResult(
            check="PostgreSQL WAL level",
            severity=Severity.ERROR,
            message=f"WAL level is '{wal_level}', should be 'logical'",
            recommendation="Set wal_level=logical in postgresql.conf"
        ))
    
    # Check CDC lag
    lag_ms = await get_cdc_lag()
    if lag_ms > 1000:
        results.append(ValidationResult(
            check="CDC lag",
            severity=Severity.ERROR,
            message=f"CDC lag is {lag_ms}ms (threshold: 1000ms)",
            recommendation="Scale up CDC workers or check Debezium health"
        ))
    
    return results
```

---

## Benefits Summary

| Benefit | Description |
|---------|-------------|
| ✅ **Zero-config CDC** | `sagaz init --outbox-mode=cdc` handles everything |
| ✅ **Safe migration** | `--hybrid` mode allows parallel running |
| ✅ **Automatic validation** | `sagaz validate` catches misconfigurations |
| ✅ **Rollback safety** | Auto-backup before extending |
| ✅ **Interactive wizard** | Guided setup for beginners |
| ✅ **Template-driven** | Easy to add new brokers/modes |

---

## Implementation Effort

| Component | Effort | Priority |
|-----------|--------|----------|
| `sagaz init` with CDC flags | 4 hours | High |
| `sagaz extend --enable-outbox-cdc` | 6 hours | High |
| `sagaz validate` CDC checks | 3 hours | High |
| `sagaz status` CDC display | 2 hours | Medium |
| Jinja2 templates (Debezium) | 4 hours | High |
| Interactive wizard | 4 hours | Medium |
| `.sagaz-config.yml` tracking | 2 hours | Medium |
| Integration tests | 5 hours | High |
| Documentation | 2 hours | High |

**Total**: ~32 hours (4 days)

---

## Dependencies

- **Worker implementation** (28 hours) must be complete first
- **CLI scaffolding** from Q1 2026 roadmap
- **Template system** for file generation

---

## See Also

- [ADR-011: CDC Support](docs/architecture/adr/adr-011-cdc-support.md) - Full CDC design
- [CDC_UNIFIED_WORKER_SUMMARY.md](CDC_UNIFIED_WORKER_SUMMARY.md) - Worker design
- [ROADMAP.md](docs/ROADMAP.md) - Q1/Q2 2026 CLI plans
