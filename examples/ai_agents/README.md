# AI Agents Examples

This directory contains examples demonstrating Sagaz with real AI/LLM integrations.

## Examples

### 1. `pydantic_ai_research.py`
**Research assistant saga using Pydantic AI**

Uses real `pydantic-ai` agents with structured output types for:
- Research outline planning
- Findings gathering
- Report synthesis
- Quality validation

```python
from pydantic_ai import Agent, RunContext

# Structured output with validation
outline_agent = Agent(
    'openai:gpt-4o-mini',
    deps_type=ResearchDeps,
    output_type=ResearchOutline,  # Pydantic model
    system_prompt="You are a research planning assistant..."
)

@outline_agent.tool
async def get_research_context(ctx: RunContext[ResearchDeps]) -> str:
    return f"Topic: {ctx.deps.topic}"
```

### 2. `langgraph_support_agent.py`
**Customer support agent using LangGraph StateGraph**

Uses real LangGraph for multi-node agent workflows:
- Ticket analysis node
- Response generation node
- Resolution attempt node
- Conditional routing (resolve or escalate)

```python
from langgraph.graph import StateGraph, START, END

graph = StateGraph(SupportTicketState)
graph.add_node("analyze", analyze_node)
graph.add_node("generate_response", generate_response_node)
graph.add_conditional_edges(
    "attempt_resolution",
    route_after_resolution,
    {"resolve": "resolve", "escalate": "escalate"}
)
```

### 3. `ai_content_pipeline.py`
**Content generation pipeline with parallel AI steps**

Uses Pydantic AI for:
- Content outline creation
- Article generation
- Quality checking (parallel)
- SEO optimization (parallel)
- Final review gate

## Prerequisites

```bash
# Install Pydantic AI
pip install pydantic-ai

# Install LangGraph
pip install langgraph langchain-openai

# Set API key
export OPENAI_API_KEY="sk-..."

# Or for Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Running Examples

```bash
# Research assistant
python pydantic_ai_research.py

# Customer support (LangGraph)
python langgraph_support_agent.py

# Content pipeline
python ai_content_pipeline.py
```

## Key Patterns

### Pattern 1: AI Agent as Saga Step

```python
class ResearchSaga(Saga):
    @action("analyze")
    async def analyze_with_ai(self, ctx: dict) -> dict:
        agent = Agent('openai:gpt-4o-mini', output_type=Analysis)
        result = await agent.run(ctx['prompt'])
        return {"analysis": result.output.model_dump()}
    
    @compensate("analyze")
    async def handle_ai_failure(self, ctx: dict) -> None:
        # Log failure, notify, or retry with different model
        pass
```

### Pattern 2: LangGraph Workflow in Saga

```python
class SupportSaga(Saga):
    @action("run_workflow")
    async def run_langgraph(self, ctx: dict) -> dict:
        graph = create_support_graph()  # StateGraph
        result = await graph.ainvoke(initial_state)
        return {"result": result}
```

### Pattern 3: Parallel AI Processing

```python
class ContentSaga(Saga):
    @action("quality_check", depends_on=["generate"])
    async def check_quality(self, ctx): ...
    
    @action("seo_optimize", depends_on=["generate"])  # Runs in parallel
    async def optimize_seo(self, ctx): ...
    
    @action("finalize", depends_on=["quality_check", "seo_optimize"])
    async def finalize(self, ctx): ...
```

### Pattern 4: Trigger with Idempotency

```python
@trigger(
    source="webhook",
    idempotency_key="request_id",  # Prevent duplicate processing
    max_concurrent=5  # Limit concurrent AI calls
)
def on_request(self, event):
    return {"topic": event["topic"]}
```

## Architecture Benefits

| Sagaz Feature | AI Benefit |
|---------------|------------|
| **Compensation** | Graceful handling of AI failures |
| **Idempotency** | Prevent duplicate expensive AI calls |
| **Concurrency Limits** | Control API rate limits |
| **Persistence** | Resume long AI workflows |
| **Triggers** | Event-driven AI processing |
| **Parallel Steps** | Concurrent AI processing |

## Model Support

### Pydantic AI Models
- `openai:gpt-4o`
- `openai:gpt-4o-mini`
- `anthropic:claude-3-5-sonnet-latest`
- `anthropic:claude-3-5-haiku-latest`
- `groq:llama-3.3-70b-versatile`

### LangGraph with LangChain
- `ChatOpenAI(model="gpt-4o")`
- `ChatAnthropic(model="claude-3-5-sonnet-20241022")`
- `ChatGroq(model="llama-3.3-70b-versatile")`
