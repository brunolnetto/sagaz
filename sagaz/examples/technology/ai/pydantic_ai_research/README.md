# Pydantic AI Research Assistant

Structured research synthesis using Pydantic AI with type-safe LLM outputs and validation gates.

## Description

This example demonstrates using Pydantic AI's structured output feature within a Sagaz saga to build a reliable research assistant that synthesizes information into structured reports.

## Features

- **Pydantic AI Agents**: Type-safe LLM interactions with structured outputs
- **Multi-step workflow**: Plan → Gather → Synthesize → Validate
- **Structured outputs**: `ResearchOutline`, `ResearchFindings`, `FinalReport` models
- **Tool integration**: Agent-specific tools for context retrieval
- **Quality gates**: Validation against confidence thresholds
- **Lazy initialization**: Agents only loaded when needed

## Prerequisites

```bash
pip install pydantic-ai
export OPENAI_API_KEY="your-key"
# OR
export ANTHROPIC_API_KEY="your-key"
```

## Running the Example

```bash
python -m sagaz.examples.technology.ai.pydantic_ai_research.main
```

## Workflow

```
research_request (topic, depth, requester)
    ↓
[plan_outline] → Pydantic AI Agent
    ↓ ResearchOutline (key_questions, research_areas, complexity)
    ↓
[gather_findings] → Pydantic AI Agent with outline context
    ↓ ResearchFindings (key_points, confidence_score)
    ↓
[synthesize_report] → Pydantic AI Agent with outline + findings
    ↓ FinalReport (summary, conclusions, recommendations)
    ↓
[quality_check] → Validate confidence, completeness
    ↓
Output: research_report_id
```

## Key Patterns

1. **Structured Models**: BaseModel classes define expected LLM outputs
2. **Agent Tools**: Injected into agents for context retrieval
3. **Dependencies**: `ResearchDeps` passed to agents for context
4. **Validation Gates**: Quality check ensures findings meet confidence threshold
5. **Compensation**: Failed stages properly clean up

## Pydantic AI vs ChatGPT API

| Aspect | Pydantic AI | Raw ChatGPT |
|--------|-----------|-----------|
| **Output Type** | Structured Pydantic models | Raw strings |
| **Validation** | Automatic via models | Manual parsing |
| **Tools** | Async function decorators | JSON schema definitions |
| **Type Safety** | Full static typing | No type guarantees |
| **Error Handling** | Structured exceptions | String matching |

## Integration Points

- **Research Database**: Store findings for future reference
- **Citation System**: Track sources for each finding
- **Report Distribution**: Email/publish final reports
- **Analytics**: Track research depth usage and quality metrics
