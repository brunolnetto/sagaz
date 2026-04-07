"""
Flask Integration Demo

Interactive demonstration that:
1. Checks dependencies and offers installation
2. Shows usage instructions
3. Optionally runs the server
4. Provides example curl commands

Run with: python demo.py
"""

import subprocess
import sys
from pathlib import Path


def check_dependencies():
    """Check if required dependencies are installed."""
    try:
        import flask

        return True
    except ImportError:
        return False


def install_dependencies():
    """Offer to install required dependencies."""
    requirements_path = Path(__file__).parent / "requirements.txt"
    print("\n⚠️  Required dependencies not installed!")
    print("\n📦 Required: flask")
    print(f"\nInstall command: pip install -r {requirements_path}")

    response = input("\nInstall dependencies now? (y/N): ").strip().lower()
    if response in ("y", "yes"):
        print("\nInstalling dependencies...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)],
                check=True,
            )
            print("✅ Dependencies installed successfully!")
            return True
        except subprocess.CalledProcessError:
            print("❌ Installation failed. Please install manually.")
            return False
    return False


def main():
    """Display Flask integration demo and optionally run server."""
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

    # Check and install dependencies if needed
    if not check_dependencies() and not install_dependencies():
        return 1

    print()
    print("✅ All dependencies installed!")
    print()

    # Show what's available first
    print("=" * 70)
    print("📡 AVAILABLE ENDPOINTS")
    print("=" * 70)
    print()
    print("Once the server starts, you can access:")
    print()
    print("  ❤️  Health Check:  http://localhost:5000/health")
    print("  📊 Order Diagram: http://localhost:5000/orders/<order_id>/diagram")
    print("  🎯 Webhook:       http://localhost:5000/webhooks/<source>")
    print()

    print("=" * 70)
    print("🔧 EXAMPLE REQUESTS YOU CAN MAKE")
    print("=" * 70)
    print()

    print("1️⃣  Health Check:")
    print("   curl http://localhost:5000/health")
    print()

    print("2️⃣  Validate Order Before Processing:")
    print("   curl -X POST http://localhost:5000/orders/validate \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001"}\'')
    print()
    print("   ✓ Checks if order_id is already processed or in progress")
    print("   ✓ Returns validation result and helpful advice")
    print()

    print("3️⃣  Get Saga Diagram:")
    print("   curl http://localhost:5000/orders/ORD-001/diagram")
    print()

    print("4️⃣  Trigger Order Saga via Webhook (Fire-and-Forget):")
    print("   curl -X POST http://localhost:5000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99, "user_id": "user-123"}\'')
    print()
    print('   ✓ Returns: {"status": "accepted", "correlation_id": "..."}')
    print()

    print("5️⃣  Check Webhook Status (use correlation_id from step 4):")
    print("   curl http://localhost:5000/webhooks/order_created/status/<correlation_id>")
    print()
    print("   Example:")
    print("   curl http://localhost:5000/webhooks/order_created/status/abc-123-xyz")
    print()
    print("   ⏱️  Status values:")
    print("     • queued → Event received, not processed yet")
    print("     • processing → Firing event to trigger sagas")
    print("     • triggered → Sagas running in background (poll for updates)")
    print("     • completed → All sagas succeeded")
    print("     • completed_with_failures → Some sagas succeeded, some failed")
    print("     • failed → All sagas failed")
    print()

    print("6️⃣  Trigger with High Amount (will fail payment):")
    print("   curl -X POST http://localhost:5000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "FAIL-001", "amount": 1500.00, "user_id": "user-456"}\'')
    print()
    print("   Then check status after 1 second:")
    print("   sleep 1 && curl http://localhost:5000/webhooks/order_created/status/<correlation_id>")
    print("   (Should show 'completed_with_failures' or 'failed' with error details)")
    print()

    print("7️⃣  Try Duplicate Order (Idempotency Test):")
    print("   # First, validate the order")
    print("   curl -X POST http://localhost:5000/orders/validate \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001"}\'')
    print()
    print("   # Then try to submit it again")
    print("   curl -X POST http://localhost:5000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99, "user_id": "user-123"}\'')
    print()
    print("   ✓ Same order_id creates deterministic saga_id (UUID5)")
    print("   ✓ Saga won't re-execute if already completed/in-progress")
    print("   ✓ Validation endpoint helps prevent duplicate submissions")
    print()

    print("8️⃣  With Custom Correlation ID for Tracing:")
    print("   curl -X POST http://localhost:5000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -H "X-Correlation-ID: my-trace-456" \\')
    print('        -d \'{"order_id": "ORD-004", "amount": 299.99, "user_id": "user-789"}\'')
    print()
    print("   Then check status:")
    print("   curl http://localhost:5000/webhooks/order_created/status/my-trace-456")
    print()

    print("⚠️  IDEMPOTENCY:")
    print("   • Same order_id → same saga_id (deterministic via UUID5)")
    print("   • Already completed/running saga won't re-execute")
    print("   • Each webhook call gets unique correlation_id for tracking")
    print("   • Use /orders/validate endpoint before triggering webhook")
    print()
    print("i️  Webhooks execute sagas asynchronously. Poll status endpoint for updates.")
    print()

    # Ask if user wants to run the server
    print("=" * 70)
    print("🚀 START SERVER?")
    print("=" * 70)
    print()
    script_dir = Path(__file__).parent
    print("The Flask server will start on http://localhost:5000")
    print("Press Ctrl+C to stop the server when done testing.")
    print()

    response = input("Start the server now? (Y/n): ").strip().lower()
    if response in ("", "y", "yes"):
        print("\n🚀 Starting Flask server...")
        print("-" * 70)

        # Check if port 5000 is in use
        import socket

        port = 5000
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", port)) == 0:
                print(f"\n⚠️  Port {port} is already in use.")
                alt_port = input("Use alternative port (e.g., 5001)? [5001]: ").strip() or "5001"
                try:
                    port = int(alt_port)
                except ValueError:
                    print("❌ Invalid port number.")
                    return 1

                # Update displayed URLs
                print(f"\n📡 Server will start on http://localhost:{port}")
                print()

                # Set environment variable for Flask
                import os

                os.environ["FLASK_RUN_PORT"] = str(port)

        try:
            # Use flask run command for better port control
            import os

            os.environ["FLASK_APP"] = str(script_dir / "main.py")
            subprocess.run(
                [sys.executable, "-m", "flask", "run", "--port", str(port)],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print("\n❌ Server failed to start.")
            print(f"\n💡 Error: {e}")
            return 1
        except KeyboardInterrupt:
            print("\n\n✅ Server stopped.")
        return 0

    # Show instructions instead
    print()
    print("=" * 70)
    print("🚀 MANUAL SERVER START")
    print("=" * 70)
    print()
    print("Start the Flask development server:")
    print()
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
    print("  📊 Order Diagram: http://localhost:5000/orders/<order_id>/diagram")
    print("  🎯 Webhook:       http://localhost:5000/webhooks/<source>")
    print()

    print("=" * 70)
    print("🔧 EXAMPLE REQUESTS")
    print("=" * 70)
    print()

    print("1️⃣  Health Check:")
    print("   curl http://localhost:5000/health")
    print()

    print("2️⃣  Get Saga Diagram:")
    print("   curl http://localhost:5000/orders/ORD-001/diagram")
    print()

    print("3️⃣  Trigger Order Saga via Webhook:")
    print("   curl -X POST http://localhost:5000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99, "user_id": "user-123"}\'')
    print()
    print('   ✓ Returns: {"status": "accepted", "correlation_id": "..."}')
    print()

    print("4️⃣  Check Webhook Status:")
    print("   curl http://localhost:5000/webhooks/order_created/status/<correlation_id>")
    print()

    print("5️⃣  Trigger with High Amount (will fail payment):")
    print("   curl -X POST http://localhost:5000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-002", "amount": 1500.00, "user_id": "user-456"}\'')
    print()

    print("6️⃣  With Correlation ID for Tracing:")
    print("   curl -X POST http://localhost:5000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -H "X-Correlation-ID: my-trace-456" \\')
    print('        -d \'{"order_id": "ORD-003", "amount": 299.99, "user_id": "user-789"}\'')
    print()

    print("i️  Note: Webhooks execute sagas asynchronously in background.")
    print("   Use correlation_id to check status, or monitor application logs.")
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
