"""
Flask Integration Demo

This is a non-blocking demonstration script that:
1. Shows how to start the Flask server
2. Explains how to test the endpoints
3. Provides example curl commands

To actually run the server, use:
    python main.py

Or using Flask CLI:
    flask run --reload
"""

import sys
from pathlib import Path


def main():
    """Display Flask integration demo instructions."""
    print("=" * 70)
    print("FLASK INTEGRATION EXAMPLE - Sagaz")
    print("=" * 70)
    print()
    print("📦 This example demonstrates native Flask integration with Sagaz:")
    print("   • Sync saga execution with Flask extension")
    print("   • Automatic correlation ID propagation")
    print("   • Request lifecycle hooks")
    print("   • Blueprint-based webhook endpoints")
    print()
    print("=" * 70)
    print("📋 PREREQUISITES")
    print("=" * 70)
    print()

    # Check if dependencies are installed
    try:
        import flask

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
    print("Start the Flask development server:")
    print()
    script_dir = Path(__file__).parent
    print(f"  cd {script_dir}")
    print("  python main.py")
    print()
    print("Or using Flask CLI:")
    print("  export FLASK_APP=main")
    print("  flask run --reload")
    print()
    print("Or with custom host/port:")
    print("  flask run --host 0.0.0.0 --port 5000")
    print()

    print("=" * 70)
    print("📡 TESTING THE API")
    print("=" * 70)
    print()
    print("Once running, access:")
    print()
    print("  ❤️  Health Check:  http://localhost:5000/health")
    print("  📊 Order Diagram: http://localhost:5000/orders/ORD-001/diagram")
    print()

    print("=" * 70)
    print("🔧 EXAMPLE REQUESTS")
    print("=" * 70)
    print()

    print("1️⃣  Health Check:")
    print("   curl http://localhost:5000/health")
    print()

    print("2️⃣  Create Order (Using Extension):")
    print("   curl -X POST http://localhost:5000/orders \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99}\'')
    print()

    print("3️⃣  Create Order (Standalone Function):")
    print("   curl -X POST http://localhost:5000/orders/standalone \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-002", "amount": 149.99}\'')
    print()

    print("4️⃣  Get Saga Diagram:")
    print("   curl http://localhost:5000/orders/ORD-001/diagram")
    print()

    print("5️⃣  With Correlation ID:")
    print("   curl -X POST http://localhost:5000/orders \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -H "X-Correlation-ID: my-trace-456" \\')
    print('        -d \'{"order_id": "ORD-003", "amount": 199.99}\'')
    print()

    print("6️⃣  Trigger via Webhook (Event-Driven):")
    print("   curl -X POST http://localhost:5000/webhooks/order.created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-004", "amount": 299.99}\'')
    print()

    print("=" * 70)
    print("💡 KEY FEATURES")
    print("=" * 70)
    print()
    print("• Flask Extension:")
    print("  SagaFlask(app, config) manages lifecycle and resources")
    print()
    print("• Sync Wrapper:")
    print("  run_saga_sync() allows async sagas in sync Flask views")
    print()
    print("• Correlation ID:")
    print("  Auto-extracted from headers and injected into sagas")
    print()
    print("• Webhook Integration:")
    print("  register_webhook_blueprint() for event-driven sagas")
    print()

    print("=" * 70)
    print("⚠️  IMPORTANT NOTES")
    print("=" * 70)
    print()
    print("• Flask is synchronous - each request blocks until saga completes")
    print("• For long-running sagas, consider:")
    print("  - Using FastAPI (async) instead")
    print("  - Offloading to Celery/background workers")
    print("  - Webhook pattern for fire-and-forget")
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
