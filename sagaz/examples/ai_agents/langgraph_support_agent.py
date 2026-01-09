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
from operator import add
from typing import Annotated, Literal, TypedDict

from sagaz import Saga, action, compensate
from sagaz.config import SagaConfig, configure
from sagaz.storage import InMemorySagaStorage
from sagaz.triggers import fire_event, trigger

# =============================================================================
# LangGraph State Definition
# =============================================================================

class SupportTicketState(TypedDict):
    """State for the support ticket workflow."""
    ticket_id: str
    customer_id: str
    issue: str
    # Analysis results
    category: str
    priority: str
    sentiment: str
    # Resolution
    ai_response: str
    resolution_attempted: bool
    resolution_success: bool
    # Escalation
    escalated: bool
    human_agent_id: str
    # Message history (append-only)
    messages: Annotated[list[dict], add]


# =============================================================================
# LangGraph Setup
# =============================================================================

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True

except ImportError:
    LANGGRAPH_AVAILABLE = False


def create_support_graph():
    """
    Create the LangGraph support agent workflow.

    Flow:
    START -> analyze -> generate_response -> attempt_resolution -> route
              |
              v
        [can_resolve?]
              |
        yes   |   no
          v       v
        resolve  escalate
              |     |
              v     v
              END  END
    """
    if not LANGGRAPH_AVAILABLE:
        msg = "langgraph not installed"
        raise RuntimeError(msg)

    # Initialize LLM
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # Define nodes
    async def analyze_node(state: SupportTicketState) -> dict:
        """Analyze the support ticket."""
        messages = [
            SystemMessage(content="""
                You are a support ticket analyzer. Analyze the customer issue and respond with:
                - Category: billing, technical, account, shipping, or other
                - Priority: low, medium, high, or critical
                - Sentiment: positive, neutral, frustrated, or angry

                Format: category|priority|sentiment
            """),
            HumanMessage(content=f"Customer issue: {state['issue']}")
        ]

        response = await llm.ainvoke(messages)
        parts = response.content.strip().split("|")

        return {
            "category": parts[0] if len(parts) > 0 else "other",
            "priority": parts[1] if len(parts) > 1 else "medium",
            "sentiment": parts[2] if len(parts) > 2 else "neutral",
            "messages": [{"role": "system", "content": "Ticket analyzed"}]
        }

    async def generate_response_node(state: SupportTicketState) -> dict:
        """Generate an AI response to the customer."""
        messages = [
            SystemMessage(content=f"""
                You are a helpful support agent. The customer has a {state['category']} issue.
                Their sentiment is {state['sentiment']}. Priority: {state['priority']}.

                Provide a helpful, empathetic response. Be professional and solution-oriented.
            """),
            HumanMessage(content=f"Customer: {state['issue']}")
        ]

        response = await llm.ainvoke(messages)

        return {
            "ai_response": response.content,
            "messages": [{"role": "agent", "content": response.content[:100] + "..."}]
        }

    async def attempt_resolution_node(state: SupportTicketState) -> dict:
        """Attempt to resolve the issue automatically."""
        messages = [
            SystemMessage(content="""
                You are evaluating if this support issue can be resolved automatically.
                Consider:
                - Is this a common issue with a known solution?
                - Does it require account access or manual intervention?
                - Is the customer too frustrated for automated handling?

                Respond with just: YES or NO
            """),
            HumanMessage(content=f"""
                Category: {state['category']}
                Priority: {state['priority']}
                Sentiment: {state['sentiment']}
                Issue: {state['issue']}
            """)
        ]

        response = await llm.ainvoke(messages)
        can_resolve = "YES" in response.content.upper()

        return {
            "resolution_attempted": True,
            "resolution_success": can_resolve,
            "messages": [{"role": "system", "content": f"Resolution: {'success' if can_resolve else 'escalate'}"}]
        }

    async def resolve_node(state: SupportTicketState) -> dict:
        """Successfully resolve the ticket."""
        return {
            "escalated": False,
            "messages": [{"role": "system", "content": "Ticket resolved automatically"}]
        }

    async def escalate_node(state: SupportTicketState) -> dict:
        """Escalate to human agent."""
        # In production, this would integrate with your ticketing system
        agent_id = f"agent-{hash(state['ticket_id']) % 100:03d}"

        return {
            "escalated": True,
            "human_agent_id": agent_id,
            "messages": [{"role": "system", "content": f"Escalated to {agent_id}"}]
        }

    def route_after_resolution(state: SupportTicketState) -> Literal["resolve", "escalate"]:
        """Route based on resolution success."""
        if state.get("resolution_success"):
            return "resolve"
        return "escalate"

    # Build the graph
    graph = StateGraph(SupportTicketState)

    # Add nodes
    graph.add_node("analyze", analyze_node)
    graph.add_node("generate_response", generate_response_node)
    graph.add_node("attempt_resolution", attempt_resolution_node)
    graph.add_node("resolve", resolve_node)
    graph.add_node("escalate", escalate_node)

    # Add edges
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "generate_response")
    graph.add_edge("generate_response", "attempt_resolution")
    graph.add_conditional_edges(
        "attempt_resolution",
        route_after_resolution,
        {"resolve": "resolve", "escalate": "escalate"}
    )
    graph.add_edge("resolve", END)
    graph.add_edge("escalate", END)

    return graph.compile()


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

    @trigger(
        source="support_ticket",
        idempotency_key="ticket_id",
        max_concurrent=20
    )
    def on_ticket_received(self, event: dict) -> dict:
        """Process incoming support tickets."""
        if not event.get("issue"):
            return None

        return {
            "ticket_id": event.get("ticket_id", f"TKT-{datetime.now().timestamp()}"),
            "customer_id": event.get("customer_id", "unknown"),
            "issue": event["issue"],
            "channel": event.get("channel", "web"),
            "received_at": datetime.now().isoformat()
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
            "messages": []
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
                "resolution_success": final_state["resolution_success"]
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
                "ai_handled": not result["escalated"]
            }
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
            "channel": "web"
        },
        {
            "ticket_id": "TKT-002",
            "customer_id": "CUST-456",
            "issue": "Your service is terrible! I was charged twice for my order and nobody is helping me!",
            "channel": "email"
        }
    ]

    for ticket in tickets:

        saga_ids = await fire_event("support_ticket", ticket)

        if saga_ids:
            pass

        # Wait between tickets
        await asyncio.sleep(10)



if __name__ == "__main__":
    asyncio.run(run_demo())
