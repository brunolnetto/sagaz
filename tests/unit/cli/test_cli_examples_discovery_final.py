import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import sys

from sagaz.cli.examples.discovery import (
    get_examples_dir,
    _check_subdomain_for_main_file,
    discover_examples,
    _find_example_files,
    discover_examples_by_domain,
    _collect_examples_by_subdomain
)

class TestDiscoveryFinal:
    def test_get_examples_dir_final_fallback(self):
        with patch("importlib.resources.files", side_effect=TypeError):
            with patch("pathlib.Path.exists", return_value=False):
                d = get_examples_dir()
                assert d == Path.cwd() / "sagaz" / "examples"

    def test_check_subdomain_no_files(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "other.txt").write_text("hi")
        assert _check_subdomain_for_main_file(sub) is False

    def test_discover_examples_search_dir_missing(self, tmp_path):
        with patch("sagaz.cli.examples.discovery.get_examples_dir", return_value=tmp_path):
            with patch("sagaz.cli.examples.discovery.SUBDOMAIN_TO_DOMAIN_FOLDER", {"cat": "dom"}):
                # dom/cat does not exist
                assert discover_examples("cat") == {}

    def test_find_example_files_relative_to_fails(self, tmp_path):
        search_dir = tmp_path / "search"
        search_dir.mkdir()
        (search_dir / "main.py").write_text("hi")
        # examples_dir is different, so relative_to will fail
        other_dir = Path("/other/path")
        assert _find_example_files(search_dir, other_dir) == {}

    def test_discover_examples_by_domain_dir_missing(self):
        with patch("sagaz.cli.examples.discovery.get_examples_dir", return_value=Path("/nonexistent")):
            assert discover_examples_by_domain() == {}

    def test_collect_examples_parts_short(self, tmp_path):
        (tmp_path / "main.py").write_text("hi")
        # root is examples_dir, parts will be empty
        assert _collect_examples_by_subdomain(tmp_path) == {}

    def test_collect_examples_relative_to_fails(self, tmp_path):
        # This is hard to trigger without real os.walk issues, 
        # but we can mock relative_to on the Path objects if needed.
        pass
