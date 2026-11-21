"""Check the built distributions before they are published.

Every file under ``sagaz/`` in the wheel and the sdist must be tracked by git:
files that git ignores (downloaded jars, local caches, generated data) must not
ship. Each artifact must also stay under a size limit.

    python scripts/check_dist.py [dist/]
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024  # the 2.2.0 wheel was ~1.6 MB; 2.3.0 shipped 56.5 MB by mistake


def tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "sagaz"], capture_output=True, check=True
    ).stdout.decode()
    return {name for name in out.split("\0") if name}


def wheel_members(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as wheel:
        return [n for n in wheel.namelist() if n.startswith("sagaz/") and not n.endswith("/")]


def sdist_members(path: Path) -> list[str]:
    with tarfile.open(path) as sdist:
        names = [
            m.name.split("/", 1)[1] for m in sdist.getmembers() if m.isfile() and "/" in m.name
        ]
    return [n for n in names if n.startswith("sagaz/")]


def check(dist: Path) -> list[str]:
    tracked = tracked_files()
    problems = []
    artifacts = sorted([*dist.glob("*.whl"), *dist.glob("*.tar.gz")])
    if not artifacts:
        return [f"no wheel or sdist in {dist}"]
    for artifact in artifacts:
        size = artifact.stat().st_size
        if size > MAX_BYTES:
            problems.append(f"{artifact.name}: {size / 1048576:.1f} MiB > {MAX_BYTES >> 20} MiB")
        members = wheel_members(artifact) if artifact.suffix == ".whl" else sdist_members(artifact)
        untracked = sorted(set(members) - tracked)
        problems += [f"{artifact.name}: untracked file {name}" for name in untracked[:20]]
        if len(untracked) > 20:
            problems.append(f"{artifact.name}: ... and {len(untracked) - 20} more untracked files")
    return problems


def main() -> int:
    dist = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    problems = check(dist)
    for problem in problems:
        print(f"✗ {problem}")
    if not problems:
        print(f"✓ {dist}: only tracked files, every artifact under {MAX_BYTES >> 20} MiB")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
