# LangGraph Customer Support Agent

Multi-node LLM agent workflow for intelligent customer support using LangGraph StateGraph.

## Description

This example demonstrates using LangGraph's StateGraph abstraction within a Sagaz saga to build a sophisticated multi-node LLM agent workflow for customer support.

## Features

- **LangGraph StateGraph**: Typed state management and conditional routing
- **Multi-node workflow**: Analyze → Generate Response → Attempt Resolution → Route
- **Conditional routing**: AI-driven decision logic (can resolve vs. escalate)
- **Human-in-the-loop**: Automatic escalation to human agents
- **Compensation**: Proper cleanup if LLM fails mid-workflow

## Prerequisites

```bash
pip install langgraph langchain-openai langchain-anthropic
export OPENAI_API_KEY="your-key"
```

## Running the Example

```bash
python -m sagaz.examples.ai.technology.llm.langgraph_support_agent.main
```

## Workflow

```
support_ticket
    ↓
[analyze_node] → Categorize, prioritize, analyze sentiment
    ↓
[generate_response_node] → AI response generation
    ↓
[attempt_resolution_node] → Decision: can resolve?
    ↓
    ├─ YES → [resolve_node] → Close ticket
    │
    └─ NO → [escalate_node] → Assign to human agent
```

## Key Patterns

1. **StateGraph Nodes**: Each node is an async function that reads/writes state
2. **Conditional Edges**: `route_after_resolution` function decides next path
3. **Type Safety**: `SupportTicketState` TypedDict ensures consistent state shape
4. **Append-only Messages**: Using `Annotated[list[dict], add]` for audit trail

## Integration Points

- **Message Service**: Send AI response to customer
- **Ticketing System**: Store resolution or escalation
- **Agent Assignment**: Route to appropriate human agent
- **Analytics**: Track resolution rates and escalation patterns
