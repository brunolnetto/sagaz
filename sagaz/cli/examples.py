"""
CLI module for discovering and running examples.
Refactored to sagaz.cli.examples sub-module (v1.6.1).
"""

from .examples import examples_cli, list_examples, run_example, select_example

__all__ = ["examples_cli", "list_examples", "run_example", "select_example"]
