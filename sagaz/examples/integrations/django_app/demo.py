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
    print(f"\n📦 Required: django")
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
    if not check_dependencies():
        if not install_dependencies():
            return 1

    print()
    print("✅ All dependencies installed!")
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
                [sys.executable, "manage.py", "runserver"],
                cwd=script_dir,
                check=True,
            )
        except subprocess.CalledProcessError:
            print("\n❌ Server failed to start.")
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

    print("2️⃣  Create Order:")
    print("   curl -X POST http://localhost:8000/orders/ \\")
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"order_id": "ORD-001", "amount": 99.99}\'')
    print()

    print("3️⃣  Get Order Status:")
    print("   curl http://localhost:8000/orders/ORD-001/")
    print()

    print("4️⃣  List Orders:")
    print("   curl http://localhost:8000/orders/")
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
