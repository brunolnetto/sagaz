"""The classic ``sagaz.core.saga.Saga`` is deprecated in favour of ``sagaz.Saga`` (#544)."""

from __future__ import annotations

import subprocess
import sys
import warnings

import pytest

from sagaz.core.saga import Saga as ClassicSaga


def test_creating_a_classic_saga_warns_and_names_the_replacement():
    with pytest.warns(DeprecationWarning, match=r"removed in 3\.0: use sagaz\.Saga") as caught:
        ClassicSaga("order")
    assert caught[0].filename == __file__  # it points at the code that created the saga


def test_a_subclass_warns_too():
    class Order(ClassicSaga):
        def __init__(self) -> None:
            super().__init__(name="order")

    with pytest.warns(DeprecationWarning, match="sagaz.core.saga.Saga is deprecated"):
        Order()


async def test_a_classic_saga_still_runs():
    async def step(ctx):
        return {"done": True}

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        saga = ClassicSaga("order")
    await saga.add_step("a", step)
    result = await saga.execute()
    assert result.success


def test_sagaz_saga_does_not_warn():
    from sagaz import Saga

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        Saga()


def test_importing_sagaz_and_its_demonstrations_does_not_warn():
    """Nothing the library ships creates a classic saga at import time."""
    code = (
        "import warnings; warnings.simplefilter('error', DeprecationWarning)\n"
        "import sagaz, sagaz.core.saga, sagaz.core.execution.orchestrator\n"
        "import sagaz.core.replay.saga_replay\n"
        "import sagaz.demonstrations.core_patterns.parallel_steps.main\n"
        "import sagaz.demonstrations.reliability_recovery.saga_replay.main\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
