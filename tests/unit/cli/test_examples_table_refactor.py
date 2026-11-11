from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from sagaz.cli import examples


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("example", ("", "example")),
        ("subdomain/example", ("subdomain", "example")),
        ("domain/subdomain/example", ("subdomain", "example")),
        (
            "domain/subdomain/example/extra",
            ("subdomain", "example"),
        ),
    ],
)
def test_example_display_parts_preserves_identifier_semantics(
    identifier: str,
    expected: tuple[str, str],
) -> None:
    assert examples._example_display_parts(identifier) == expected


def test_add_examples_table_rows_sorts_and_groups_domains(monkeypatch) -> None:
    table = MagicMock()
    descriptions = {
        Path("/examples/a.py"): "Description A",
        Path("/examples/b.py"): "Description B",
        Path("/examples/c.py"): "Description C",
    }
    monkeypatch.setattr(
        examples,
        "get_example_description",
        lambda path: descriptions[path],
    )

    by_domain = {
        "Business": {
            "commerce/zebra": Path("/examples/c.py"),
            "commerce/alpha": Path("/examples/a.py"),
        },
        "Technology": {
            "data/pipeline/run": Path("/examples/b.py"),
        },
    }

    examples._add_examples_table_rows(table, by_domain)

    assert table.add_row.call_args_list == [
        call("Business", "commerce", "alpha", "Description A"),
        call("", "commerce", "zebra", "Description C"),
        call("Technology", "pipeline", "run", "Description B"),
    ]


def test_display_examples_table_falls_back_without_rich(monkeypatch) -> None:
    plain_display = MagicMock()
    monkeypatch.setattr(examples, "TableClass", None)
    monkeypatch.setattr(examples, "_display_examples_plain", plain_display)

    by_domain = {"Business": {}}
    examples._display_examples_table(by_domain)

    plain_display.assert_called_once_with(by_domain)


def test_display_examples_table_renders_columns_and_rows(monkeypatch) -> None:
    table = MagicMock()
    table_factory = MagicMock(return_value=table)
    console = MagicMock()
    monkeypatch.setattr(examples, "TableClass", table_factory)
    monkeypatch.setattr(examples, "console", console)
    monkeypatch.setattr(
        examples,
        "discover_examples_by_domain",
        lambda: {"Business": {}},
    )

    examples._display_examples_table({"Business": {"commerce/order": Path("/examples/order.py")}})

    table_factory.assert_called_once_with(
        title="Sagaz Examples",
        show_header=True,
        header_style="bold magenta",
        expand=False,
    )
    assert table.add_column.call_count == 4
    table.add_row.assert_called_once_with(
        "Business",
        "commerce",
        "order",
        examples.get_example_description(Path("/examples/order.py")),
    )
    console.print.assert_has_calls(
        [
            call(table),
            call(
                "[dim]Run an example: sagaz examples run <domain_folder>/<subdomain>/<name>[/dim]"
            ),
        ]
    )
