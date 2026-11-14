"""Tests for demonstration discovery (sagaz.demonstrations._discovery)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sagaz import demonstrations
from sagaz.demonstrations import _discovery


def _make_domain(root: Path, name: str, demos: list[str]) -> Path:
    domain = root / name
    domain.mkdir()
    (domain / "__init__.py").write_text("")
    for demo in demos:
        demo_dir = domain / demo
        demo_dir.mkdir()
        (demo_dir / "main.py").write_text(f'"""{demo} demo."""\n')
    return domain


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """A demonstrations tree on disk that discovery is pointed at."""
    monkeypatch.setattr(_discovery, "get_demonstrations_dir", lambda: tmp_path)
    return tmp_path


class TestPublicReExports:
    def test_package_reexports_discovery_functions(self):
        for name in demonstrations.__all__:
            assert getattr(demonstrations, name) is getattr(_discovery, name)


class TestBundledDemonstrations:
    def test_demonstrations_dir_is_the_package_directory(self):
        root = _discovery.get_demonstrations_dir()
        assert root.resolve() == Path(_discovery.__file__).parent.resolve()

    def test_falls_back_to_package_directory_when_resources_unavailable(self, monkeypatch):
        def boom(_package):
            msg = "no resources"
            raise ModuleNotFoundError(msg)

        monkeypatch.setattr(_discovery.pkg_resources, "files", boom)
        assert _discovery.get_demonstrations_dir() == Path(_discovery.__file__).parent

    def test_domains_are_ordered_by_declared_order(self):
        domains = _discovery.discover_domains()
        orders = [d["order"] for d in domains]
        assert orders == sorted(orders)
        assert domains[0]["name"] == "core_patterns"
        assert all(
            {"order", "name", "label", "short_label", "description"} <= d.keys() for d in domains
        )

    def test_flat_demo_listing_is_sorted_and_points_at_main_files(self):
        demos = _discovery.discover_demos()
        assert "basic_saga" in demos
        assert list(demos) == sorted(demos)
        assert all(path.name == "main.py" and path.exists() for path in demos.values())

    def test_domain_lookup_for_demo(self):
        by_domain = _discovery.discover_demos_by_domain()
        last_domain = list(by_domain)[-1]
        last_demo = next(iter(by_domain[last_domain]))

        assert _discovery.get_domain_for_demo("basic_saga") == "core_patterns"
        assert _discovery.get_domain_for_demo(last_demo) == last_domain
        assert _discovery.get_domain_for_demo("does-not-exist") is None


class TestDiscoveryOnCustomTree:
    def test_only_domain_packages_with_demos_are_listed(self, fake_root):
        _make_domain(fake_root, "alpha", ["one", "two"])
        _make_domain(fake_root, "empty_domain", [])
        _make_domain(fake_root, "_private", ["hidden"])
        (fake_root / "not_a_package").mkdir()
        (fake_root / "stray_file.py").write_text("")
        top_level_demo = fake_root / "top_level_demo"
        top_level_demo.mkdir()
        (top_level_demo / "__init__.py").write_text("")
        (top_level_demo / "main.py").write_text("")

        by_domain = _discovery.discover_demos_by_domain()

        assert by_domain == {
            "alpha": {
                "one": fake_root / "alpha" / "one" / "main.py",
                "two": fake_root / "alpha" / "two" / "main.py",
            }
        }

    def test_domain_without_metadata_gets_generated_fallback(self, fake_root):
        _make_domain(fake_root, "my_custom_domain", ["demo"])

        assert _discovery.discover_domains() == [
            {
                "order": 999,
                "name": "my_custom_domain",
                "label": "My Custom Domain",
                "short_label": "My Custom Domain",
                "description": "",
            }
        ]

    def test_domains_without_registered_metadata_go_last_alphabetically(
        self, fake_root, monkeypatch
    ):
        for name in ("zeta", "beta", "alpha"):
            _make_domain(fake_root, name, [f"{name}_demo"])
        monkeypatch.setattr(_discovery, "discover_domains", lambda: [{"name": "zeta"}])

        assert list(_discovery.discover_demos_by_domain()) == ["zeta", "alpha", "beta"]

    def test_duplicate_demo_names_across_domains_are_rejected(self, fake_root):
        _make_domain(fake_root, "alpha", ["shared"])
        _make_domain(fake_root, "beta", ["shared"])

        with pytest.raises(ValueError, match="Duplicate demo name 'shared'"):
            _discovery.discover_demos()


class TestDemoDescription:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ('#!/usr/bin/env python\n\n"""Run the thing."""\n', "Run the thing."),
            ("'''Single quoted.'''\n", "Single quoted."),
            ('"""\nSummary on the next line.\n"""\n', "Summary on the next line."),
            ('"""\n\n"""\n', "No description"),
            ("import os\n", "No description"),
            ("\n\n", "No description"),
        ],
    )
    def test_first_docstring_line_is_extracted(self, tmp_path, source, expected):
        main = tmp_path / "main.py"
        main.write_text(source)
        assert _discovery.get_demo_description(main) == expected

    def test_unreadable_file_has_no_description(self, tmp_path):
        assert _discovery.get_demo_description(tmp_path / "missing.py") == "No description"
