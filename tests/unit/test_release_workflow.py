from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "release.yml"
)
SOURCE_SHA = "${{ needs.resolve-version.outputs.source_sha }}"


def _workflow() -> dict:
    return yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def _checkout_step(job: dict) -> dict:
    matches = [
        step
        for step in job["steps"]
        if step.get("uses") == "actions/checkout@v7"
    ]
    assert len(matches) == 1
    return matches[0]


def test_release_workflow_keeps_trusted_publisher_filename() -> None:
    assert WORKFLOW_PATH.is_file()
    assert not WORKFLOW_PATH.with_suffix(".yaml").exists()


def test_publish_and_tag_are_gated_by_the_release_tests() -> None:
    jobs = _workflow()["jobs"]
    assert "test" in jobs["publish"]["needs"]
    assert {"test", "publish"} <= set(jobs["tag-and-release"]["needs"])


def test_release_stages_use_one_pinned_source_commit() -> None:
    jobs = _workflow()["jobs"]
    assert (
        jobs["resolve-version"]["outputs"]["source_sha"]
        == "${{ steps.version.outputs.source_sha }}"
    )
    assert (
        _checkout_step(jobs["resolve-version"])["with"]["ref"]
        == "${{ github.sha }}"
    )
    for name in ("test", "publish", "tag-and-release"):
        assert _checkout_step(jobs[name])["with"]["ref"] == SOURCE_SHA



def test_release_notes_fallback_uses_an_existing_comparison_target() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "compare/${PREVIOUS_TAG}...${SOURCE_SHA}" in workflow
    assert "blob/main/CHANGELOG.md" not in workflow


def test_release_tag_and_github_release_target_main() -> None:
    tag_steps = _workflow()["jobs"]["tag-and-release"]["steps"]
    commands = "\n".join(step.get("run", "") for step in tag_steps)
    assert "HEAD:main" in commands
    assert "--target main" in commands
    assert "HEAD:develop" not in commands
    assert "--target develop" not in commands
