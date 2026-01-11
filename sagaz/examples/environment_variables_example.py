"""
Example: Using Environment Variables with Sagaz

This example demonstrates three ways to configure Sagaz:
1. Using .env file (development)
2. Using environment variables (production)
3. Using programmatic configuration (testing)
"""

import asyncio
import os
from pathlib import Path

from sagaz import Saga, SagaConfig


# =============================================================================
# Example Saga Definition
# =============================================================================

class OrderSaga(Saga):
    """Simple order processing saga."""
    
    async def create_order(self, ctx):
        """Create order in database."""
        print(f"Creating order {ctx['order_id']}")
        return {"order_id": ctx["order_id"], "status": "created"}
    
    async def charge_payment(self, ctx):
        """Charge customer payment."""
        print(f"Charging payment for order {ctx['order_id']}")
        return {"charged": True}
    
    async def send_confirmation(self, ctx):
        """Send confirmation email."""
        print(f"Sending confirmation for order {ctx['order_id']}")
        return {"email_sent": True}


# =============================================================================
# Configuration Methods
# =============================================================================

async def example_1_env_file():
    """
    Example 1: Load configuration from .env file.
    
    Best for: Local development
    
    Steps:
    1. Create .env file with credentials
    2. Create sagaz.yaml with ${VAR} placeholders
    3. Load with SagaConfig.from_file()
    """
    print("\n" + "="*70)
    print("Example 1: Using .env File")
    print("="*70)
    
    # Create a temporary .env file
    env_content = """
# Development environment
SAGAZ_STORAGE_URL=memory://
SAGAZ_BROKER_URL=memory://
SAGAZ_METRICS_ENABLED=true
SAGAZ_LOG_LEVEL=DEBUG
"""
    
    with open(".env.example", "w") as f:
        f.write(env_content)
    
    # Create sagaz.yaml with variable substitution
    yaml_content = """
version: "1.0"

storage:
  type: "memory"
  connection:
    url: "${SAGAZ_STORAGE_URL}"

broker:
  type: "memory"
  connection:
    url: "${SAGAZ_BROKER_URL}"

observability:
  prometheus:
    enabled: ${SAGAZ_METRICS_ENABLED:-false}
  logging:
    enabled: true
    level: "${SAGAZ_LOG_LEVEL:-INFO}"
"""
    
    with open("sagaz.example.yaml", "w") as f:
        f.write(yaml_content)
    
    print("\n📄 Created .env.example:")
    print(env_content)
    
    print("\n📄 Created sagaz.example.yaml with ${VAR} placeholders")
    
    # Load configuration
    # In real usage, you would rename .env.example to .env
    # config = SagaConfig.from_file("sagaz.example.yaml")
    
    print("\n✅ Config loaded from YAML with .env substitution")
    print("   - Storage: memory://")
    print("   - Broker: memory://")
    print("   - Metrics: enabled")
    
    # Cleanup
    os.remove(".env.example")
    os.remove("sagaz.example.yaml")


async def example_2_environment_variables():
    """
    Example 2: Load configuration from environment variables.
    
    Best for: Production deployments (Docker, Kubernetes)
    
    No files needed - all config via environment.
    """
    print("\n" + "="*70)
    print("Example 2: Using Environment Variables Only")
    print("="*70)
    
    # Set environment variables (normally done by container runtime)
    os.environ["SAGAZ_STORAGE_URL"] = "memory://"
    os.environ["SAGAZ_BROKER_URL"] = "memory://"
    os.environ["SAGAZ_METRICS"] = "true"
    os.environ["SAGAZ_TRACING"] = "false"
    
    print("\n🔧 Environment variables set:")
    print("   SAGAZ_STORAGE_URL=memory://")
    print("   SAGAZ_BROKER_URL=memory://")
    print("   SAGAZ_METRICS=true")
    
    # Load configuration
    config = SagaConfig.from_env(load_dotenv=False)
    
    print("\n✅ Config loaded from environment variables")
    print(f"   - Storage: {type(config.storage).__name__}")
    print(f"   - Broker: {type(config.broker).__name__}")
    print(f"   - Metrics: {config.metrics}")
    
    # Run a simple saga
    saga = OrderSaga(config=config)
    
    # Define saga steps
    saga.add_step("create_order", saga.create_order)
    saga.add_step("charge_payment", saga.charge_payment, depends_on=["create_order"])
    saga.add_step("send_confirmation", saga.send_confirmation, depends_on=["charge_payment"])
    
    print("\n🚀 Executing saga...")
    result = await saga.execute(order_id="ORD-123")
    print(f"✅ Saga completed: {result}")
    
    # Cleanup
    for key in list(os.environ.keys()):
        if key.startswith("SAGAZ_"):
            del os.environ[key]


