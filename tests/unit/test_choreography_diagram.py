"""A static Mermaid diagram of a choreography (#565)."""

from __future__ import annotations

import logging

import pytest

from sagaz.choreography import (
    ChoreographedSaga,
    ChoreographyEngine,
    Event,
    EventBus,
    choreography_mermaid,
    compensate,
    on_event,
)


async def reserve(event: Event, me: ChoreographedSaga) -> None:
    await me.emit("stock.reserved")


async def release(event: Event, me: ChoreographedSaga) -> None:
    pass


async def pay(event: Event, me: ChoreographedSaga) -> None:
    await me.emit("order.completed")


async def ship(event: Event, me: ChoreographedSaga) -> None:
    pass


def shop(*, ship_declares: bool = False) -> ChoreographyEngine:
    engine = ChoreographyEngine(EventBus(), completion_events={"order.completed"})
    engine.register(ChoreographedSaga(name="orders"))
    engine.register(
        ChoreographedSaga(name="inventory").on(
            "order.created", reserve, release, emits={"stock.reserved"}
        )
    )
    engine.register(
        ChoreographedSaga(name="payments").on("stock.reserved", pay, emits={"order.completed"})
    )
    shipping = ChoreographedSaga(name="shipping")
    shipping.on("order.completed", ship, emits=set() if ship_declares else None)
    engine.register(shipping)
    return engine


def node(diagram: str, text: str) -> str:
    """The id of the node labelled *text*."""
    for line in diagram.splitlines():
        if f'"{text}"' in line and ("(" in line or "[" in line) and "-->" not in line:
            return line.strip().split("(")[0].split("[")[0]
    msg = f"no node {text!r} in\n{diagram}"
    raise AssertionError(msg)


class TestTheGraph:
    def test_events_flow_through_the_participants_that_handle_and_emit_them(self):
        diagram = shop().to_mermaid()
        created, reserved, completed = (
            node(diagram, e) for e in ("order.created", "stock.reserved", "order.completed")
        )
        inventory, payments = node(diagram, "inventory"), node(diagram, "payments")
        assert f'{created} -->|"compensable"| {inventory}' in diagram
        assert f"{inventory} --> {reserved}" in diagram
        assert f"{reserved} --> {payments}" in diagram
        assert f"{payments} --> {completed}" in diagram

    def test_completion_events_are_final_nodes(self):
        diagram = shop().to_mermaid()
        assert '((("order.completed"))):::completion' in diagram

    def test_a_handler_without_emits_is_marked_undeclared(self):
        diagram = shop().to_mermaid()
        assert "shipping<br/>emits undeclared on order.completed" in diagram
        assert (
            f"class {node(diagram, 'shipping<br/>emits undeclared on order.completed')} undeclared"
            in diagram
        )
        assert '(["order.created"]):::event' in diagram  # not an entry: knowledge is incomplete

    def test_when_every_handler_declared_the_events_nobody_emits_are_entries(self):
        diagram = shop(ship_declares=True).to_mermaid()
        assert '(["order.created"]):::entry' in diagram
        assert '(["stock.reserved"]):::event' in diagram
        assert "undeclared" not in diagram.split("classDef")[0]

    def test_compensation_reaches_the_participants_that_can_undo(self):
        diagram = shop().to_mermaid()
        assert 'compensate(["choreography.compensate"]):::compensate' in diagram
        assert f'compensate -.->|"undo order.created"| {node(diagram, "inventory")}' in diagram
        assert "compensate" not in shop().to_mermaid(show_compensation=False).split("classDef")[0]

    def test_the_output_does_not_depend_on_registration_order(self):
        engine = ChoreographyEngine(EventBus(), completion_events={"order.completed"})
        participants = shop().registered_sagas
        for participant in reversed(participants):
            participant._publish = None  # registered once already
            engine.register(participant)
        assert engine.to_mermaid() == shop().to_mermaid()


class TestOptions:
    def test_direction(self):
        assert shop().to_mermaid(direction="TB").startswith("flowchart TB\n")
        with pytest.raises(ValueError, match="direction"):
            shop().to_mermaid(direction="sideways")

    def test_markdown(self):
        markdown = shop().to_mermaid_markdown()
        assert markdown.startswith("```mermaid\nflowchart LR\n")
        assert markdown.endswith("\n```")

    def test_labels_are_escaped(self):
        odd = ChoreographedSaga(name='odd "<b>" & co').on("x", ship, emits=set())
        diagram = choreography_mermaid([odd])
        assert "odd #quot;#lt;b#gt;#quot; #amp; co" in diagram
        assert "<b>" not in diagram

    def test_without_an_engine(self):
        diagram = choreography_mermaid(
            shop().registered_sagas, completion_events={"order.completed"}
        )
        assert diagram == shop().to_mermaid()


class TestDeclaringEmits:
    def test_the_decorators_declare_it_too(self):
        class Inventory(ChoreographedSaga):
            @on_event("order.created", emits={"stock.reserved"})
            async def reserve(self, event: Event) -> None:
                await self.emit("stock.reserved")

            @compensate("order.created")
            async def release(self, event: Event) -> None: ...

        inventory = Inventory(name="inventory")
        assert inventory.emits("order.created") == {"stock.reserved"}
        diagram = choreography_mermaid([inventory])
        assert '-->|"compensable"|' in diagram
        assert "undeclared" not in diagram.split("classDef")[0]

    def test_an_undeclared_handler_has_no_declaration(self):
        assert ChoreographedSaga(name="s").on("x", ship).emits("x") is None

    async def test_emitting_an_undeclared_type_logs_a_warning(self, caplog):
        async def wrong(event: Event, me: ChoreographedSaga) -> None:
            await me.emit("stock.missing")

        bus = EventBus()
        engine = ChoreographyEngine(bus)
        engine.register(
            ChoreographedSaga(name="inventory").on("order.created", wrong, emits={"stock.reserved"})
        )
        await engine.start()
        try:
            with caplog.at_level(logging.WARNING, logger="sagaz.choreography"):
                await bus.publish(Event("order.created", saga_id="t-1"))
        finally:
            await engine.stop()
        assert "inventory emits undeclared 'stock.missing' on 'order.created'" in caplog.text
        assert [e.event_type for e in bus.published] == [
            "order.created",
            "stock.missing",
        ]  # still sent

    async def test_emitting_a_declared_type_logs_nothing(self, caplog):
        bus = EventBus()
        engine = ChoreographyEngine(bus)
        engine.register(
            ChoreographedSaga(name="inventory").on(
                "order.created", reserve, emits={"stock.reserved"}
            )
        )
        await engine.start()
        try:
            with caplog.at_level(logging.WARNING, logger="sagaz.choreography"):
                await bus.publish(Event("order.created", saga_id="t-1"))
        finally:
            await engine.stop()
        assert "undeclared" not in caplog.text
