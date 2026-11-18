"""``sagaz deploy`` and ``sagaz teardown``: the sagaz worker stack on AWS, GCP or Kubernetes (#49).

- ``aws``: ECS Fargate + RDS PostgreSQL + ElastiCache Redis (Terraform)
- ``gcp``: Cloud Run + Cloud SQL PostgreSQL + Memorystore Redis (Terraform)
- ``k8s``: the sagaz Helm chart in the current kube context

Guide: docs/guides/cloud-deployment.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from sagaz.cli._deploy_cost import estimate, render, tf_defaults
from sagaz.cli._deploy_runner import HelmRelease, TerraformStack, module_files

PROVIDERS = ("aws", "gcp", "k8s")


def parse_vars(pairs: tuple[str, ...]) -> dict[str, Any]:
    """``KEY=VALUE`` pairs; values are JSON when they parse as JSON (numbers, booleans)."""
    variables: dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            msg = f"--var expects KEY=VALUE, got {pair!r}"
            raise click.BadParameter(msg, param_hint="--var")
        try:
            variables[key] = json.loads(raw)
        except ValueError:
            variables[key] = raw
    return variables


def split_image(image: str) -> tuple[str, str | None]:
    """``registry/repo:tag`` → (``registry/repo``, ``tag``); a registry port is not a tag."""
    repository, sep, tag = image.rpartition(":")
    if sep and "/" not in tag:
        return repository, tag
    return image, None


def _state_dir(provider: str, state_dir: Path | None) -> Path:
    return state_dir or Path(".sagaz") / "deploy" / provider


def _terraform_variables(provider: str, options: dict[str, Any]) -> dict[str, Any]:
    variables = {"name": options["name"], **parse_vars(options["variables"])}
    for option, variable in (
        ("image", "image"),
        ("region", "region"),
        ("project_id", "project_id"),
    ):
        if options.get(option):
            variables[variable] = options[option]
    if "image" not in variables:
        msg = "--image is required for cloud deployments (a pushed sagaz worker image)"
        raise click.UsageError(msg)
    if provider == "gcp" and "project_id" not in variables:
        msg = "--project-id is required for --provider gcp"
        raise click.UsageError(msg)
    return variables


def _print_cost(provider: str, variables: dict[str, Any]) -> None:
    module = module_files(provider)
    cost = json.loads(module.joinpath("cost.json").read_text())
    defaults = tf_defaults(module.joinpath("variables.tf").read_text())
    click.echo(render(estimate(cost, {**defaults, **variables})))
    click.echo()


def _deploy_terraform(provider: str, options: dict[str, Any]) -> None:
    variables = _terraform_variables(provider, options)
    if options["cost_estimate"]:
        _print_cost(provider, variables)
    stack = TerraformStack(provider, _state_dir(provider, options["state_dir"]))
    stack.prepare(variables)
    stack.init()
    stack.plan()
    if options["dry_run"]:
        click.echo(f"Dry run: nothing was changed. The plan is in {stack.state_dir}.")
        return
    if not options["yes"]:
        click.confirm(f"Apply this plan to {provider}?", abort=True)
    stack.apply()
    click.echo(f"Deployed sagaz to {provider}. State: {stack.state_dir}")
    for key, value in sorted(stack.outputs().items()):
        click.echo(f"  {key}: {value}")


def _helm_sets(options: dict[str, Any]) -> dict[str, str]:
    sets: dict[str, str] = {}
    if options.get("image"):
        repository, tag = split_image(options["image"])
        sets["image.repository"] = repository
        if tag:
            sets["image.tag"] = tag
    sets.update({key: str(value) for key, value in parse_vars(options["variables"]).items()})
    return sets


def _deploy_k8s(options: dict[str, Any]) -> None:
    if options["cost_estimate"]:
        click.echo("Kubernetes: the cost depends on your cluster; no estimate is made.\n")
    release = HelmRelease(options["name"], options["namespace"])
    sets = _helm_sets(options)
    if options["dry_run"]:
        release.template(sets, options["values_files"])
        click.echo("Dry run: rendered the manifests; nothing was installed.", err=True)
        return
    if not options["yes"]:
        click.confirm(
            f"Install release '{release.name}' in namespace '{release.namespace}'"
            " of the current kube context?",
            abort=True,
        )
    release.install(sets, options["values_files"])
    click.echo(f"Installed release '{release.name}' in namespace '{release.namespace}'.")


@click.command("deploy")
@click.option("--provider", type=click.Choice(PROVIDERS), required=True)
@click.option("--image", help="Worker image, e.g. ghcr.io/acme/sagaz-worker:1.9.0.")
@click.option("--name", default="sagaz", show_default=True, help="Resource / release name.")
@click.option("--region", help="Cloud region (aws, gcp).")
@click.option("--project-id", help="GCP project id (gcp).")
@click.option("--namespace", default="sagaz", show_default=True, help="Namespace (k8s).")
@click.option(
    "--values",
    "values_files",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Helm values file (k8s); repeatable.",
)
@click.option(
    "--var",
    "variables",
    multiple=True,
    metavar="KEY=VALUE",
    help="Terraform variable (aws, gcp) or Helm value (k8s); repeatable.",
)
@click.option(
    "--state-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Terraform working directory [default: .sagaz/deploy/<provider>].",
)
@click.option("--cost-estimate", is_flag=True, help="Print the estimated monthly cost first.")
@click.option("--dry-run", is_flag=True, help="Show the Terraform plan / Helm manifests only.")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def deploy_cmd(provider: str, **options: Any) -> None:
    """Deploy the sagaz worker stack to AWS, GCP or Kubernetes.

    \b
    Examples:
        sagaz deploy --provider aws --image ghcr.io/acme/sagaz:1.9.0 --cost-estimate
        sagaz deploy --provider gcp --project-id acme --image REGION-docker.pkg.dev/acme/sagaz:1.9.0
        sagaz deploy --provider k8s --namespace sagaz --values my-values.yaml --dry-run
    """
    if provider == "k8s":
        _deploy_k8s(options)
    else:
        _deploy_terraform(provider, options)


@click.command("teardown")
@click.option("--provider", type=click.Choice(PROVIDERS), required=True)
@click.option("--name", default="sagaz", show_default=True, help="Release name (k8s).")
@click.option("--namespace", default="sagaz", show_default=True, help="Namespace (k8s).")
@click.option(
    "--state-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Terraform working directory of the deployment [default: .sagaz/deploy/<provider>].",
)
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def teardown_cmd(
    provider: str, name: str, namespace: str, state_dir: Path | None, yes: bool
) -> None:
    """Destroy a sagaz deployment created with ``sagaz deploy``.

    Cloud deployments delete the database and everything in it.
    """
    if provider == "k8s":
        if not yes:
            click.confirm(f"Uninstall release '{name}' from namespace '{namespace}'?", abort=True)
        HelmRelease(name, namespace).uninstall()
        click.echo(f"Uninstalled release '{name}'.")
        return

    stack = TerraformStack(provider, _state_dir(provider, state_dir))
    deployed = stack.recorded_variables().get("name", "sagaz")
    if not yes:
        typed = click.prompt(
            f"This destroys the '{deployed}' stack on {provider}, including its database. "
            f"Type '{deployed}' to confirm"
        )
        if typed != deployed:
            raise click.Abort
    stack.init()
    stack.destroy()
    click.echo(f"Destroyed the '{deployed}' stack on {provider}.")
