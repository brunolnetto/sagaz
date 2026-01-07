# Project CLI - Implementation Plan

**Status:** Draft  
**Created:** 2026-01-07  
**Last Updated:** 2026-01-07  
**Target Version:** v1.4.0  
**ADR:** [ADR-027: Project CLI](../adr/adr-027-project-cli.md)  
**Estimated Effort:** 6-8 weeks  

---

## Executive Summary

Transform `sagaz` from a library into a project-aware framework with discovery, validation, and execution tooling—inspired by dbt and Airflow.

---

## Goals

| Goal | Success Criteria |
|------|------------------|
| Standardize project structure | `sagaz project init` creates consistent layout |
| Enable pre-flight validation | `sagaz project check` catches 90%+ of config/DAG errors |
| Provide discovery mechanism | `sagaz project list` finds all sagas without manual registration |
| Support environment profiles | Secrets interpolated from env vars, not hardcoded |

---

## Non-Goals (Scope Exclusions)

- **Cross-saga orchestration**: We discover sagas, but don't orchestrate dependencies *between* sagas (that's a v2 feature).
- **Remote execution**: All commands run locally; no distributed scheduler.
- **GUI/Web UI**: CLI only for now.

---

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI Layer                             │
│  sagaz project init │ check │ list │ run │ docs             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Project Service                          │
│  ┌───────────┐  ┌───────────────┐  ┌────────────────────┐   │
│  │ Manifest  │  │   Discovery   │  │    Validator       │   │
│  │  Loader   │  │    Engine     │  │  (DAG, Config)     │   │
│  └───────────┘  └───────────────┘  └────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       Core sagaz                             │
│              Saga │ SagaConfig │ Storage                     │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

#### 1. ManifestLoader

Parses `sagaz.yaml` and `profiles.yaml`:

```python
# sagaz/project/manifest.py
@dataclass
class ProjectManifest:
    name: str
    version: str
    profile: str
    saga_paths: list[str] = field(default_factory=lambda: ["sagas/"])
    config: dict = field(default_factory=dict)
    
    @classmethod
    def load(cls, project_dir: Path) -> "ProjectManifest":
        yaml_path = project_dir / "sagaz.yaml"
        if not yaml_path.exists():
            raise ProjectError(f"No sagaz.yaml found in {project_dir}")
        # ... parse and validate with Pydantic
```

#### 2. DiscoveryEngine

Finds saga classes without polluting the runtime:

```python
# sagaz/project/discovery.py
class DiscoveryEngine:
    def __init__(self, saga_paths: list[Path]):
        self.saga_paths = saga_paths
        self._cache: dict[str, SagaMetadata] = {}
    
    def discover(self) -> list[SagaMetadata]:
        """
        Walk saga_paths, import modules, find Saga subclasses.
        
        Returns list of SagaMetadata with:
          - module_path: str
          - class_name: str
          - saga_name: str (from class attribute)
          - steps: list[str]
          - dependencies: dict[str, list[str]]
          - file_path: Path
          - line_number: int
        """
        results = []
        for path in self.saga_paths:
            for py_file in path.rglob("*.py"):
                if py_file.name.startswith("_"):
                    continue
                try:
                    metadata = self._inspect_file(py_file)
                    results.extend(metadata)
                except ImportError as e:
                    # Log warning but continue
                    logger.warning(f"Failed to import {py_file}: {e}")
        return results
    
    def _inspect_file(self, py_file: Path) -> list[SagaMetadata]:
        """Import file in isolated namespace, find Saga subclasses."""
        # Use importlib.util to avoid sys.path pollution
        spec = importlib.util.spec_from_file_location(
            f"_sagaz_discovery_{py_file.stem}", 
            py_file
        )
        module = importlib.util.module_from_spec(spec)
        
        # Temporarily add parent to path for relative imports
        with self._temporary_sys_path(py_file.parent):
            spec.loader.exec_module(module)
        
        # Find Saga subclasses
        sagas = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if self._is_saga_subclass(obj) and obj.__module__ == module.__name__:
                sagas.append(self._extract_metadata(obj, py_file))
        return sagas
```

#### 3. Validator

Checks DAG correctness and config validity:

