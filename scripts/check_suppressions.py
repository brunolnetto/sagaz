"""Fail on a suppression comment that does not say what it suppresses, or why (#594).

A marker that silences a tool hides whatever the tool would have said, so each one
must be specific and explained:

- ``# type: ignore`` needs an error code: ``# type: ignore[attr-defined]``.
- ``# noqa`` needs a rule: ``# noqa: E501``.
- ``# nosec`` needs a rule and a reason: ``# nosec B608 - only constants are interpolated``.
- ``# pragma: no cover`` needs a reason: ``# pragma: no cover - the extra is installed``.

Only real comments are checked (the source is tokenized), so a marker quoted inside a
string or a docstring is ignored.

    python scripts/check_suppressions.py [paths...]     # default: sagaz/
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

REASON = r"\s+-\s+\S"
RULES: list[tuple[re.Pattern[str], re.Pattern[str], str]] = [
    (
        re.compile(r"#\s*type:\s*ignore"),
        re.compile(r"#\s*type:\s*ignore\[[\w-]+(,\s*[\w-]+)*\]"),
        "type: ignore needs an error code, e.g. # type: ignore[attr-defined]",
    ),
    (
        re.compile(r"#\s*noqa"),
        re.compile(r"#\s*noqa:\s*[A-Z]+\d+"),
        "noqa needs a rule, e.g. # noqa: E501",
    ),
    (
        re.compile(r"#\s*nosec"),
        re.compile(r"#\s*nosec\s+B\d+(,\s*B\d+)*" + REASON),
        "nosec needs a rule and a reason, e.g. # nosec B608 - <reason>",
    ),
    (
        re.compile(r"#\s*pragma:\s*no cover"),
        re.compile(r"#\s*pragma:\s*no cover" + REASON),
        "pragma: no cover needs a reason, e.g. # pragma: no cover - <reason>",
    ),
]


def problems_in(source: str) -> list[tuple[int, str]]:
    """``(line, message)`` for each comment in *source* that breaks a rule."""
    found = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        for marker, well_formed, message in RULES:
            if marker.search(token.string) and not well_formed.search(token.string):
                found.append((token.start[0], message))
    return found


def check(paths: list[Path]) -> list[str]:
    """One ``path:line: message`` per problem in the Python files under *paths*."""
    files = sorted(
        file for path in paths for file in ([path] if path.is_file() else path.rglob("*.py"))
    )
    return [
        f"{file}:{line}: {message}"
        for file in files
        for line, message in problems_in(file.read_text(encoding="utf-8"))
    ]


def main(argv: list[str]) -> int:
    failures = check([Path(arg) for arg in argv] or [Path("sagaz")])
    for failure in failures:
        print(failure)
    if failures:
        print(f"\n{len(failures)} suppression comment(s) without a code or a reason.")
        return 1
    print("✓ every suppression comment names what it suppresses and why")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
