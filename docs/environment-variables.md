# Environment Variables and Configuration

Sagaz supports flexible configuration management using environment variables, `.env` files, and YAML configuration. This guide explains how to securely manage configuration across different environments.

## Quick Start

### 1. Initialize Your Project

```bash
sagaz init
cd my-project
```

This creates:
- `sagaz.yaml` - Configuration structure with variable placeholders
- `.env.template` - Template with all available variables
- `.gitignore` - Ensures `.env` is never committed

### 2. Configure for Development

```bash
# Copy the template
cp .env.template .env

# Edit with your local values
nano .env
```

### 3. Run Your Application

```python
from sagaz import SagaConfig

# Automatically loads .env and substitutes variables in sagaz.yaml
config = SagaConfig.from_file("sagaz.yaml")
```

## Configuration Methods

### Method 1: YAML + .env Files (Recommended)

Best for most users. Combines structured YAML with flexible environment variables.

**sagaz.yaml:**
```yaml
storage:
  type: "${SAGAZ_STORAGE_TYPE:-postgresql}"
  connection:
    url: "${SAGAZ_STORAGE_URL}"
    host: "${SAGAZ_STORAGE_HOST:-localhost}"
    port: ${SAGAZ_STORAGE_PORT:-5432}

broker:
  type: "${SAGAZ_BROKER_TYPE:-redis}"
  connection:
    url: "${SAGAZ_BROKER_URL}"
```

**.env:**
```bash
SAGAZ_STORAGE_URL=postgresql://user:pass@localhost:5432/sagaz
SAGAZ_BROKER_URL=redis://localhost:6379/1
```

**Python code:**
```python
from sagaz import SagaConfig

# Loads sagaz.yaml with .env substitution
config = SagaConfig.from_file("sagaz.yaml")
```

### Method 2: Environment Variables Only

Best for containers and production deployments.

```python
from sagaz import SagaConfig

# Set environment variables (in shell, Dockerfile, K8s, etc.)
# SAGAZ_STORAGE_URL=postgresql://...
# SAGAZ_BROKER_URL=kafka://...

config = SagaConfig.from_env()
```

### Method 3: Programmatic Configuration

Best for testing and advanced use cases.

```python
from sagaz import SagaConfig
from sagaz.storage import PostgreSQLSagaStorage
from sagaz.outbox.brokers import KafkaBroker

config = SagaConfig(
    storage=PostgreSQLSagaStorage("postgresql://..."),
    broker=KafkaBroker(...),
    metrics=True,
)
```

## Variable Substitution Syntax

Sagaz supports shell-like variable substitution in YAML files:

### Basic Substitution

```yaml
host: "${DB_HOST}"  # Uses value of DB_HOST
```

### With Defaults

```yaml
host: "${DB_HOST:-localhost}"  # Uses localhost if DB_HOST not set
port: ${DB_PORT:-5432}          # Works for numbers too
```

### Required Variables

```yaml
password: "${DB_PASSWORD:?Database password required}"
# Raises error if DB_PASSWORD is not set
```

### Real-World Example

```yaml
storage:
  connection:
    # Try full URL first
    url: "${SAGAZ_STORAGE_URL}"
    
    # Fall back to components
    host: "${SAGAZ_STORAGE_HOST:-localhost}"
    port: ${SAGAZ_STORAGE_PORT:-5432}
    database: "${SAGAZ_STORAGE_DB:-sagaz}"
    user: "${SAGAZ_STORAGE_USER:-postgres}"
    password: "${SAGAZ_STORAGE_PASSWORD:?Storage password required}"
```

## Available Environment Variables

### Storage Configuration

```bash
# Full URL (recommended)
SAGAZ_STORAGE_URL=postgresql://user:pass@host:port/db

# Or individual components
SAGAZ_STORAGE_TYPE=postgresql  # postgresql, redis, memory
SAGAZ_STORAGE_HOST=localhost
SAGAZ_STORAGE_PORT=5432
SAGAZ_STORAGE_DB=sagaz
SAGAZ_STORAGE_USER=postgres
SAGAZ_STORAGE_PASSWORD=your_password
```

