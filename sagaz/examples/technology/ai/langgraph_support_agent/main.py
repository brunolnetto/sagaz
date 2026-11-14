"""
LangGraph Customer Support Agent Saga

Real implementation using LangGraph StateGraph for multi-agent support.
Features:
- LangGraph StateGraph with typed state
- Multi-node agent workflow
- Conditional routing based on analysis
- Human-in-the-loop escalation pattern

Prerequisites:
    pip install langgraph langchain-openai langchain-anthropic
    export OPENAI_API_KEY="your-key"

Run:
    python langgraph_support_agent.py
"""

import asyncio
import os
from datetime import datetime

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig, configure
from sagaz.core.storage import InMemorySagaStorage
from sagaz.core.triggers import fire_event, trigger
from sagaz.examples.technology.ai.langgraph_support_agent.graph import (
    LANGGRAPH_AVAILABLE,
    SupportTicketState,
    create_support_graph,
)

# =============================================================================
# Support Saga with LangGraph Integration
# =============================================================================


class CustomerSupportSaga(Saga):
    """
    AI-powered customer support saga using LangGraph.

    The saga wraps a LangGraph workflow, providing:
    - Compensation if the graph fails
    - Persistence of saga state
    - Trigger-based activation
    - Concurrency control
    """

    saga_name = "customer_support"

    # ==========================================================================
    # TRIGGER: Support Ticket
    # ==========================================================================

    @trigger(source="support_ticket", idempotency_key="ticket_id", max_concurrent=20)
    def on_ticket_received(self, event: dict) -> dict:
        """Process incoming support tickets."""
        if not event.get("issue"):
            return None  # type: ignore[return-value]

        return {
            "ticket_id": event.get("ticket_id", f"TKT-{datetime.now().timestamp()}"),
            "customer_id": event.get("customer_id", "unknown"),
            "issue": event["issue"],
            "channel": event.get("channel", "web"),
            "received_at": datetime.now().isoformat(),
        }

    # ==========================================================================
    # STEP 1: Run LangGraph Workflow
    # ==========================================================================

    @action("run_support_graph")
    async def run_langgraph_workflow(self, ctx: dict) -> dict:
        """
        Execute the LangGraph support workflow.

        This step runs the entire graph as a single saga action,
        allowing for proper compensation if it fails.
        """

        if not LANGGRAPH_AVAILABLE:
            msg = "langgraph not installed"
            raise RuntimeError(msg)

        # Create the graph
        graph = create_support_graph()

        # Prepare initial state
        initial_state: SupportTicketState = {
            "ticket_id": ctx["ticket_id"],
            "customer_id": ctx["customer_id"],
            "issue": ctx["issue"],
            "category": "",
            "priority": "",
            "sentiment": "",
            "ai_response": "",
            "resolution_attempted": False,
            "resolution_success": False,
            "escalated": False,
            "human_agent_id": "",
            "messages": [],
        }

        # Run the graph
        final_state = await graph.ainvoke(initial_state)

        if final_state["escalated"]:
            pass

        return {
            "graph_result": {
                "category": final_state["category"],
                "priority": final_state["priority"],
                "sentiment": final_state["sentiment"],
                "ai_response": final_state["ai_response"],
                "escalated": final_state["escalated"],
                "human_agent_id": final_state["human_agent_id"],
                "resolution_success": final_state["resolution_success"],
            }
        }

    @compensate("run_support_graph")
    async def handle_graph_failure(self, ctx: dict) -> None:
        """Handle graph failure - always escalate to human."""

    # ==========================================================================
    # STEP 2: Finalize Ticket
    # ==========================================================================

    @action("finalize_ticket", depends_on=["run_support_graph"])
    async def finalize_ticket(self, ctx: dict) -> dict:
        """Finalize the ticket processing."""
        result = ctx["graph_result"]

        status = "resolved" if result["resolution_success"] else "escalated"

        return {
            "status": status,
            "completed_at": datetime.now().isoformat(),
            "summary": {
                "ticket_id": ctx["ticket_id"],
                "category": result["category"],
                "priority": result["priority"],
                "outcome": status,
                "ai_handled": not result["escalated"],
            },
        }


# =============================================================================
# Demo Runner
# =============================================================================


async def run_demo():
    """Run the customer support demo."""

    # Check requirements
    if not LANGGRAPH_AVAILABLE:
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return

    # Configure Sagaz
    config = SagaConfig(storage=InMemorySagaStorage())
    configure(config)

    # Sample tickets
    tickets = [
        {
            "ticket_id": "TKT-001",
            "customer_id": "CUST-123",
            "issue": "I can't login to my account. I've tried resetting my password 3 times but the email never arrives!",
            "channel": "web",
        },
        {
            "ticket_id": "TKT-002",
            "customer_id": "CUST-456",
            "issue": "Your service is terrible! I was charged twice for my order and nobody is helping me!",
            "channel": "email",
        },
    ]

    for ticket in tickets:
        saga_ids = await fire_event("support_ticket", ticket)

        if saga_ids:
            pass

        # Wait between tickets
        await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(run_demo())
