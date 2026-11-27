"""A decorated method is a step whatever it is named, and an empty saga does not run (#656)."""

from __future__ import annotations

from typing import Any

import pytest

from sagaz import (
    RecoveryAction,
    Saga,
    SagaConfig,
    SagaFailedError,
    action,
    compensate,
    forward_recovery,
)
from sagaz.core.exceptions import SagaDefinitionError
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage


def quiet(**settings: Any) -> SagaConfig:
    return SagaConfig(metrics=False, logging=False, **settings)


class TestPrivateMethods:
    async def test_steps_and_compensations_named_with_an_underscore_run(self):
        log: list[str] = []

        class Transfer(Saga):
            saga_name = "transfer"

            @action("validate")
            async def _validate(self, ctx: dict[str, Any]) -> None:
                log.append("validate")

            @compensate("validate")
            async def _cancel(self, ctx: dict[str, Any]) -> None:
                log.append("cancel")

            @action("execute", depends_on=["validate"], max_retries=0)
            async def _execute(self, ctx: dict[str, Any]) -> None:
                msg = "bank offline"
                raise RuntimeError(msg)

        with pytest.raises(SagaFailedError):
            await Transfer(config=quiet()).run({})
        assert log == ["validate", "cancel"]

    async def test_a_name_mangled_method_is_a_step_too(self):
        log: list[str] = []

        class Transfer(Saga):
            saga_name = "transfer"

            @action("validate")
            async def __validate(self, ctx: dict[str, Any]) -> None:
                log.append("validate")

        await Transfer(config=quiet()).run({})
        assert log == ["validate"]

    async def test_a_private_forward_recovery_handler_is_asked(self):
        asked: list[str] = []

        class Order(Saga):
            saga_name = "order"

            @action("charge", pivot=True)
            async def _charge(self, ctx: dict[str, Any]) -> None: ...

            @action("ship", depends_on=["charge"], max_retries=0)
            async def _ship(self, ctx: dict[str, Any]) -> None:
                msg = "no carrier"
                raise RuntimeError(msg)

            @forward_recovery("ship")
            async def _recover(self, ctx: dict[str, Any], error: Exception) -> RecoveryAction:
                asked.append(str(error))
                return RecoveryAction.MANUAL_INTERVENTION

        with pytest.raises(SagaFailedError):
            await Order(config=quiet()).run({})
        assert asked == ["no carrier"]

    def test_creating_the_saga_evaluates_no_property(self):
        class Order(Saga):
            saga_name = "order"

            @property
            def total(self) -> int:
                msg = "a property is not a step: it must not be read"
                raise AssertionError(msg)

            @action("charge")
            async def charge(self, ctx: dict[str, Any]) -> None: ...

        assert [step.step_id for step in Order(config=quiet())._steps] == ["charge"]

    def test_public_and_private_steps_keep_one_name_each(self):
        class Order(Saga):
            @action("charge")
            async def charge(self, ctx: dict[str, Any]) -> None: ...

            @action("charge")
            async def _charge(self, ctx: dict[str, Any]) -> None: ...

        with pytest.raises(SagaDefinitionError, match="two steps are named 'charge'"):
            Order(config=quiet())


class TestASagaWithNoSteps:
    async def test_it_does_not_run_nor_is_it_stored(self):
        storage = InMemorySagaStorage()

        class Empty(Saga):
            saga_name = "empty"

        with pytest.raises(SagaDefinitionError, match="'empty' has no steps"):
            await Empty(config=quiet(storage=storage)).run({}, saga_id="e-1")
        assert await storage.load_saga_state("e-1") is None

    async def test_an_imperative_saga_runs_once_it_has_a_step(self):
        saga = Saga(name="late", config=quiet())
        with pytest.raises(SagaDefinitionError, match="has no steps"):
            await saga.run({})

        async def step(ctx: dict[str, Any]) -> dict[str, Any]:
            return {"done": True}

        saga.add_step("only", step)
        assert (await saga.run({}))["done"] is True
