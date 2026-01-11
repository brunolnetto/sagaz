# ADR-015: Environment Variable Management with .env Support

**Status:** Accepted  
**Date:** 2026-01-11  
**Deciders:** Core Team  
**Related ADRs:**
- ADR-001 (Core Architecture)
- ADR-003 (Configuration Management)

## Context

When deploying Sagaz applications, users need to configure:
- Database connection strings with sensitive credentials
- Message broker URLs
- Observability endpoints
- Environment-specific settings (dev/staging/prod)

**Problem:**
Hard-coding configuration in YAML files leads to:
1. **Security risks**: Credentials committed to version control
2. **Inflexibility**: Different configs needed per environment
3. **Maintenance burden**: Updating configs across multiple deployments
4. **Poor developer experience**: Manual configuration prone to errors

**Requirements:**
- Keep sensitive data out of version control
- Support multiple environments (dev/staging/prod) with same codebase
- Allow both environment variables and file-based configuration
- Provide clear defaults for development
- Work seamlessly with containers and orchestrators

## Decision

We implement a **three-tier configuration system**:

1. **`.env` files** for local development (git-ignored, not committed)
2. **Environment variables** for production/containers (injected at runtime)
3. **`sagaz.yaml`** with variable substitution for structure

### Architecture

```
┌──────────────────────────────────────────────────────┐
│ Application Code                                      │
│   config = SagaConfig.from_file("sagaz.yaml")        │
└───────────────────┬──────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────┐
│ EnvManager (core/env.py)                              │
│  - Loads .env file (if exists)                        │
│  - Substitutes ${VAR} in YAML                         │
│  - Provides defaults                                  │
└───────────────────┬──────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌──────────────┐        ┌──────────────┐
│ .env (local) │        │ OS environ   │
│ (git-ignored)│        │ (runtime)    │
└──────────────┘        └──────────────┘
```

### Key Features

#### 1. Variable Substitution in YAML

```yaml
storage:
  connection:
    url: "${SAGAZ_STORAGE_URL}"  # Simple substitution
    host: "${SAGAZ_STORAGE_HOST:-localhost}"  # With default
    password: "${SAGAZ_STORAGE_PASSWORD:?Required}"  # Required
```

Syntax:
- `${VAR}` - Direct substitution
- `${VAR:-default}` - Use default if not set
- `${VAR:?error}` - Raise error if not set (for required vars)

#### 2. Structured .env Files

`.env.template` provided as reference:
```bash
# Storage
SAGAZ_STORAGE_TYPE=postgresql
SAGAZ_STORAGE_URL=postgresql://user:pass@localhost:5432/db

# Broker
SAGAZ_BROKER_TYPE=redis
SAGAZ_BROKER_URL=redis://localhost:6379/1

# Observability
SAGAZ_METRICS_ENABLED=true
SAGAZ_TRACING_ENDPOINT=http://localhost:4317
```

Users copy to `.env` and customize:
```bash
cp .env.template .env
# Edit .env with actual values
```

#### 3. Priority Order

Configuration is resolved in this priority (highest to lowest):
1. **Environment variables** (runtime)
2. **`.env` file** (development)
3. **Default values** in YAML (${VAR:-default})
4. **Built-in defaults** in code

Example:
```bash
# .env file
SAGAZ_STORAGE_HOST=dev-db

# YAML
host: "${SAGAZ_STORAGE_HOST:-localhost}"

# Runtime override
SAGAZ_STORAGE_HOST=prod-db python app.py  # Uses: prod-db
python app.py                              # Uses: dev-db (from .env)
```

#### 4. Three Usage Patterns

**Pattern A: YAML + .env (recommended for most users)**
```python
# Loads sagaz.yaml with .env substitution
config = SagaConfig.from_file("sagaz.yaml")
```

**Pattern B: Environment variables only (containers)**
```python
# Loads from SAGAZ_* environment variables
config = SagaConfig.from_env()
```

**Pattern C: Programmatic (testing/advanced)**
```python
config = SagaConfig(
    storage=PostgreSQLSagaStorage("postgresql://..."),
    broker=KafkaBroker(...),
)
```

### Implementation

#### New Module: `core/env.py`

```python
class EnvManager:
    """Manages environment variables with .env support"""
    
    def load(self, env_file: Path | None = None) -> bool:
        """Load .env file using python-dotenv"""
        
    def get(self, key: str, default: str | None = None) -> str:
        """Get variable with fallback"""
        
    def substitute(self, text: str) -> str:
        """Substitute ${VAR} references in text"""
        
    def substitute_dict(self, data: dict) -> dict:
        """Recursively substitute in dict"""
```

#### Updated: `core/config.py`

