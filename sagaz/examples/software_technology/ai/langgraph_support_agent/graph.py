"""LangGraph state and workflow for the customer support agent example."""

from operator import add
from typing import Annotated, Literal, TypedDict

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
            SystemMessage(
                content="""
                You are a support ticket analyzer. Analyze the customer issue and respond with:
                - Category: billing, technical, account, shipping, or other
                - Priority: low, medium, high, or critical
                - Sentiment: positive, neutral, frustrated, or angry

                Format: category|priority|sentiment
            """
            ),
            HumanMessage(content=f"Customer issue: {state['issue']}"),
        ]

        response = await llm.ainvoke(messages)
        parts = response.content.strip().split("|")  # type: ignore[union-attr]

        return {
            "category": parts[0] if len(parts) > 0 else "other",
            "priority": parts[1] if len(parts) > 1 else "medium",
            "sentiment": parts[2] if len(parts) > 2 else "neutral",
            "messages": [{"role": "system", "content": "Ticket analyzed"}],
        }

    async def generate_response_node(state: SupportTicketState) -> dict:
        """Generate an AI response to the customer."""
        messages = [
            SystemMessage(
                content=f"""
                You are a helpful support agent. The customer has a {state["category"]} issue.
                Their sentiment is {state["sentiment"]}. Priority: {state["priority"]}.

                Provide a helpful, empathetic response. Be professional and solution-oriented.
            """
            ),
            HumanMessage(content=f"Customer: {state['issue']}"),
        ]

        response = await llm.ainvoke(messages)

        return {
            "ai_response": response.content,
            "messages": [{"role": "agent", "content": response.content[:100] + "..."}],  # type: ignore[operator]
        }

    async def attempt_resolution_node(state: SupportTicketState) -> dict:
        """Attempt to resolve the issue automatically."""
        messages = [
            SystemMessage(
                content="""
                You are evaluating if this support issue can be resolved automatically.
                Consider:
                - Is this a common issue with a known solution?
                - Does it require account access or manual intervention?
                - Is the customer too frustrated for automated handling?

                Respond with just: YES or NO
            """
            ),
            HumanMessage(
                content=f"""
                Category: {state["category"]}
                Priority: {state["priority"]}
                Sentiment: {state["sentiment"]}
                Issue: {state["issue"]}
            """
            ),
        ]

        response = await llm.ainvoke(messages)
        can_resolve = "YES" in response.content.upper()  # type: ignore[union-attr]

        return {
            "resolution_attempted": True,
            "resolution_success": can_resolve,
            "messages": [
                {
                    "role": "system",
                    "content": f"Resolution: {'success' if can_resolve else 'escalate'}",
                }
            ],
        }

    async def resolve_node(state: SupportTicketState) -> dict:
        """Successfully resolve the ticket."""
        return {
            "escalated": False,
            "messages": [{"role": "system", "content": "Ticket resolved automatically"}],
        }

    async def escalate_node(state: SupportTicketState) -> dict:
        """Escalate to human agent."""
        # In production, this would integrate with your ticketing system
        agent_id = f"agent-{hash(state['ticket_id']) % 100:03d}"

        return {
            "escalated": True,
            "human_agent_id": agent_id,
            "messages": [{"role": "system", "content": f"Escalated to {agent_id}"}],
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
        "attempt_resolution", route_after_resolution, {"resolve": "resolve", "escalate": "escalate"}
    )
    graph.add_edge("resolve", END)
    graph.add_edge("escalate", END)

    return graph.compile()
