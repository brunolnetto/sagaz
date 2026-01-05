# Documentation Structure Guide

This guide explains how the Sagaz documentation is organized and where to add new content.

---

## Directory Layout

```
docs/
├── README.md                  # Documentation home
├── ROADMAP.md                 # Roadmap & Strategy (2026)
├── STRUCTURE.md               # This file
├── quickstart.md              # 5-minute setup guide
│
├── architecture/              # System design & decisions
│   ├── overview.md            # High-level architecture
│   ├── components.md          # Service artifacts & classes
│   ├── dataflow.md            # Event flow & state machines
│   ├── decisions.md           # Architecture decision summary
│   └── adr/                   # Architecture Decision Records
│       ├── README.md          # ADR index
│       └── adr-NNN-*.md       # Individual ADRs
│
├── guides/                    # How-to guides
│   ├── configuration.md       # SagaConfig setup
│   ├── kubernetes.md          # K8s deployment
│   └── benchmarking.md        # Performance testing
│
├── patterns/                  # Implementation patterns
│   ├── dead-letter-queue.md   # DLQ pattern
│   ├── multi-sink-fanout.md   # Multi-sink pattern
│   ├── consumer-inbox.md      # Idempotent consumption
│   └── optimistic-sending.md  # Optimistic message sending
│
├── reference/                 # API reference
│   └── api.md                 # API documentation
│
├── development/               # Development process
│   └── testing.md             # Testing guide
│
├── monitoring/                # Observability
│   └── alertmanager-rules.yml # Alert templates
│
└── archive/                   # Historical documentation
    ├── README.md              # Archive index
    └── HISTORICAL_*.md        # Superseded docs
```

---

## Where to Add New Content

| Content Type | Location | Example |
|-------------|----------|---------|
| Architecture decisions | `architecture/adr/` | ADR-015 Unified API |
| Implementation patterns | `patterns/` | Consumer Inbox |
| How-to guides | `guides/` | Kubernetes Guide |
| API reference | `reference/` | SagaConfig API |
| Development process | `development/` | Testing Guide |
| Historical/deprecated | `archive/` | Old README |

---

## Content by Audience

| I am a... | Start Here | Then Read |
|-----------|-----------|-----------|
| **New User** | [Quickstart](quickstart.md) | [Configuration](guides/configuration.md) |
| **Developer** | [Architecture](architecture/overview.md) | [Patterns](patterns/) |
| **Operator** | [Kubernetes Guide](guides/kubernetes.md) | [Monitoring](monitoring/) |
| **Architect** | [ADR Index](architecture/adr/README.md) | [Roadmap](ROADMAP.md) |

---

## File Naming Conventions

### ADRs
```
adr-NNN-descriptive-name.md
```
- `NNN`: Three-digit number (001, 002, ...)
- Use lowercase with hyphens
- Examples:
  - `adr-011-cdc-support.md`
  - `adr-015-unified-saga-api.md`

### Other Files
```
descriptive-name.md
```
- Lowercase with hyphens
- Be descriptive but concise
- Examples:
  - `dead-letter-queue.md`
  - `kubernetes.md`

---

## When to Archive

Move content to `archive/` when:
- Content is superseded by newer documentation
- Feature is deprecated or removed
- Document provides historical context only

### Archive Naming
```
HISTORICAL_<original-name>.md
```

Example: `STRATEGY.md` → `HISTORICAL_STRATEGY_2024.md`

---

## Documentation Standards

### Headers
- H1 (`#`): Document title (once per file)
- H2 (`##`): Major sections
- H3 (`###`): Subsections
- H4+ (`####`): Rarely needed

### Code Blocks
Always specify the language:
```python
# Python example
from sagaz import Saga
```

```yaml
# YAML example
apiVersion: v1
kind: ConfigMap
```

### Tables
Use consistent alignment:
| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Value 1  | Value 2  | Value 3  |

### Links
Use relative paths:
```markdown
[Architecture](architecture/overview.md)
[ADR-011](architecture/adr/adr-011-cdc-support.md)
```

---

## Adding New ADRs

1. Create file: `docs/architecture/adr/adr-NNN-title.md`
2. Use the ADR template (see [ADR README](architecture/adr/README.md))
3. Update the ADR index in `architecture/adr/README.md`
4. Update `architecture/decisions.md` if adding to summary
5. Reference from `ROADMAP.md` if planned for a milestone

---

## See Also

- [ADR Index](architecture/adr/README.md) - Architecture decisions
- [Roadmap](ROADMAP.md) - Development timeline
- [Archive](archive/README.md) - Historical documentation
