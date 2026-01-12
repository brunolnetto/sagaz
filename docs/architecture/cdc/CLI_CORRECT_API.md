# Correct CLI API - Interactive by Default

**Key principle**: `sagaz init` is interactive, flags are optional shortcuts.

---

## Primary Usage (Interactive)

```bash
# Default: Interactive wizard
$ sagaz init

Welcome to Sagaz! Let's set up your project.

? Project name: my-saga-app
? Deployment type:
  > Local (Docker Compose)
    Kubernetes
    
? Outbox implementation:
  > Polling (simple, recommended for <5K events/sec)
    CDC (high-throughput, 50K+ events/sec)
    Hybrid (both, for testing/migration)

? Message broker:
  > Kafka
    RabbitMQ
    Redis Streams

? Enable monitoring (Prometheus + Grafana)?
  > Yes
    No

✓ Generated docker-compose.yml
✓ Generated .env (SAGAZ_OUTBOX_MODE=polling)
✓ Generated k8s/outbox-worker.yaml
✓ Created examples/

Project initialized successfully!

Next steps:
  cd my-saga-app
  docker-compose up -d
  python examples/simple_saga.py
```

## Optional Flags (Non-Interactive)

For automation or experienced users:

```bash
# Skip wizard with flags
sagaz init \
  --local \
  --outbox-mode=cdc \
  --outbox-broker=kafka \
  --no-interactive

# Minimal (defaults)
sagaz init --local --no-interactive
```

---

## CLI Command Structure

### `sagaz init` (Interactive by default)

```
Usage: sagaz init [OPTIONS]

  Initialize a new Sagaz project.
  
  Runs an interactive wizard by default. Use flags to skip wizard.

Options:
  --local                 Docker Compose setup (default)
  --k8s                   Kubernetes manifests
  --outbox-mode TEXT      Skip wizard: polling|cdc|hybrid
  --outbox-broker TEXT    Skip wizard: kafka|redis|rabbitmq
  --no-interactive        Skip wizard, use flags or defaults
  --project-name TEXT     Project name (default: current directory)
  --help                  Show this message and exit

Examples:
  # Interactive (recommended)
  sagaz init
  
  # Non-interactive with flags
  sagaz init --local --outbox-mode=cdc --outbox-broker=kafka --no-interactive
  
  # Minimal (all defaults)
  sagaz init --local --no-interactive
```

### `sagaz extend` (Always interactive with confirmation)

```
Usage: sagaz extend [OPTIONS]

  Extend an existing Sagaz project with new capabilities.
  
  Always requires confirmation for safety.

Options:
  --enable-outbox-cdc     Upgrade outbox to CDC implementation
  --outbox-broker TEXT    Message broker: kafka|redis|rabbitmq
  --hybrid                Run both polling and CDC (recommended)
  --remove-polling        Remove polling workers (CDC-only)
  --no-backup             Skip backup (not recommended)
  --yes                   Auto-confirm (for CI/CD)
  --help                  Show this message and exit

Examples:
  # Interactive upgrade (shows plan, asks confirmation)
  sagaz extend --enable-outbox-cdc --outbox-broker=kafka --hybrid
  
  # Auto-confirm for automation
  sagaz extend --enable-outbox-cdc --outbox-broker=kafka --yes
```

---

## User Journeys

### Journey 1: Beginner (Interactive)

```bash
# User just runs init
$ sagaz init

Welcome to Sagaz! Let's set up your project.

? Project name: my-first-saga
? Deployment type:
  > Local (Docker Compose)
    Kubernetes

? Outbox implementation:
  > Polling (simple, recommended for <5K events/sec)
    CDC (high-throughput, 50K+ events/sec)
    Hybrid (both, for testing/migration)

ℹ You selected: Polling
  • Simple setup, no additional services
  • Handles up to 5,000 events/second
  • Easy to upgrade to CDC later

? Message broker:
  > Kafka
    RabbitMQ
    Redis Streams

? Enable monitoring (Prometheus + Grafana)?
  > Yes
    No

✓ Generated configuration
✓ Project ready!

Next steps:
  cd my-first-saga
  docker-compose up -d
  python examples/simple_saga.py

Documentation: https://docs.sagaz.io/quickstart
```

### Journey 2: Experienced User (Non-Interactive)

