"""
Execution logic for running Sagaz examples and checking requirements.
"""

import os
import subprocess
import sys
from pathlib import Path

import click

try:
    from rich.console import Console

    console: Console | None = Console()
except ImportError:
    console = None


def execute_example(script_path: Path):
    """Execute an example script with requirements check."""
    requirements_file = script_path.parent / "requirements.txt"
    if requirements_file.exists():
        try:
            _check_requirements(requirements_file)
        except KeyboardInterrupt:
            if console:
                console.print("\n[yellow]Skipped example.[/yellow]")
            else:
                click.echo("\nSkipped example.")
            return

    env = os.environ.copy()
    cwd = Path.cwd()
    env["PYTHONPATH"] = f"{cwd}{os.pathsep}{env.get('PYTHONPATH', '')}"

    try:
        subprocess.run([sys.executable, str(script_path)], env=env, check=True)
    except subprocess.CalledProcessError as e:
        click.echo(f"\nExample failed with exit code {e.returncode}")
        if requirements_file.exists():
            click.echo("\n💡 This example may require additional dependencies.")
            click.echo(f"   Install them with: pip install -r {requirements_file}")
    except KeyboardInterrupt:
        click.echo("\nInterrupted.")


def _check_requirements(requirements_file: Path) -> None:
    """Check if required packages are installed and warn user."""
    try:
        with requirements_file.open() as f:
            reqs = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    except Exception:
        return

    missing_packages = []
    for req in reqs:
        if req.startswith("sagaz"):
            continue
        pkg_name = _parse_package_name(req)
        if not _check_package_installed(pkg_name):
            missing_packages.append(pkg_name)

    if not missing_packages:
        return

    _display_missing_packages(missing_packages, requirements_file)

    if not _prompt_user_continue():
        raise KeyboardInterrupt


def _parse_package_name(req: str) -> str:
    """Extract package name from requirement string."""
    return req.split(">=")[0].split("==")[0].split("<")[0].split(">")[0].strip()


def _check_package_installed(pkg_name: str) -> bool:
    """Check if a package is installed."""
    import importlib.util

    package_to_import = {
        "python-dotenv": "dotenv",
        "pillow": "PIL",
        "opencv-python": "cv2",
        "scikit-learn": "sklearn",
        "beautifulsoup4": "bs4",
        "python-dateutil": "dateutil",
    }
    import_name = package_to_import.get(pkg_name, pkg_name)
    return importlib.util.find_spec(import_name) is not None


def _display_missing_packages(missing_packages: list[str], requirements_file: Path):
    """Display missing packages to user."""
    if console:
        console.print("\n[yellow]⚠️  This example requires additional dependencies:[/yellow]")
        for pkg in missing_packages:
            console.print(f"   • {pkg}")
        console.print(f"\n[cyan]📦 Install with:[/cyan] pip install -r {requirements_file}")
    else:
        click.echo(f"\n⚠️  Missing dependencies: {', '.join(missing_packages)}")
        click.echo(f"Install with: pip install -r {requirements_file}")


def _prompt_user_continue() -> bool:
    """Prompt user to continue despite missing packages."""
    response = input("\nContinue anyway? (y/N): ").strip().lower()
    return response in ("y", "yes")