```python
# sagaz/project/validator.py
@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationError]
    warnings: list[ValidationWarning]

class ProjectValidator:
    def validate(self, manifest: ProjectManifest, sagas: list[SagaMetadata]) -> ValidationResult:
        errors = []
        warnings = []
        
        # Check for duplicate saga_names
        names = [s.saga_name for s in sagas]
        duplicates = [n for n in names if names.count(n) > 1]
        if duplicates:
            errors.append(DuplicateSagaNameError(duplicates))
        
        # Check each saga's internal DAG
        for saga in sagas:
            try:
                self._validate_saga_dag(saga)
            except CircularDependencyError as e:
                errors.append(e)
        
        # Check profile existence
        if not self._profile_exists(manifest.profile):
            warnings.append(ProfileNotFoundWarning(manifest.profile))
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
```

---

## Implementation Phases

### Phase 1: Foundation (Weeks 1-2)

| Task | Effort | Owner | Notes |
|------|--------|-------|-------|
| Create `sagaz/project/` package | 0.5d | - | Directory structure |
| Implement `ManifestLoader` with Pydantic | 2d | - | `sagaz.yaml` + `profiles.yaml` |
| Implement `DiscoveryEngine` | 3d | - | **High risk**: import machinery |
| Unit tests for manifest/discovery | 2d | - | Edge cases: empty dirs, syntax errors |
| `sagaz project init` command | 2d | - | Template files, directory creation |

**Deliverables:**
- `sagaz project init my_project` works
- `ManifestLoader` parses YAML correctly
- `DiscoveryEngine` finds sagas in test fixtures

**Risks:**
| Risk | Mitigation |
|------|------------|
| Import errors crash CLI | Catch all exceptions, report as diagnostics |
| Relative imports fail | Add parent directory to sys.path temporarily |

### Phase 2: Validation & Listing (Weeks 3-4)

| Task | Effort | Owner | Notes |
|------|--------|-------|-------|
| Implement `ProjectValidator` | 2d | - | DAG checks, duplicate names |
| `sagaz project check` command | 1d | - | Rich output with errors/warnings |
| `sagaz project list` command | 1d | - | Table with saga name, steps, tags |
| Integration tests | 2d | - | Test projects with errors |
| Profile loading with env var interpolation | 2d | - | `{{ env_var('X') }}` syntax |

**Deliverables:**
- `sagaz project check` returns non-zero on errors (CI-friendly)
- `sagaz project list` shows discovered sagas in pretty table

### Phase 3: Execution & Docs (Weeks 5-6)

| Task | Effort | Owner | Notes |
|------|--------|-------|-------|
| `sagaz project run <name>` command | 2d | - | Instantiate saga, call `run()` |
| Context injection from CLI (`--ctx`) | 1d | - | JSON or key=value pairs |
| `sagaz project docs` command | 3d | - | Generate Mermaid diagrams per saga |
| Static HTML output | 2d | - | Index page linking to saga docs |
| End-to-end tests | 2d | - | Full flow: init → check → run |

### Phase 4: Polish & Edge Cases (Weeks 7-8)

| Task | Effort | Owner | Notes |
|------|--------|-------|-------|
| Cache manifest in `.sagaz/` | 2d | - | Skip re-discovery if unchanged |
| `--verbose` and `--quiet` flags | 1d | - | Logging levels |
| Error message UX review | 1d | - | Human-readable errors |
| Documentation | 2d | - | User guide, examples |
| Performance testing | 1d | - | Test with 100+ sagas |

---

## Test Strategy

### Unit Tests
- `ManifestLoader`: Valid YAML, invalid YAML, missing file, missing fields
- `DiscoveryEngine`: Empty dir, nested dirs, import errors, abstract classes
- `ProjectValidator`: Cycles, duplicates, missing deps

### Integration Tests
- Full project fixtures (valid, invalid, edge cases)
- CI simulation: `sagaz project check` exit codes

### End-to-End Tests
- `init → check → list → run` flow
- Error recovery scenarios

---

## Dependencies

| Dependency | Purpose | Status |
|------------|---------|--------|
| Click/Typer | CLI framework | Already in use |
| Rich | Pretty output | Already in use |
| Pydantic | Manifest validation | Already in use |
| PyYAML | YAML parsing | Already in use |
| Jinja2 (optional) | Template rendering | Defer—simple string templates first |

---

## Success Criteria

| Metric | Target |
|--------|--------|
| `sagaz project init` creates valid project | 100% |
| `sagaz project check` detects known error cases | 95%+ |
| Discovery time for 50-saga project | < 3 seconds |
| Zero import-related crashes | Caught and reported gracefully |
| Documentation coverage | All commands documented |

---

## Open Issues

1. **Monorepo support**: Should we support `workspaces` like npm/pnpm?
2. **Plugin system**: Allow custom validators/discovery hooks?
3. **Config inheritance**: Should `sagaz.yaml` support `include` or `extends`?