```bash
# Power user skips wizard
$ sagaz init \
  --local \
  --outbox-mode=cdc \
  --outbox-broker=kafka \
  --no-interactive

✓ Project initialized (CDC mode, Kafka broker)

Next steps:
  docker-compose up -d
```

### Journey 3: CI/CD Automation

```bash
# In CI/CD pipeline
$ sagaz init \
  --k8s \
  --outbox-mode=polling \
  --outbox-broker=kafka \
  --project-name=saga-$CI_COMMIT_SHA \
  --no-interactive

✓ Kubernetes manifests generated
```

---

## Interactive Wizard Flow

```
sagaz init
    │
    ├─► Project name? ─────────► [user input] ──┐
    │                                            │
    ├─► Deployment type? ──────► Local/K8s ─────┤
    │                                            │
    ├─► Outbox mode? ──────────► Polling/CDC ───┤
    │   (shows explanation)                      │
    │                                            │
    ├─► Broker? ───────────────► Kafka/etc ─────┤
    │                                            │
    ├─► Monitoring? ───────────► Yes/No ────────┤
    │                                            │
    └─► Generate files ─────────────────────────┘
         ✓ docker-compose.yml
         ✓ .env
         ✓ k8s/
         ✓ examples/
```

---

## Comparison: Interactive vs Flags

### ✅ Interactive (Recommended)

```bash
$ sagaz init

Pros:
  • Beginner-friendly
  • Guided decisions
  • Contextual help
  • No flags to remember
  
Best for:
  • First-time users
  • Learning the tool
  • Exploration
```

### ✅ Non-Interactive (Power Users)

```bash
$ sagaz init --local --outbox-mode=cdc --no-interactive

Pros:
  • Fast
  • Scriptable
  • CI/CD friendly
  • Reproducible
  
Best for:
  • Automation
  • Experienced users
  • Scripts
```

---

## Flag Behavior

| Scenario | Behavior |
|----------|----------|
| `sagaz init` | Interactive wizard |
| `sagaz init --local` | Interactive (just sets deployment type) |
| `sagaz init --outbox-mode=cdc` | Interactive (just sets outbox mode) |
| `sagaz init --no-interactive` | Non-interactive, uses defaults |
| `sagaz init --local --outbox-mode=cdc --no-interactive` | Non-interactive, uses specified values |

---

## Defaults (When Non-Interactive)

```yaml
deployment: local
outbox_mode: polling
broker: kafka
monitoring: true
project_name: <current_directory_name>
```

---

## Help Text

```bash
$ sagaz init --help

Usage: sagaz init [OPTIONS]

  Initialize a new Sagaz project.

  By default, runs an interactive wizard that guides you through project
  setup. Use flags to skip the wizard and provide values directly.

Options:
  --local                 Generate Docker Compose setup (default)
  --k8s                   Generate Kubernetes manifests
  
  --outbox-mode TEXT      Outbox implementation: polling|cdc|hybrid
                          Default: polling
                          Interactive: Prompts with explanation
  
  --outbox-broker TEXT    Message broker: kafka|redis|rabbitmq
                          Default: kafka
                          Interactive: Prompts with pros/cons
  
  --project-name TEXT     Project name
                          Default: current directory name
  
  --no-interactive        Skip wizard, use flags or defaults
                          Required for CI/CD automation
  
  --help                  Show this message and exit

Examples:
  # Interactive wizard (recommended for first use)
  sagaz init
  
  # Quick start with defaults
  sagaz init --no-interactive
  
  # Non-interactive with custom values
  sagaz init --outbox-mode=cdc --outbox-broker=kafka --no-interactive
  
  # Kubernetes setup
  sagaz init --k8s --no-interactive

Learn more: https://docs.sagaz.io/cli/init
```

---

## Key Takeaways

1. **`sagaz init` is interactive by default** - No flags required
2. **Flags are optional shortcuts** - For power users and automation
3. **`--no-interactive` for CI/CD** - Explicit automation mode
4. **Wizard provides guidance** - Helps users understand options
5. **Always can use flags** - Skip wizard if you know what you want

---

## See Also

- [CLI Examples](CLI_EXAMPLES.md) - More usage examples
- [CLI Naming Convention](CLI_NAMING_CONVENTION.md) - Why `--outbox-mode`
- [CLI Integration](CDC_CLI_INTEGRATION.md) - Full CLI design
