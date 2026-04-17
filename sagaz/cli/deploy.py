"""
Sagaz CLI — Cloud Deploy & Destroy Commands.

Provides commands for deploying and tearing down sagaz instances
on cloud platforms (AWS, GCP, Azure, Docker, Kubernetes).
"""

from __future__ import annotations

import click


@click.group("deploy")
def deploy_cmd() -> None:
    """Deploy sagaz to a cloud platform or local container runtime."""


@deploy_cmd.command("docker")
@click.option("--tag", default="latest", show_default=True, help="Image tag to deploy.")
@click.option(
    "--env", type=click.Choice(["dev", "staging", "prod"]), default="dev", show_default=True
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview actions without executing.")
def deploy_docker(tag: str, env: str, dry_run: bool) -> None:
    """Deploy sagaz using Docker Compose."""
    if dry_run:
        click.echo(f"[dry-run] Would deploy tag={tag} to Docker ({env}).")
        return
    click.echo(f"Deploying sagaz:{tag} via Docker Compose (env={env}) …")


@deploy_cmd.command("kubernetes")
@click.option("--namespace", default="sagaz", show_default=True, help="Kubernetes namespace.")
@click.option("--tag", default="latest", show_default=True, help="Image tag to deploy.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview actions without executing.")
def deploy_kubernetes(namespace: str, tag: str, dry_run: bool) -> None:
    """Deploy sagaz to a Kubernetes cluster."""
    if dry_run:
        click.echo(f"[dry-run] Would deploy tag={tag} to namespace={namespace}.")
        return
    click.echo(f"Deploying sagaz:{tag} to Kubernetes namespace={namespace} …")


@click.group("destroy")
def destroy_cmd() -> None:
    """Tear down a deployed sagaz instance."""


@destroy_cmd.command("docker")
@click.option(
    "--env", type=click.Choice(["dev", "staging", "prod"]), default="dev", show_default=True
)
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompt.")
def destroy_docker(env: str, yes: bool) -> None:
    """Tear down the Docker Compose deployment."""
    if not yes:
        click.confirm(f"Destroy sagaz Docker deployment (env={env})?", abort=True)
    click.echo(f"Destroying sagaz Docker deployment (env={env}) …")


@destroy_cmd.command("kubernetes")
@click.option("--namespace", default="sagaz", show_default=True, help="Kubernetes namespace.")
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompt.")
def destroy_kubernetes(namespace: str, yes: bool) -> None:
    """Tear down the Kubernetes deployment."""
    if not yes:
        click.confirm(f"Destroy sagaz in namespace={namespace}?", abort=True)
    click.echo(f"Destroying sagaz Kubernetes deployment (namespace={namespace}) …")
