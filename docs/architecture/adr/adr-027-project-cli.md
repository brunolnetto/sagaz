# ADR-027: Project-Centric CLI (Airflow/dbt-inspired)

**Date**: 2026-01-07  
**Status**: Proposed  
**Target Version**: v1.4.0  
**Priority**: High  
**Complexity**: High  
**Effort Estimate**: 6-8 weeks  
**Prerequisites**: None (but synergizes with ADR-019 Dry Run)  
**Enables**: Standardized project structure, CI/CD validation, multi-saga orchestration  

---

## Context and Problem Statement

As `sagaz` adoption grows, users building systems with 10–50+ sagas face organizational challenges:

1. **No canonical structure**: Every team invents their own layout for saga files, tests, and configs.
2. **No discovery mechanism**: Users must manually register sagas or create custom import machinery.
3. **No pre-flight validation**: Circular dependencies, missing compensations, and config errors are only caught at runtime.
4. **Environment management is ad-hoc**: Connection strings and credentials are hardcoded or managed inconsistently.

Tools like **dbt** and **Apache Airflow** solve analogous problems for data pipelines and workflows. Their project-centric CLIs are a key reason for their adoption.

### Existing Sagaz CLI Capabilities

Currently, `sagaz` provides:
- `sagaz init --local|--k8s|--selfhost`: Scaffold deployment configs (Docker Compose, K8s manifests).
- `sagaz examples run|list|select`: Browse and run bundled examples.
- `sagaz dev`: Start local development stack.
- `sagaz benchmark`: Run performance benchmarks.

These are *deployment* and *demo* oriented. We lack *project* and *saga* management commands.

---

## Decision

Implement a **project-centric CLI** that treats a directory as a "Sagaz project" with:
1. A manifest file (`sagaz.yaml`) defining project metadata.
2. Auto-discovery of `Saga` subclasses in designated source directories.
3. Validation, listing, and execution commands.
4. Environment profiles with secret interpolation.

### 1. Project Structure

`sagaz init my_project` creates:

```
my_project/
├── sagaz.yaml              # Project manifest (required)
├── profiles.yaml           # Environment-specific configs (gitignored)
├── sagas/                   # Saga source files (discovered recursively)
│   ├── __init__.py
│   ├── orders/
│   │   ├── __init__.py
│   │   ├── order_saga.py
│   │   └── payment_saga.py
│   └── inventory/
│       └── stock_saga.py
├── tests/                   # Saga tests
├── macros/                  # Shared utilities (optional)
└── .sagaz/                  # Cache and compiled artifacts
```

### 2. Manifest Schema (`sagaz.yaml`)

```yaml
name: my_project
version: "1.0.0"
profile: default  # References profiles.yaml

saga-paths:
  - sagas/  # Default; can add more

config:
  default_timeout: 60
  failure_strategy: FAIL_FAST_WITH_GRACE

# Optional: Selector tags for filtering
tags:
  orders/order_saga.py:
    - critical
    - payments
```

### 3. Profiles (`profiles.yaml`)

```yaml
default:
  target: dev

dev:
  storage_url: "postgresql://localhost/sagaz_dev"
  broker_url: "redis://localhost:6379"
  
prod:
  storage_url: "{{ env_var('SAGAZ_STORAGE_URL') }}"
  broker_url: "{{ env_var('SAGAZ_BROKER_URL') }}"
```

Secret interpolation uses `{{ env_var('NAME') }}` syntax (like dbt).

### 4. CLI Commands

| Command | Description |
|---------|-------------|
| `sagaz project init <name>` | Create new project scaffold |
| `sagaz project check` | Parse all sagas, validate DAGs, check configs |
| `sagaz project list [--tag TAG]` | List discovered sagas with metadata |
| `sagaz project run <saga> [--ctx JSON]` | Execute a saga by name |
| `sagaz project docs [--output DIR]` | Generate static documentation with Mermaid diagrams |
| `sagaz project graph` | Visualize inter-saga dependencies (if cross-saga refs exist) |

