"""Package resource copy utilities used by the deployment initialization handlers."""

import importlib.resources as pkg_resources
from pathlib import Path
from typing import Any

import click


def _resources() -> Any:
    """Deployment templates shipped in the wheel under ``sagaz/deployment/resources``.

    ``sagaz/deployment`` is not a Python package, so the templates are addressed
    from the ``sagaz`` package root (see ``[tool.setuptools.package-data]``).
    """
    return pkg_resources.files("sagaz").joinpath("deployment", "resources")


def _copy_example_saga(example_template: str, target_dir: Path):
    """Copy an example saga from the package to the target directory."""
    try:
        # Map simple name to full path
        if example_template == "simple":
            # Create simple inline example
            simple_content = """from sagaz import Saga, action, SagaContext


class ExampleSaga(Saga):
    \"\"\"
    Simple example saga demonstrating basic multi-step workflow.

    This saga shows:
    - Sequential step execution with dependencies
    - Context passing between steps
    - Compensation handlers for rollback
    \"\"\"

    @action("initialize")
    async def initialize(self, ctx: SagaContext):
        \"\"\"Initialize the workflow.\"\"\"
        print("Initializing workflow")
        return {"initialized": True}

    @action("process", depends_on=["initialize"])
    async def process(self, ctx: SagaContext):
        \"\"\"Main processing step.\"\"\"
        print("Processing data")
        return {"processed": True}

    @action("finalize", depends_on=["process"])
    async def finalize(self, ctx: SagaContext):
        \"\"\"Finalize the workflow.\"\"\"
        print("Finalizing workflow")
        return {"completed": True}
"""
            (target_dir / "example_saga.py").write_text(simple_content)
            click.echo(f"  CREATE {target_dir / 'example_saga.py'}")
            return

        # Try to copy from package examples
        source_path = pkg_resources.files("sagaz.examples").joinpath(example_template)

        # Copy main.py if it exists
        try:
            main_py = source_path.joinpath("main.py")
            content = main_py.read_text()

            # Extract saga class name from path for filename
            saga_filename = example_template.split("/")[-1] + "_saga.py"
            (target_dir / saga_filename).write_text(content)
            click.echo(f"  CREATE {target_dir / saga_filename}")
        except Exception:
            click.echo(f"  WARNING: Could not copy example '{example_template}'")
            click.echo("           Creating simple example instead")
            _copy_example_saga("simple", target_dir)

    except Exception as e:
        click.echo(f"  ERROR: {e}")
        click.echo("  Creating empty project")


def _copy_dir_resource(resource_dir: str, target_dir: str) -> None:
    """Recursively copy a directory from the package resources."""
    try:
        traversable_dir = _resources().joinpath(resource_dir)
        # Check if directory exists (Traversable may not have exists())
        try:
            list(traversable_dir.iterdir())  # Will raise if doesn't exist
        except (FileNotFoundError, TypeError):
            return

        Path(target_dir).mkdir(parents=True, exist_ok=True)
        for item in traversable_dir.iterdir():
            if item.is_dir():
                _copy_dir_resource(f"{resource_dir}/{item.name}", f"{target_dir}/{item.name}")
            else:
                try:
                    text_content = item.read_text(encoding="utf-8")
                    Path(target_dir, item.name).write_text(text_content, encoding="utf-8")
                except UnicodeDecodeError:
                    binary_content = item.read_bytes()
                    Path(target_dir, item.name).write_bytes(binary_content)
                click.echo(f"  CREATE {target_dir}/{item.name}")
    except Exception:
        # Silently fail if dir doesn't exist, it's optional for some presets
        pass


def _copy_resource(resource_path: str, target_path: str):
    """Copy a resource file from the package to the target path."""
    try:
        content = _resources().joinpath(resource_path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as e:
        # A required template is missing from the installation: stop instead of
        # reporting a successful setup with files silently absent.
        msg = f"Template '{resource_path}' is not available in this sagaz installation: {e}"
        raise click.ClickException(msg) from e
    Path(target_path).write_text(content, encoding="utf-8")
    click.echo(f"  CREATE {target_path}")
