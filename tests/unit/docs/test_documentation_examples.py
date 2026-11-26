"""Every example of the documentation runs, and prints what its page shows (#680).

Each ``docs/tour/code/<name>.py`` and ``docs/examples/code/<name>.py`` is included in a
page next to ``<name>.out``, its output. A page therefore cannot show code that fails, nor an output the code does not
produce. To record an output again after changing an example::

    python docs/tour/code/<name>.py > docs/tour/code/<name>.out
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"
EXAMPLES = sorted([*DOCS.glob("tour/code/*.py"), *DOCS.glob("examples/code/*.py")])
INCLUDE = re.compile(r'--8<-- "([\w./-]+)"')
PAGES = sorted(path for path in DOCS.rglob("*.md") if "archive" not in path.parts)


def test_there_are_examples():
    assert len(EXAMPLES) >= 13


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda path: path.stem)
def test_the_example_prints_what_its_page_shows(example: Path):
    expected = example.with_suffix(".out")
    assert expected.exists(), f"record it: python {example} > {expected}"
    run = subprocess.run(  # noqa: S603 - a file of this repository, run by this interpreter
        [sys.executable, str(example)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert run.stderr == "", "an example prints nothing but its output"
    assert run.stdout == expected.read_text(encoding="utf-8")


def included() -> set[str]:
    return {name for page in PAGES for name in INCLUDE.findall(page.read_text(encoding="utf-8"))}


def test_every_example_is_shown_on_a_page_with_its_output():
    shown = included()
    for example in EXAMPLES:
        for file in (example, example.with_suffix(".out")):
            path = file.relative_to(ROOT).as_posix()
            assert path in shown, f"{path} is on no page"


def test_every_include_points_to_a_file():
    for name in included():
        assert (ROOT / name).is_file(), f"a page includes {name}, which does not exist"


def test_the_home_page_shows_the_first_example_as_it_is():
    """The home page is also read on GitHub, where an include would not render."""
    home = (DOCS / "README.md").read_text(encoding="utf-8")
    assert (DOCS / "tour/code/first_saga.py").read_text(encoding="utf-8").rstrip() in home
    assert (DOCS / "tour/code/first_saga.out").read_text(encoding="utf-8").rstrip() in home


def test_the_catalogue_lists_every_shipped_example():
    from sagaz.cli._examples_discovery import discover_examples

    catalogue = (DOCS / "examples/shipped.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"\| \[`(\w+)`\]", catalogue))
    shipped = {name.rsplit("/", 1)[-1] for name in discover_examples()}
    assert listed == shipped
    assert f"{len(shipped)} scenarios" in (DOCS / "examples/index.md").read_text(encoding="utf-8")
