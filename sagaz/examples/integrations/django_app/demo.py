"""
Django Integration Demo

This is a non-blocking demonstration script that:
1. Shows how to start the Django server
2. Explains how to test the endpoints
3. Provides example management commands

To actually run the server, use:
    python manage.py runserver

Or in production:
    gunicorn config.wsgi:application --bind 0.0.0.0:8000
"""

import sys
from pathlib import Path


def main():
    """Display Django integration demo instructions."""
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
    print("=" * 70)
    print("📋 PREREQUISITES")
    print("=" * 70)
    print()

    # Check if dependencies are installed
    try:
        import django

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
    print("Start the Django development server:")
    print()
    script_dir = Path(__file__).parent
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