### Broker Configuration

```bash
# Full URL (recommended)
SAGAZ_BROKER_URL=kafka://localhost:9092

# Or individual components
SAGAZ_BROKER_TYPE=redis  # redis, kafka, rabbitmq, memory
SAGAZ_BROKER_HOST=localhost
SAGAZ_BROKER_PORT=6379
SAGAZ_BROKER_USER=guest
SAGAZ_BROKER_PASSWORD=guest
```

### Observability

```bash
# Metrics
SAGAZ_METRICS_ENABLED=true
SAGAZ_METRICS_PORT=9090

# Tracing
SAGAZ_TRACING_ENABLED=false
SAGAZ_TRACING_ENDPOINT=http://localhost:4317

# Logging
SAGAZ_LOGGING_ENABLED=true
SAGAZ_LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

### Saga Execution

```bash
SAGAZ_DEFAULT_TIMEOUT=60.0
SAGAZ_DEFAULT_MAX_RETRIES=3
SAGAZ_FAILURE_STRATEGY=FAIL_FAST_WITH_GRACE
```

## Deployment Scenarios

### Local Development

Use `.env` file for convenience:

```bash
# .env
SAGAZ_STORAGE_URL=postgresql://localhost/sagaz
SAGAZ_BROKER_URL=redis://localhost:6379
SAGAZ_LOG_LEVEL=DEBUG
```

**DO NOT COMMIT** `.env` to version control!

### Docker Compose

Use `env_file` directive:

```yaml
# docker-compose.yml
services:
  app:
    image: my-sagaz-app
    env_file:
      - .env.production  # Separate env file for production
    volumes:
      - ./sagaz.yaml:/app/sagaz.yaml
```

### Dockerfile

Set defaults in Dockerfile, override at runtime:

```dockerfile
FROM python:3.11

# Set defaults
ENV SAGAZ_STORAGE_TYPE=postgresql
ENV SAGAZ_BROKER_TYPE=kafka
ENV SAGAZ_LOG_LEVEL=INFO

# DO NOT set passwords in Dockerfile!
# They should be injected at runtime

COPY . /app
WORKDIR /app
CMD ["python", "main.py"]
```

Run with secrets:
```bash
docker run \
  -e SAGAZ_STORAGE_PASSWORD=secret \
  -e SAGAZ_BROKER_URL=kafka://kafka:9092 \
  my-sagaz-app
```

### Kubernetes

Use ConfigMaps for non-sensitive data and Secrets for credentials:

```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: sagaz-config
data:
  SAGAZ_STORAGE_TYPE: "postgresql"
  SAGAZ_BROKER_TYPE: "kafka"
  SAGAZ_METRICS_ENABLED: "true"
  
---
# secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: sagaz-secrets
type: Opaque
stringData:
  SAGAZ_STORAGE_URL: "postgresql://user:pass@db:5432/sagaz"
  SAGAZ_BROKER_URL: "kafka://kafka:9092"

---
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: sagaz-app
        image: my-sagaz-app
        envFrom:
        - configMapRef:
            name: sagaz-config
        - secretRef:
            name: sagaz-secrets
```

### Systemd

Use EnvironmentFile:

```ini
# /etc/systemd/system/sagaz.service
[Service]
EnvironmentFile=/etc/sagaz/env
ExecStart=/usr/local/bin/sagaz-app

