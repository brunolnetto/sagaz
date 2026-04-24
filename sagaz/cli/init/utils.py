"""
Common utilities for Sagaz CLI initialization.
"""

import importlib.resources as pkg_resources
from pathlib import Path

import click

try:
    from rich.console import Console
    console: Console | None = Console()
except ImportError:
    console = None


def copy_resource(resource_path: str, target_path: str):
    """Copy a resource file from the package to the target path."""
    try:
        content = (
            pkg_resources.files("sagaz.resources")
            .joinpath(resource_path)
            .read_text(encoding="utf-8")
        )
        Path(target_path).write_text(content, encoding="utf-8")
        click.echo(f"  CREATE {target_path}")
    except Exception as e:
        click.echo(f"  ERROR copying {resource_path}: {e}")


def copy_dir_resource(resource_dir: str, target_dir: str) -> None:
    """Recursively copy a directory from the package resources."""
    try:
        traversable_dir = pkg_resources.files("sagaz.resources").joinpath(resource_dir)
        try:
            list(traversable_dir.iterdir())
        except (FileNotFoundError, TypeError):
            return

        Path(target_dir).mkdir(parents=True, exist_ok=True)
        for item in traversable_dir.iterdir():
            if item.is_dir():
                copy_dir_resource(f"{resource_dir}/{item.name}", f"{target_dir}/{item.name}")
            else:
                try:
                    text_content = item.read_text(encoding="utf-8")
                    Path(target_dir, item.name).write_text(text_content, encoding="utf-8")
                except UnicodeDecodeError:
                    binary_content = item.read_bytes()
                    Path(target_dir, item.name).write_bytes(binary_content)
                click.echo(f"  CREATE {target_dir}/{item.name}")
    except Exception:
        pass


def copy_example_saga(example_template: str, target_dir: Path):
    """Copy an example saga from the package to the target directory."""
    try:
        if example_template == "simple":
            simple_content = 'from sagaz import Saga, action\n\nclass ExampleSaga(Saga):\n    @action("initialize")\n    async def initialize(self, ctx):\n        return {"initialized": True}'
            (target_dir / "example_saga.py").write_text(simple_content)
            return

        source_path = pkg_resources.files("sagaz.examples").joinpath(example_template)
        try:
            main_py = source_path.joinpath("main.py")
            content = main_py.read_text()
            saga_filename = example_template.split("/")[-1] + "_saga.py"
            (target_dir / saga_filename).write_text(content)
        except Exception:
            copy_example_saga("simple", target_dir)
    except Exception as e:
        click.echo(f"  ERROR: {e}")
