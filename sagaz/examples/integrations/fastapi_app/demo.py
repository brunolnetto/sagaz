"""
FastAPI Integration Demo

This is a non-blocking demonstration script that:
1. Shows how to start the FastAPI server
2. Explains how to test the endpoints
3. Provides example curl commands

To actually run the server, use:
    uvicorn main:app --reload

Or in production:
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
"""

import sys
from pathlib import Path


def main():
    """Display FastAPI integration demo instructions."""
    print("=" * 70)
    print("FASTAPI INTEGRATION EXAMPLE - Sagaz")
    print("=" * 70)
    print()
    print("📦 This example demonstrates native FastAPI integration with Sagaz:")
    print("   • Async saga execution with dependency injection")
    print("   • Background task processing")
    print("   • Correlation ID middleware")
    print("   • OpenAPI/Swagger documentation")
    print()
    print("=" * 70)
    print("📋 PREREQUISITES")
    print("=" * 70)
    print()

    # Check if dependencies are installed
    try:
        import fastapi
        import uvicorn

        deps_installed = True
    except ImportError:
        deps_installed = False

    if not deps_installed:
        print("⚠️  Required dependencies not installed!")
        print()
        requirements_path = Path(__file__).parent / "requirements.txt"
        print(f"Install with: pip install -r {requirements_path}")
        print()
        return 1
    print("✅ All dependencies installed!")
    print()

    print("=" * 70)
    print("🚀 RUNNING THE SERVER")
    print("=" * 70)
    print()
    print("Start the FastAPI development server:")
    print()
    script_dir = Path(__file__).parent
    print(f"  cd {script_dir}")
    print("  uvicorn main:app --reload")
    print()
    print("Or with custom host/port:")
    print("  uvicorn main:app --host 0.0.0.0 --port 8000")
    print()

    print("=" * 70)
    print("📡 TESTING THE API")
    print("=" * 70)
    print()
    print("Once running, access:")
    print()
    print("  🌐 Swagger UI:    http://localhost:8000/docs")
    print("  📚 ReDoc:         http://localhost:8000/redoc")
    print("  ❤️  Health Check:  http://localhost:8000/health")
    print()

    print("=" * 70)
    print("🔧 EXAMPLE REQUESTS")
    print("=" * 70)
    print()

    print("1️⃣  Health Check:")
    print("   curl http://localhost:8000/health")
    print()

    print("2️⃣  Create Order (Synchronous):")
    print("   curl -X POST http://localhost:8000/orders \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99}\'')
    print()

    print("3️⃣  Create Order (Background):")
    print("   curl -X POST http://localhost:8000/orders/async \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-002", "amount": 149.99}\'')
    print()

    print("4️⃣  Get Saga Diagram:")
    print("   curl http://localhost:8000/orders/ORD-001/diagram")
    print()

    print("5️⃣  With Correlation ID:")
    print("   curl -X POST http://localhost:8000/orders \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -H "X-Correlation-ID: my-trace-123" \\')
    print('        -d \'{"order_id": "ORD-003", "amount": 199.99}\'')
    print()

    print("=" * 70)
    print("💡 KEY FEATURES")
    print("=" * 70)
    print()
    print("• Dependency Injection:")
    print("  Use Depends(saga_factory(OrderSaga)) in route handlers")
    print()
    print("• Background Tasks:")
    print("  Long-running sagas execute without blocking responses")
    print()
    print("• Middleware:")
    print("  SagaContextMiddleware auto-propagates correlation IDs")
    print()
    print("• Lifespan Management:")
    print("  create_lifespan(config) handles startup/shutdown")
    print()

    print("=" * 70)
    print("📖 LEARN MORE")
    print("=" * 70)
    print()
    readme_path = Path(__file__).parent / "README.md"
    print(f"📄 Full documentation: {readme_path}")
    print(f"💻 Source code:       {Path(__file__).parent / 'main.py'}")
    print()
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