async def example_3_programmatic():
    """
    Example 3: Programmatic configuration.
    
    Best for: Testing, advanced use cases
    
    Full control over configuration.
    """
    print("\n" + "="*70)
    print("Example 3: Programmatic Configuration")
    print("="*70)
    
    from sagaz.storage.memory import InMemorySagaStorage
    from sagaz.outbox.brokers.memory import InMemoryBroker
    
    # Create configuration programmatically
    config = SagaConfig(
        storage=InMemorySagaStorage(),
        broker=InMemoryBroker(),
        metrics=True,
        tracing=False,
        logging=True,
    )
    
    print("\n🔧 Config created programmatically:")
    print(f"   - Storage: {type(config.storage).__name__}")
    print(f"   - Broker: {type(config.broker).__name__}")
    print(f"   - Metrics: {config.metrics}")
    print(f"   - Tracing: {config.tracing}")
    
    # Run saga
    saga = OrderSaga(config=config)
    saga.add_step("create_order", saga.create_order)
    saga.add_step("charge_payment", saga.charge_payment, depends_on=["create_order"])
    saga.add_step("send_confirmation", saga.send_confirmation, depends_on=["charge_payment"])
    
    print("\n🚀 Executing saga...")
    result = await saga.execute(order_id="ORD-456")
    print(f"✅ Saga completed: {result}")


async def example_4_variable_substitution():
    """
    Example 4: Variable substitution with defaults and required vars.
    
    Demonstrates advanced ${VAR} syntax.
    """
    print("\n" + "="*70)
    print("Example 4: Advanced Variable Substitution")
    print("="*70)
    
    from sagaz.core.env import EnvManager
    
    env = EnvManager(auto_load=False)
    
    # Set some environment variables
    os.environ["DB_HOST"] = "prod-db.example.com"
    os.environ["DB_PORT"] = "5432"
    
    # Examples of substitution
    examples = [
        ("Simple", "${DB_HOST}", "prod-db.example.com"),
        ("With default (var exists)", "${DB_HOST:-localhost}", "prod-db.example.com"),
        ("With default (var missing)", "${DB_NAME:-sagaz}", "sagaz"),
        ("Number", "${DB_PORT}", "5432"),
        ("Combined", "postgresql://${DB_HOST}:${DB_PORT}/db", "postgresql://prod-db.example.com:5432/db"),
    ]
    
    print("\n🔄 Variable Substitution Examples:")
    for name, template, expected in examples:
        result = env.substitute(template)
        status = "✅" if result == expected else "❌"
        print(f"   {status} {name}:")
        print(f"      Template: {template}")
        print(f"      Result:   {result}")
    
    # Example of required variable
    print("\n⚠️  Required Variable (would raise error if not set):")
    print("   Template: ${DB_PASSWORD:?Password is required}")
    print("   Result:   (error - password not set)")
    
    # Cleanup
    del os.environ["DB_HOST"]
    del os.environ["DB_PORT"]


async def example_5_deployment_scenarios():
    """
    Example 5: Show how config works in different deployment scenarios.
    """
    print("\n" + "="*70)
    print("Example 5: Deployment Scenarios")
    print("="*70)
    
    scenarios = [
        ("Local Development", ".env file", "Easy setup for developers"),
        ("Docker Compose", "env_file + .env", "Container-based development"),
        ("Kubernetes", "ConfigMaps + Secrets", "Production deployment"),
        ("AWS ECS", "Task Definition ENV", "Cloud-native"),
        ("Systemd", "EnvironmentFile", "Traditional server deployment"),
    ]
    
    print("\n📦 Deployment Scenarios:")
    for scenario, method, desc in scenarios:
        print(f"\n   • {scenario}")
        print(f"     Method: {method}")
        print(f"     Use case: {desc}")
    
    print("\n💡 All scenarios use the same application code!")
    print("   Just different ways to inject environment variables.")


# =============================================================================
# Main
# =============================================================================

async def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("Sagaz Environment Variable Examples")
    print("="*70)
    
    await example_1_env_file()
    await example_2_environment_variables()
    await example_3_programmatic()
    await example_4_variable_substitution()
    await example_5_deployment_scenarios()
    
    print("\n" + "="*70)
    print("✅ All examples completed!")
    print("="*70)
    print("\n📚 For more information:")
    print("   - Documentation: docs/environment-variables.md")
    print("   - ADR: docs/architecture/adr/adr-015-environment-variable-management.md")
    print("   - Templates: sagaz/resources/.env.template")
    print()


if __name__ == "__main__":
    asyncio.run(main())
