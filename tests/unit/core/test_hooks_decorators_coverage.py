"""
Tests for sagaz.core.hooks._decorators module.

Ensures all hook decorators are properly covered and functional.
"""

import pytest

from sagaz.core.hooks._decorators import (
    on_step_compensate,
    on_step_enter,
    on_step_exit,
    on_step_failure,
    on_step_success,
)


class TestHookDecorators:
    """Test hook decorators from sagaz.core.hooks._decorators."""

    def test_on_step_enter_decorator_returns_function(self):
        """Test that on_step_enter decorator returns the wrapped function."""

        async def my_hook(ctx, step_name):
            return "enter"

        decorated = on_step_enter(my_hook)
        assert decorated is my_hook
        assert callable(decorated)

    def test_on_step_success_decorator_returns_function(self):
        """Test that on_step_success decorator returns the wrapped function."""

        async def my_hook(ctx, step_name, result):
            return "success"

        decorated = on_step_success(my_hook)
        assert decorated is my_hook
        assert callable(decorated)

    def test_on_step_failure_decorator_returns_function(self):
        """Test that on_step_failure decorator returns the wrapped function."""

        async def my_hook(ctx, step_name, error):
            return "failure"

        decorated = on_step_failure(my_hook)
        assert decorated is my_hook
        assert callable(decorated)

    def test_on_step_compensate_decorator_returns_function(self):
        """Test that on_step_compensate decorator returns the wrapped function."""

        async def my_hook(ctx, step_name):
            return "compensate"

        decorated = on_step_compensate(my_hook)
        assert decorated is my_hook
        assert callable(decorated)

    def test_on_step_exit_decorator_returns_function(self):
        """Test that on_step_exit decorator returns the wrapped function."""

        async def my_hook(ctx, step_name):
            return "exit"

        decorated = on_step_exit(my_hook)
        assert decorated is my_hook
        assert callable(decorated)

    def test_decorators_work_with_sync_functions(self):
        """Test that decorators work with synchronous functions."""

        def sync_hook(ctx):
            return "sync"

        # All decorators should work with sync functions too
        assert on_step_enter(sync_hook) is sync_hook
        assert on_step_success(sync_hook) is sync_hook
        assert on_step_failure(sync_hook) is sync_hook
        assert on_step_compensate(sync_hook) is sync_hook
        assert on_step_exit(sync_hook) is sync_hook

    def test_decorators_preserve_function_attributes(self):
        """Test that decorators preserve function names and docstrings."""

        async def documented_hook(ctx):
            """This is a documented hook."""
            pass

        decorated = on_step_enter(documented_hook)
        assert decorated.__name__ == "documented_hook"
        assert decorated.__doc__ == "This is a documented hook."

    def test_decorators_can_be_chained(self):
        """Test that decorators can be stacked (though unusual)."""

        async def my_hook(ctx):
            pass

        # Although unusual, decorators should compose
        decorated = on_step_exit(on_step_compensate(my_hook))
        assert callable(decorated)
        assert decorated is my_hook

    def test_all_decorators_with_lambda(self):
        """Test that decorators work with lambda functions."""
        lambda_fn = lambda ctx: "lambda_result"  # noqa: E731

        assert on_step_enter(lambda_fn) is lambda_fn
        assert on_step_success(lambda_fn) is lambda_fn
        assert on_step_failure(lambda_fn) is lambda_fn
        assert on_step_compensate(lambda_fn) is lambda_fn
        assert on_step_exit(lambda_fn) is lambda_fn
