"""sagaz.Saga is the public class; the imperative engine speaks its vocabulary (#537)."""

from __future__ import annotations

import pytest

import sagaz
from sagaz.core.decorators import Saga as DeclarativeSaga
from sagaz.core.saga import Saga as ImperativeSaga
from sagaz.core.types import SagaStatus


async def ok(ctx):
    return {"ok": True}


def test_sagaz_saga_is_the_declarative_class():
    assert sagaz.Saga is DeclarativeSaga


async def test_the_imperative_add_step_takes_sagaz_saga_names():
    saga = ImperativeSaga("legacy")
    await saga.add_step("a", ok, depends_on=[], timeout_seconds=5, compensation_timeout_seconds=7)
    await saga.add_step("b", ok, depends_on=["a"])
    assert [(s.name, s.timeout, s.compensation_timeout) for s in saga.steps] == [
        ("a", 5, 7),
        ("b", 30.0, 30.0),
    ]
    assert (await saga.execute()).status == SagaStatus.COMPLETED


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dependencies": {"a"}, "depends_on": ["a"]},
        {"timeout": 5, "timeout_seconds": 5},
        {"compensation_timeout": 5, "compensation_timeout_seconds": 5},
    ],
)
async def test_both_spellings_of_a_parameter_are_refused(kwargs):
    saga = ImperativeSaga("legacy")
    await saga.add_step("a", ok)
    with pytest.raises(TypeError, match="got both"):
        await saga.add_step("b", ok, **kwargs)


async def test_the_imperative_run_points_to_sagaz_saga():
    with pytest.raises(TypeError, match=r"sagaz\.Saga \(from sagaz import Saga\)"):
        await ImperativeSaga("legacy").run({})
