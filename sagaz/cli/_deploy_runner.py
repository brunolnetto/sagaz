"""Terraform and Helm execution behind ``sagaz deploy`` / ``sagaz teardown`` (#49).

The Terraform modules and the Helm chart ship in the package under
``sagaz/deployment/resources/{infra,charts}``. A Terraform module is copied into a
local state directory (default ``.sagaz/deploy/<provider>``) on every deploy, so
the state and provider cache live with the project; the variables used are
written to ``sagaz.auto.tfvars.json`` there, so ``teardown`` destroys exactly
what was created.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from sagaz.cli._deploy_resources import _resources

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

TFVARS = "sagaz.auto.tfvars.json"
PLAN = "sagaz.tfplan"


def require_tool(tool: str) -> str:
    """Absolute path of ``tool`` on PATH, or a CLI error explaining how to get it."""
    path = shutil.which(tool)
    if path is None:
        links = {
            "terraform": "https://developer.hashicorp.com/terraform/install",
            "helm": "https://helm.sh/docs/intro/install/",
        }
        msg = f"'{tool}' is required but was not found on PATH ({links.get(tool, '')})"
        raise click.ClickException(msg)
    return path


def run(command: Sequence[str], cwd: Path | None = None) -> None:
    """Run a tool, streaming its output; a non-zero exit becomes a CLI error."""
    click.echo(f"$ {' '.join(command)}", err=True)
    result = subprocess.run(list(command), cwd=cwd, check=False)
    if result.returncode != 0:
        msg = f"{Path(command[0]).name} exited with status {result.returncode}"
        raise click.ClickException(msg)


def module_files(provider: str) -> Any:
    """The packaged Terraform module of ``provider`` (a Traversable)."""
    module = _resources().joinpath("infra", provider)
    if not module.joinpath("main.tf").is_file():
        msg = f"No Terraform module for '{provider}' in this sagaz installation"
        raise click.ClickException(msg)
    return module


def chart_path() -> Path:
    """Filesystem path of the packaged Helm chart."""
    chart = Path(str(_resources().joinpath("charts", "sagaz")))
    if not (chart / "Chart.yaml").is_file():
        msg = "The sagaz Helm chart is not available in this sagaz installation"
        raise click.ClickException(msg)
    return chart


def _copy_tree(source: Traversable, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_dir():
            _copy_tree(item, target / item.name)
        else:
            (target / item.name).write_bytes(item.read_bytes())


class TerraformStack:
    """One provider's Terraform working directory with sagaz's module in it."""

    def __init__(self, provider: str, state_dir: Path) -> None:
        self.provider = provider
        self.state_dir = state_dir
        self.terraform = require_tool("terraform")

    @property
    def tfvars_path(self) -> Path:
        return self.state_dir / TFVARS

    def prepare(self, variables: dict[str, Any]) -> None:
        """Refresh the module files and record ``variables`` (state is kept)."""
        _copy_tree(module_files(self.provider), self.state_dir)
        self.tfvars_path.write_text(json.dumps(variables, indent=2, sort_keys=True) + "\n")

    def recorded_variables(self) -> dict[str, Any]:
        if not self.tfvars_path.is_file():
            msg = f"No sagaz deployment found in {self.state_dir} (nothing to tear down)"
            raise click.ClickException(msg)
        data: dict[str, Any] = json.loads(self.tfvars_path.read_text())
        return data

    def _terraform(self, *args: str) -> None:
        run([self.terraform, *args], cwd=self.state_dir)

    def init(self) -> None:
        self._terraform("init", "-input=false")

    def plan(self) -> None:
        self._terraform("plan", "-input=false", f"-out={PLAN}")

    def apply(self) -> None:
        self._terraform("apply", "-input=false", PLAN)

    def destroy(self) -> None:
        self._terraform("destroy", "-input=false", "-auto-approve")

    def outputs(self) -> dict[str, Any]:
        """Non-sensitive outputs (``terraform output -json``)."""
        result = subprocess.run(
            [self.terraform, "output", "-json"],
            cwd=self.state_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        raw: dict[str, Any] = json.loads(result.stdout)
        return {k: v.get("value") for k, v in raw.items() if not v.get("sensitive")}


class HelmRelease:
    """The sagaz Helm release in a namespace of the current kube context."""

    def __init__(self, name: str, namespace: str) -> None:
        self.name = name
        self.namespace = namespace
        self.helm = require_tool("helm")

    def _values_args(self, sets: dict[str, str], values_files: Sequence[str]) -> list[str]:
        args: list[str] = []
        for path in values_files:
            args += ["-f", path]
        for key, value in sets.items():
            args += ["--set", f"{key}={value}"]
        return args

    def template(self, sets: dict[str, str], values_files: Sequence[str]) -> None:
        """Render the manifests locally (no cluster needed)."""
        run(
            [
                self.helm,
                "template",
                self.name,
                str(chart_path()),
                "--namespace",
                self.namespace,
                *self._values_args(sets, values_files),
            ]
        )

    def install(self, sets: dict[str, str], values_files: Sequence[str]) -> None:
        run(
            [
                self.helm,
                "upgrade",
                "--install",
                self.name,
                str(chart_path()),
                "--namespace",
                self.namespace,
                "--create-namespace",
                "--wait",
                *self._values_args(sets, values_files),
            ]
        )

    def uninstall(self) -> None:
        run([self.helm, "uninstall", self.name, "--namespace", self.namespace])
