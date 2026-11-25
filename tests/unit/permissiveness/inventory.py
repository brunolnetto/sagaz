"""What sagaz accepts today that it should refuse, measured (#660).

``python -m tests.unit.permissiveness.inventory --write`` rewrites
``known_accepted.json`` from the current behaviour; do that only to remove entries
that a fix made sagaz refuse.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import pkgutil
import re
import sys
import typing
from pathlib import Path

import click

import sagaz
from tests.unit.permissiveness.cases import CASES, accepted

KNOWN = Path(__file__).with_name("known_accepted.json")

#: Packages whose dataclasses are not library configuration.
_SKIPPED = ("demonstrations", "examples", "templates", "deployment", "cli", "visualization.gradio")
_NUMERIC = re.compile(
    r"(timeout|retries|retry|interval|delay|backoff|ttl|days|seconds|_ms$|size|limit|max_|min_|"
    r"threshold|rate|probability|port|count|capacity|concurrency|workers|period|lease|depth|"
    r"batch|window|attempts|quota|percent|ratio|weight|jitter|age|duration|deadline|grace)",
    re.IGNORECASE,
)
_CHOICE = re.compile(
    r"(strategy|mode|layout|level|format|backend|kind|policy|compression|envelope)$", re.IGNORECASE
)
#: Records of what happened (events, results, measurements), not settings someone writes.
_RECORDS = re.compile(
    r"(Event|Result|Record|Snapshot|Status|Summary|Report|Stats|Statistics|Info|State|Entry|"
    r"Message|Row|Sample|Measurement|Comparison|Metric|Outcome|Activity|Change|Transaction|"
    r"Write|Request|Experiment|Timing|Profile|Progress|Step$|Node$|Context$)"
)
_BAD_NUMBERS = (-1, "x", True)
_BAD_CHOICES = ("no-such-value", 42)


def accepted_cases() -> set[str]:
    """The cases of ``cases.py`` that sagaz accepts."""
    return {what for what, attempt in CASES.items() if accepted(attempt)}


def _dataclasses() -> list[type]:
    found: dict[str, type] = {}
    for info in pkgutil.walk_packages(sagaz.__path__, "sagaz."):
        if any(f".{skipped}" in info.name for skipped in _SKIPPED):
            continue
        try:
            module = importlib.import_module(info.name)
        except ImportError:  # an optional dependency that is not installed
            continue
        for value in vars(module).values():
            if isinstance(value, type) and dataclasses.is_dataclass(value):
                if value.__module__.startswith("sagaz") and not _RECORDS.search(value.__name__):
                    found[f"{value.__module__}.{value.__qualname__}"] = value
    return [found[name] for name in sorted(found)]


def _bad_values(cls: type, field: dataclasses.Field) -> tuple[object, ...]:
    try:
        annotation = str(typing.get_type_hints(cls).get(field.name, field.type))
    except Exception:  # an annotation that cannot be resolved here
        annotation = str(field.type)
    if _NUMERIC.search(field.name) and re.search(r"int|float|timedelta", annotation):
        return _BAD_NUMBERS
    if _CHOICE.search(field.name) and "str" in annotation and "Enum" not in annotation:
        return _BAD_CHOICES
    return ()


def _builds(cls: type, **values: object) -> bool:
    try:
        cls(**values)
    except Exception:
        return False
    return True


def probed_classes() -> set[str]:
    """The configuration classes this environment can import and build with no argument."""
    return {cls.__name__ for cls in _dataclasses() if _builds(cls)}


def accepted_fields() -> set[str]:
    """``Class.field=value`` for every configuration field that takes an invalid value."""
    found = set()
    for cls in _dataclasses():
        if not _builds(cls):
            continue  # it needs arguments: not probed
        for field in dataclasses.fields(cls):
            if not field.init or field.name.startswith("_"):
                continue
            for value in _bad_values(cls, field):
                if _builds(cls, **{field.name: value}):
                    found.add(f"{cls.__name__}.{field.name}={value!r}")
    return found


def _commands(command: click.Command, path: str = "") -> typing.Iterator[tuple[str, click.Command]]:
    name = f"{path} {command.name}".strip()
    if isinstance(command, click.Group):
        for sub in command.commands.values():
            yield from _commands(sub, name)
    else:
        yield name, command


def unbounded_cli_options() -> set[str]:
    """Numeric CLI options that take any number, negative ones and zero included."""
    from sagaz.cli.app import cli

    bounded = (click.IntRange, click.FloatRange)
    plain = (click.types.IntParamType, click.types.FloatParamType)
    return {
        f"{name} {'/'.join(option.opts)}"
        for name, command in _commands(cli)
        for option in command.params
        if isinstance(option.type, plain) and not isinstance(option.type, bounded)
    }


def measure() -> dict[str, list[str]]:
    return {
        "cases": sorted(accepted_cases()),
        "configuration_fields": sorted(accepted_fields()),
        "cli_options": sorted(unbounded_cli_options()),
    }


if __name__ == "__main__":
    measured = measure()
    if "--write" in sys.argv:
        KNOWN.write_text(json.dumps(measured, indent=2) + "\n")
    for kind, entries in measured.items():
        sys.stdout.write(f"{kind}: {len(entries)}\n")
