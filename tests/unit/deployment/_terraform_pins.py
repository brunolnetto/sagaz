"""Provider pinning checks shared by the Terraform module tests (#49).

A provider must be pinned to one major version (``~> N.x``) and the committed
lock file must hold a version of that same major. Renovate bumps both
together; a lock file out of step with ``versions.tf`` fails here.
"""

from __future__ import annotations

import re
from pathlib import Path


def pinned_major(module_dir: Path, provider: str) -> str:
    """The major version ``provider`` is pinned to, checked against the lock file."""
    versions = (module_dir / "versions.tf").read_text()
    pin = re.search(
        rf'source\s*=\s*"hashicorp/{provider}"\s*\n\s*version\s*=\s*"~>\s*(\d+)\.', versions
    )
    assert pin, f"hashicorp/{provider} is not pinned with '~> N.x' in versions.tf"
    lock = (module_dir / ".terraform.lock.hcl").read_text()
    locked = re.search(
        rf'provider "registry\.terraform\.io/hashicorp/{provider}" \{{\s*version\s*=\s*"(\d+)\.',
        lock,
    )
    assert locked, f"hashicorp/{provider} is missing from .terraform.lock.hcl"
    assert locked.group(1) == pin.group(1), (
        f"lock file has {provider} {locked.group(1)}.x but versions.tf pins ~> {pin.group(1)}.x"
    )
    return pin.group(1)
