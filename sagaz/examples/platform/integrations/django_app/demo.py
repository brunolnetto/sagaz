"""
Django Integration Demo

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
        import django

        return True
    except ImportError:
        return False


def install_dependencies():
    """Offer to install required dependencies."""
    requirements_path = Path(__file__).parent / "requirements.txt"
    print("\n⚠️  Required dependencies not installed!")
    print("\n📦 Required: django")
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
    """Display Django integration demo and optionally run server."""
    print("=" * 70)
    print("DJANGO INTEGRATION EXAMPLE - Sagaz")
    print("=" * 70)
    print()
    print("📦 This example demonstrates native Django integration with Sagaz:")
    print("   • Django app with saga-backed views")
    print("   • Management commands for saga operations")
    print("   • Middleware for correlation ID tracking")
    print("   • Celery integration for background execution")
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
    print("  🏠 Home Page:     http://localhost:8000/")
    print("  📊 Admin Panel:   http://localhost:8000/admin/")
    print("  ❤️  Health Check:  http://localhost:8000/health/")
    print()

    print("=" * 70)
    print("🔧 EXAMPLE REQUESTS YOU CAN MAKE")
    print("=" * 70)
    print()

    print("1️⃣  Health Check:")
    print("   curl http://localhost:8000/health/")
    print()

    print("2️⃣  Get Saga Diagram:")
    print("   curl http://localhost:8000/orders/ORD-001/diagram/")
    print()

    print("3️⃣  Trigger Order Saga via Webhook (Fire-and-Forget):")
    print("   curl -X POST http://localhost:8000/webhooks/order_created/ \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99, "user_id": "user-123"}\'')
    print()
    print('   ✓ Returns: {"status": "accepted", "correlation_id": "abc-123-..."}')
    print()

    print("4️⃣  Check Webhook Status (use correlation_id from step 3):")
    print("   curl http://localhost:8000/webhooks/order_created/status/<correlation_id>/")
    print()
    print("   Example:")
    print("   curl http://localhost:8000/webhooks/order_created/status/abc-123-xyz/")
    print()
    print("   ⏱️  Status values:")
    print("     • queued → Event received, not processed yet")
    print("     • processing → Firing event to trigger sagas")
    print("     • triggered → Sagas running in background (poll for updates)")
    print("     • completed → All sagas succeeded")
    print("     • completed_with_failures → Some sagas succeeded, some failed")
    print("     • failed → All sagas failed")
    print()

    print("5️⃣  Trigger with High Amount (will fail payment):")
    print("   curl -X POST http://localhost:8000/webhooks/order_created/ \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "FAIL-001", "amount": 1500.00, "user_id": "user-456"}\'')
    print()
    print("   Then check status after 1 second:")
    print(
        "   sleep 1 && curl http://localhost:8000/webhooks/order_created/status/<correlation_id>/"
    )
    print("   (Should show 'failed' with error details)")
    print()

    print("6️⃣  With Custom Correlation ID for Tracing:")
    print("   curl -X POST http://localhost:8000/webhooks/order_created/ \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -H "X-Correlation-ID: my-trace-456" \\')
    print('        -d \'{"order_id": "ORD-003", "amount": 299.99, "user_id": "user-789"}\'')
    print()
    print("   Then check status:")
    print("   curl http://localhost:8000/webhooks/order_created/status/my-trace-456/")
    print()

    print("⚠️  IDEMPOTENCY: Same order_id triggers same saga (deduplication)")
    print("   Each correlation_id tracks a separate webhook invocation")
    print("   If you send order_id='ORD-001' again, webhook returns existing saga status")
    print()
    print("i️  Webhooks execute sagas asynchronously. Poll status endpoint for updates.")
    print()

    print("=" * 70)
    print("🛠️  MANAGEMENT COMMANDS YOU CAN RUN")
    print("=" * 70)
    print()
    print("  python manage.py list_sagas")
    print("  python manage.py replay_saga <saga_id>")
    print("  python manage.py cleanup_old_sagas --days 30")
    print()

    # Ask if user wants to run migrations and server
    print("=" * 70)
    print("🚀 START SERVER?")
    print("=" * 70)
    print()
    script_dir = Path(__file__).parent
    print("The Django server will start on http://localhost:8000")
    print("Note: This will run migrations first if needed.")
    print("Press Ctrl+C to stop the server when done testing.")
    print()

    response = input("Start the server now? (Y/n): ").strip().lower()
    if response in ("", "y", "yes"):
        print("\n📦 Running migrations...")
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

                print(f"\n📡 Server will start on http://localhost:{port}")
                print()

        try:
            subprocess.run(
                [sys.executable, "manage.py", "migrate"],
                cwd=script_dir,
                check=True,
            )
            print("\n✅ Migrations completed!")
            print("\n🚀 Starting Django server...")
            print("-" * 70)
            subprocess.run(
                [sys.executable, "manage.py", "runserver", f"0.0.0.0:{port}"],
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
    print("Start the Django development server:")
    print()
    print(f"  cd {script_dir}")
    print("  python manage.py migrate  # Run migrations first")
    print("  python manage.py runserver")
    print()
    print("Or with custom host/port:")
    print("  python manage.py runserver 0.0.0.0:8000")
    print()

    print("=" * 70)
    print("📡 TESTING THE API")
    print("=" * 70)
    print()
    print("Once running, access:")
    print()
    print("  🏠 Home Page:     http://localhost:8000/")
    print("  📊 Admin Panel:   http://localhost:8000/admin/")
    print("  ❤️  Health Check:  http://localhost:8000/health/")
    print()

    print("=" * 70)
    print("🔧 EXAMPLE REQUESTS")
    print("=" * 70)
    print()

    print("1️⃣  Health Check:")
    print("   curl http://localhost:8000/health/")
    print()

    print("2️⃣  Get Saga Diagram:")
    print("   curl http://localhost:8000/orders/ORD-001/diagram/")
    print()

    print("3️⃣  Trigger Order Saga via Webhook (Fire-and-Forget):")
    print("   curl -X POST http://localhost:8000/webhooks/order_created/ \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99, "user_id": "user-123"}\'')
    print()

    print("4️⃣  Check Webhook Status:")
    print("   curl http://localhost:8000/webhooks/order_created/status/<correlation_id>/")
    print()

    print("5️⃣  Trigger with High Amount (will fail payment):")
    print("   curl -X POST http://localhost:8000/webhooks/order_created/ \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-002", "amount": 1500.00, "user_id": "user-456"}\'')
    print()

    print("=" * 70)
    print("🛠️  MANAGEMENT COMMANDS")
    print("=" * 70)
    print()

    print("Run custom Django management commands:")
    print()
    print("  python manage.py list_sagas")
    print("  python manage.py replay_saga <saga_id>")
    print("  python manage.py cleanup_old_sagas --days 30")
    print()

    print("=" * 70)
    print("💡 KEY FEATURES")
    print("=" * 70)
    print()
    print("• Django Apps:")
    print("  Saga models, views, and admin integration")
    print()
    print("• Middleware:")
    print("  Request correlation ID tracking and propagation")
    print()
    print("• Management Commands:")
    print("  CLI tools for saga operations and maintenance")
    print()
    print("• ORM Integration:")
    print("  Store saga state in Django models")
    print()

    print("=" * 70)
    print("📖 LEARN MORE")
    print("=" * 70)
    print()
    readme_path = Path(__file__).parent / "README.md"
    print(f"📄 Full documentation: {readme_path}")
    print(f"💻 Source code:       {Path(__file__).parent}")
    print()
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