**Note**: Commands are namespaced under `sagaz project` to avoid collision with existing `sagaz run` (if added later for single-file execution).

### 5. Saga Discovery

The discovery algorithm:
1. Walk all paths in `saga-paths`.
2. For each `.py` file, attempt import (sandboxed with fresh `sys.modules` snapshot).
3. Inspect module for classes subclassing `sagaz.Saga`.
4. Extract metadata: `saga_name`, steps, dependencies, tags.
5. Cache results in `.sagaz/manifest.json` for fast subsequent runs.

**Import safety**: We use `importlib.util.spec_from_file_location` to avoid polluting the main interpreter. Errors during import are caught and reported as diagnostics.

### 6. Selectors (Future)

Inspired by dbt, support filtering:
```bash
sagaz project run --select "tag:critical"
sagaz project run --select "orders/*"
sagaz project run --exclude "tag:slow"
```

This is Phase 2 scope.

---

## Consequences

### Positive
- **Consistency**: Any engineer can navigate any Sagaz project.
- **CI/CD Integration**: `sagaz project check` in pipelines catches errors before deployment.
- **Documentation**: `sagaz project docs` auto-generates up-to-date diagrams.
- **Onboarding**: "Just run `sagaz project init` and start coding."

### Negative
- **Python import complexity**: Dynamic imports are error-prone. Must handle:
  - Circular imports within user code
  - Missing dependencies (import errors)
  - Namespace package vs regular package differences
- **Two config files**: `sagaz.yaml` + `profiles.yaml` adds cognitive load (but mirrors dbt's proven model).
- **Opinionated structure**: Power users may resist. Mitigation: Support `saga-paths` customization.

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Import errors crash CLI | High | Medium | Catch all exceptions during discovery, report as diagnostics |
| Large projects slow to scan | Medium | Low | Cache manifest, incremental discovery |
| Conflicting saga names | Medium | Medium | Enforce unique `saga_name` across project |
| Secret leakage in profiles.yaml | Low | High | Document `.gitignore` in init template, warn if committed |

---

## Alternatives Considered

### 1. Status Quo (Library Only)
- **Pros**: Maximum flexibility.
- **Cons**: Every team reinvents structure; no shared tooling.
- **Decision**: Rejected—poor DX at scale.

### 2. Cookiecutter Template
- **Pros**: One-time scaffold, no ongoing code to maintain.
- **Cons**: No validation tooling, no `check` command, template drift.
- **Decision**: Rejected—insufficient ongoing value.

### 3. Decorator-Based Registration (like Flask)
```python
from sagaz import register

@register
class OrderSaga(Saga):
    ...
```
- **Pros**: Explicit, no magic imports.
- **Cons**: Requires user to import/execute registration; doesn't scale.
- **Decision**: Rejected—still requires orchestration of imports.

### 4. Explicit Manifest (No Discovery)
```yaml
sagas:
  - module: sagas.orders.order_saga
    class: OrderSaga
```
- **Pros**: No import magic.
- **Cons**: Tedious to maintain; sync issues.
- **Decision**: Rejected—poor DX.

---

## Implementation Roadmap

### Phase 1: Core (v1.4.0) — 4 weeks
- `sagaz project init`
- `sagaz project check` (parse and validate)
- `sagaz project list`
- Manifest and profile loading

### Phase 2: Execution & Docs (v1.4.1) — 2 weeks
- `sagaz project run`
- `sagaz project docs`

### Phase 3: Selectors & Polish (v1.5.0) — 2 weeks
- `--select` / `--exclude` syntax
- `sagaz project graph` for inter-saga visualization
- Performance optimization for large projects

---

## Related ADRs
- **ADR-019**: Dry Run Mode — `sagaz project run --dry-run` integration
- **ADR-026**: Industry Examples — Examples should be structured as mini-projects

---

## Open Questions

1. Should `sagaz.yaml` support inheritance (like dbt's `dbt_project.yml` with packages)?
2. How do we handle sagas that depend on runtime context (e.g., database session)? Discovery can't execute them.
3. Should we support a "workspace" concept for monorepos with multiple projects?
