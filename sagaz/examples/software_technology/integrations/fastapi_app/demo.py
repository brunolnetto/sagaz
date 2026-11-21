"""
FastAPI Integration Demo

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
        import fastapi
        import uvicorn

        return True
    except ImportError:
        return False


def install_dependencies():
    """Offer to install required dependencies."""
    requirements_path = Path(__file__).parent / "requirements.txt"
    print("\n⚠️  Required dependencies not installed!")
    print("\n📦 Required: fastapi, uvicorn")
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
    """Display FastAPI integration demo and optionally run server."""
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
    print("  🌐 Swagger UI:    http://localhost:8000/docs")
    print("  📚 ReDoc:         http://localhost:8000/redoc")
    print("  ❤️  Health Check:  http://localhost:8000/health")
    print("  📊 Order Diagram: http://localhost:8000/orders/<order_id>/diagram")
    print("  🎯 Webhook:       http://localhost:8000/webhooks/<source>")
    print()

    print("=" * 70)
    print("🔧 EXAMPLE REQUESTS YOU CAN MAKE")
    print("=" * 70)
    print()

    print("1️⃣  Health Check:")
    print("   curl http://localhost:8000/health")
    print()

    print("2️⃣  Validate Order Before Processing:")
    print("   curl -X POST http://localhost:8000/orders/validate \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001"}\'')
    print()
    print("   ✓ Checks if order_id is already processed or in progress")
    print("   ✓ Returns validation result and helpful advice")
    print()

    print("3️⃣  Get Saga Diagram:")
    print("   curl http://localhost:8000/orders/ORD-001/diagram")
    print()

    print("4️⃣  Trigger Order Saga via Webhook (Fire-and-Forget):")
    print("   curl -X POST http://localhost:8000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99, "user_id": "user-123"}\'')
    print()
    print('   ✓ Returns: {"status": "accepted", "correlation_id": "..."}')
    print()

    print("5️⃣  Check Webhook Status (use correlation_id from step 4):")
    print("   curl http://localhost:8000/webhooks/order_created/status/<correlation_id>")
    print()
    print("   Example:")
    print("   curl http://localhost:8000/webhooks/order_created/status/abc-123-xyz")
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
    print("   curl -X POST http://localhost:8000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "FAIL-001", "amount": 1500.00, "user_id": "user-456"}\'')
    print()
    print("   Then check status after 1 second:")
    print("   sleep 1 && curl http://localhost:8000/webhooks/order_created/status/<correlation_id>")
    print("   (Should show 'failed' with error details)")
    print()

    print("7️⃣  Try Duplicate Order (Idempotency Test):")
    print("   # Send same order_id again")
    print("   curl -X POST http://localhost:8000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99, "user_id": "user-123"}\'')
    print()
    print("   ✓ Same order_id creates deterministic saga_id (UUID5)")
    print("   ✓ Saga won't re-execute if already completed/in-progress")
    print("   ✓ Status endpoint shows existing saga status")
    print()

    print("8️⃣  With Custom Correlation ID for Tracing:")
    print("   curl -X POST http://localhost:8000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -H "X-Correlation-ID: my-trace-123" \\')
    print('        -d \'{"order_id": "ORD-003", "amount": 299.99, "user_id": "user-789"}\'')
    print()
    print("   Then check status:")
    print("   curl http://localhost:8000/webhooks/order_created/status/my-trace-123")
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
    print("The FastAPI server will start on http://localhost:8000")
    print("Press Ctrl+C to stop the server when done testing.")
    print()

    response = input("Start the server now? (Y/n): ").strip().lower()
    if response in ("", "y", "yes"):
        print("\n🚀 Starting FastAPI server...")
        print("-" * 70)

        # Check if port 8000 is in use
        import socket

        port = 8000
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", port)) == 0:
                print(f"\n⚠️  Port {port} is already in use.")
                alt_port = input("Use alternative port (e.g., 8001)? [8001]: ").strip() or "8001"
                try:
                    port = int(alt_port)
                except ValueError:
                    print("❌ Invalid port number.")
                    return 1

                # Update displayed URLs
                print(f"\n📡 Server will start on http://localhost:{port}")
                print(f"  🌐 Swagger UI:    http://localhost:{port}/docs")
                print(f"  📚 ReDoc:         http://localhost:{port}/redoc")
                print()

        try:
            subprocess.run(
                [sys.executable, "-m", "uvicorn", "main:app", "--reload", "--port", str(port)],
                cwd=script_dir,
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
    print("Start the FastAPI development server:")
    print()
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
    print("  📊 Order Diagram: http://localhost:8000/orders/<order_id>/diagram")
    print("  🎯 Webhook:       http://localhost:8000/webhooks/<source>")
    print()

    print("=" * 70)
    print("🔧 EXAMPLE REQUESTS")
    print("=" * 70)
    print()

    print("1️⃣  Health Check:")
    print("   curl http://localhost:8000/health")
    print()

    print("2️⃣  Validate Order (check for duplicates):")
    print("   curl -X POST http://localhost:8000/orders/validate \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001"}\'')
    print()

    print("3️⃣  Get Saga Diagram:")
    print("   curl http://localhost:8000/orders/ORD-001/diagram")
    print()

    print("4️⃣  Trigger Order Saga via Webhook:")
    print("   curl -X POST http://localhost:8000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99, "user_id": "user-123"}\'')
    print()
    print('   ✓ Returns: {"status": "accepted", "message": "Event queued"}')
    print()

    print("5️⃣  Check Webhook Status:")
    print("   curl http://localhost:8000/webhooks/order_created/status/<correlation_id>")
    print()

    print("6️⃣  Trigger with High Amount (will fail payment):")
    print("   curl -X POST http://localhost:8000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-002", "amount": 1500.00, "user_id": "user-456"}\'')
    print()

    print("7️⃣  With Correlation ID for Tracing:")
    print("   curl -X POST http://localhost:8000/webhooks/order_created \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -H "X-Correlation-ID: my-trace-123" \\')
    print('        -d \'{"order_id": "ORD-003", "amount": 299.99, "user_id": "user-789"}\'')
    print()

    print("i️  Note: Webhooks execute sagas asynchronously in background.")
    print("   Check application logs or use Swagger UI to see execution details.")
    print("   Use /orders/validate to check for duplicate order_ids.")
    print()

    print("=" * 70)
    print("💡 KEY FEATURES")
    print("=" * 70)
    print()
    print("• Webhook Integration:")
    print("  create_webhook_router() provides POST /webhooks/{source}")
    print()
    print("• Trigger Decorator:")
    print("  @trigger maps webhook events to saga execution")
    print()
    print("• Async Native:")
    print("  Full async/await support for high-performance execution")
    print()
    print("• Lifespan Management:")
    print("  sagaz_startup() and sagaz_shutdown() handle lifecycle")
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