```python
@classmethod
def from_file(cls, file_path: str, substitute_env: bool = True):
    """Load YAML with environment variable substitution"""
    env = get_env()
    env.load()  # Load .env if exists
    data = env.substitute_dict(yaml.safe_load(f))
    # ... build config
```

#### Project Initialization

`sagaz init` now generates:
- `sagaz.yaml` - Configuration structure with ${VAR} placeholders
- `.env.template` - Reference with all available variables
- `.gitignore` - Ensures .env is never committed

## Consequences

### Positive

✅ **Security**: Credentials never committed to version control  
✅ **Flexibility**: Same codebase works across environments  
✅ **DX**: Clear `.env.template` guides users  
✅ **Container-friendly**: Works seamlessly with Docker/K8s secrets  
✅ **Testability**: Easy to override in tests  
✅ **Documentation**: Self-documenting via .env.template  

### Negative

⚠️ **Complexity**: Three-tier system requires understanding  
⚠️ **Dependency**: Adds `python-dotenv` dependency  
⚠️ **Migration**: Existing users need to adapt configurations  

### Neutral

📝 `.env` files must be manually created (copy from template)  
📝 Containers should use native secret management, not .env files  
📝 Substitution only works with SagaConfig.from_file(), not raw YAML  

## Examples

### Development Workflow

```bash
# 1. Initialize project
sagaz init
cd my-project

# 2. Configure environment
cp .env.template .env
# Edit .env with local values

# 3. Run (automatically loads .env)
python main.py
```

### Production Deployment (Docker)

```dockerfile
FROM python:3.11
COPY . /app
WORKDIR /app

# Do NOT copy .env file!
# Use ENV or runtime secrets:
ENV SAGAZ_STORAGE_URL=postgresql://prod-db:5432/sagaz
ENV SAGAZ_BROKER_URL=kafka://kafka:9092

CMD ["python", "main.py"]
```

### Kubernetes

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: sagaz-secrets
stringData:
  storage-url: postgresql://user:pass@db:5432/sagaz
---
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: sagaz-app
        env:
        - name: SAGAZ_STORAGE_URL
          valueFrom:
            secretKeyRef:
              name: sagaz-secrets
              key: storage-url
```

### Testing

```python
def test_with_custom_config():
    import os
    os.environ["SAGAZ_STORAGE_URL"] = "memory://"
    os.environ["SAGAZ_BROKER_URL"] = "memory://"
    
    config = SagaConfig.from_env(load_dotenv=False)
    # Uses test values, ignores .env
```

## Validation

### Security Checklist

- ✅ `.env` in `.gitignore` (template provided)
- ✅ `.env.template` has placeholders, not real credentials
- ✅ Documentation warns against committing .env
- ✅ CI/CD uses environment variables, not .env files

### Compatibility

- ✅ Works with Docker Compose (env_file directive)
- ✅ Works with Kubernetes (ConfigMaps/Secrets)
- ✅ Works with systemd (EnvironmentFile)
- ✅ Works with cloud platforms (AWS, GCP, Azure secrets)

## Alternatives Considered

### Alternative 1: Config File Per Environment

```
config/
  development.yaml
  staging.yaml
  production.yaml
```

**Rejected:** Still risks committing credentials, requires multiple files.

### Alternative 2: Vault/HashiCorp Secrets

**Rejected:** Too heavy for a library. Users can integrate Vault themselves.

### Alternative 3: Python Files with Sensitive Data

```python
# settings.py
DATABASE_URL = "postgresql://..."  # Don't commit this!
```

**Rejected:** Too easy to accidentally commit, no structure.

### Alternative 4: JSON with Comments

**Rejected:** JSON doesn't support comments well, YAML is standard.

## Future Enhancements

1. **Validation**: Check required variables at startup
2. **Rotation**: Support for credential rotation hooks
3. **Encryption**: Encrypted .env files for local use
4. **Migration**: Tool to migrate old configs to new format

## References

- [12-Factor App: Config](https://12factor.net/config)
- [python-dotenv Documentation](https://saurabh-kumar.com/python-dotenv/)
- [Kubernetes Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
- [Docker Compose env_file](https://docs.docker.com/compose/environment-variables/)

## Implementation Checklist

- [x] Create `core/env.py` with EnvManager
- [x] Update `core/config.py` to use EnvManager
- [x] Create `.env.template` resource file
- [x] Update `sagaz.yaml.template` with ${VAR} syntax
- [x] Update project init to generate .env.template
- [x] Add python-dotenv dependency
- [x] Update .gitignore template
- [ ] Add validation for required variables
- [ ] Update documentation
- [ ] Add integration tests
- [ ] Migration guide for existing users