# /etc/sagaz/env
SAGAZ_STORAGE_URL=postgresql://localhost/sagaz
SAGAZ_BROKER_URL=redis://localhost:6379
```

## Configuration Priority

Settings are resolved in this order (highest priority first):

1. **Runtime environment variables**
   ```bash
   SAGAZ_STORAGE_HOST=prod-db python app.py
   ```

2. **`.env` file in project root**
   ```bash
   # .env
   SAGAZ_STORAGE_HOST=dev-db
   ```

3. **Default values in YAML**
   ```yaml
   host: "${SAGAZ_STORAGE_HOST:-localhost}"
   ```

4. **Built-in defaults in code**

### Example Flow

```bash
# .env file
SAGAZ_STORAGE_HOST=dev-db

# sagaz.yaml
host: "${SAGAZ_STORAGE_HOST:-localhost}"

# Normal run
python app.py
# Result: host=dev-db (from .env)

# Runtime override
SAGAZ_STORAGE_HOST=prod-db python app.py
# Result: host=prod-db (runtime wins)

# No .env, no override
# Result: host=localhost (YAML default)
```

## Security Best Practices

### ✅ DO

- ✅ Use `.env` files for local development only
- ✅ Add `.env` to `.gitignore`
- ✅ Commit `.env.template` with placeholders
- ✅ Use Kubernetes Secrets or similar for production
- ✅ Rotate credentials regularly
- ✅ Use read-only connection strings when possible
- ✅ Document required environment variables

### ❌ DON'T

- ❌ Commit `.env` files with real credentials
- ❌ Put passwords in Dockerfiles
- ❌ Hardcode credentials in code
- ❌ Share `.env` files via email/Slack
- ❌ Use production credentials in development
- ❌ Commit `sagaz.yaml` with real passwords

## Testing

### Unit Tests

Override environment for tests:

```python
import os
import pytest

def test_with_mock_config():
    # Set test environment
    os.environ["SAGAZ_STORAGE_URL"] = "memory://"
    os.environ["SAGAZ_BROKER_URL"] = "memory://"
    
    from sagaz import SagaConfig
    config = SagaConfig.from_env(load_dotenv=False)
    
    # Your test code...
    
    # Cleanup
    del os.environ["SAGAZ_STORAGE_URL"]
    del os.environ["SAGAZ_BROKER_URL"]
```

### Integration Tests

Use testcontainers for real databases:

```python
from testcontainers.postgres import PostgresContainer

def test_with_real_database():
    with PostgresContainer("postgres:15") as postgres:
        os.environ["SAGAZ_STORAGE_URL"] = postgres.get_connection_url()
        
        config = SagaConfig.from_env()
        # Test with real database...
```

## Troubleshooting

### "Configuration file not found"

Ensure `sagaz.yaml` exists in your project root or specify the path:
```python
config = SagaConfig.from_file("path/to/sagaz.yaml")
```

### "Required variable not set"

Check which variable is missing in the error message and set it:
```bash
export SAGAZ_STORAGE_PASSWORD=your_password
```

Or add to `.env`:
```bash
SAGAZ_STORAGE_PASSWORD=your_password
```

### Variables not being substituted

1. Check syntax: `${VAR}` not `$VAR` (requires braces)
2. Ensure `.env` is in project root or loaded manually
3. Verify variable names match exactly (case-sensitive)

### `.env` file not loading

```python
from sagaz.core.env import load_env

# Manually load with path
load_env("/path/to/project")
```

## Migration from Old Config

If you have existing hardcoded configs:

### Before
```yaml
storage:
  connection:
    host: localhost
    password: mypassword  # Committed to git ❌
```

### After
```yaml
storage:
  connection:
    host: "${SAGAZ_STORAGE_HOST:-localhost}"
    password: "${SAGAZ_STORAGE_PASSWORD:?Password required}"
```

```bash
# .env (not committed)
SAGAZ_STORAGE_PASSWORD=mypassword
```

## Further Reading

- [ADR-015: Environment Variable Management](../architecture/adr/adr-015-environment-variable-management.md)
- [12-Factor App: Config](https://12factor.net/config)
- [python-dotenv Documentation](https://pypi.org/project/python-dotenv/)
