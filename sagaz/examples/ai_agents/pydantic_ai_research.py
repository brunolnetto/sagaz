"""
Pydantic AI Research Assistant Saga

Real implementation using Pydantic AI for structured LLM outputs.
Features:
- pydantic-ai Agent with structured output types
- Multi-step AI research workflow with tools
- Compensation for failed AI calls
- Webhook trigger for research requests

Prerequisites:
    pip install pydantic-ai
    export OPENAI_API_KEY="your-key"
    # OR
    export ANTHROPIC_API_KEY="your-key"

Run:
    python pydantic_ai_research.py
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from sagaz import Saga, action, compensate
from sagaz.config import SagaConfig, configure
from sagaz.storage import InMemorySagaStorage
from sagaz.triggers import fire_event, trigger

# =============================================================================
# Pydantic Models for Structured AI Outputs
# =============================================================================

class ResearchOutline(BaseModel):
    """Structured output for research planning."""
    topic: str = Field(description="The main research topic")
    key_questions: list[str] = Field(description="Key questions to answer in the research")
    research_areas: list[str] = Field(description="Main areas to investigate")
    estimated_complexity: str = Field(description="Complexity level: low, medium, or high")


class ResearchFindings(BaseModel):
    """Structured output for research findings."""
    summary: str = Field(description="Executive summary of findings (2-3 sentences)")
    key_points: list[str] = Field(description="Main findings as bullet points (3-5 items)")
    sources_needed: list[str] = Field(description="Types of additional sources to consult")
    confidence_score: float = Field(ge=0, le=1, description="Confidence in findings (0-1)")


class FinalReport(BaseModel):
    """Structured output for final research report."""
    title: str = Field(description="Report title")
    executive_summary: str = Field(description="Executive summary paragraph")
    key_findings: list[str] = Field(description="Key findings as bullet points")
    conclusions: list[str] = Field(description="Main conclusions")
    recommendations: list[str] = Field(description="Actionable recommendations")


# =============================================================================
# Dependencies for Pydantic AI Agents
# =============================================================================

@dataclass
class ResearchDeps:
    """Dependencies injected into research agents."""
    topic: str
    depth: str  # "quick", "standard", "comprehensive"
    outline: dict | None = None
    findings: dict | None = None


# =============================================================================
# Pydantic AI Agents (lazy-loaded)
# =============================================================================

PYDANTIC_AI_AVAILABLE = False
_agents_initialized = False
outline_agent = None
findings_agent = None
report_agent = None

try:
    from pydantic_ai import Agent, RunContext
    PYDANTIC_AI_AVAILABLE = True
except ImportError:
    pass


def _initialize_agents():
    """Initialize agents lazily (only when actually used)."""
    global _agents_initialized, outline_agent, findings_agent, report_agent

    if _agents_initialized:
        return

    if not PYDANTIC_AI_AVAILABLE:
        msg = "pydantic-ai not installed. Install with: pip install pydantic-ai"
        raise RuntimeError(msg)

    # Outline Planning Agent
    outline_agent = Agent(
        "openai:gpt-4o-mini",
        deps_type=ResearchDeps,
        output_type=ResearchOutline,
        system_prompt="""
        You are a research planning assistant. Given a topic, create a structured
        research outline. Be specific and actionable. Consider the requested depth
        level when determining complexity.
        """
    )

    @outline_agent.tool
    async def get_research_context(ctx: RunContext[ResearchDeps]) -> str:
        """Get context about the research request."""
        return f"Topic: {ctx.deps.topic}, Depth: {ctx.deps.depth}"

    # Findings Agent
    findings_agent = Agent(
        "openai:gpt-4o-mini",
        deps_type=ResearchDeps,
        output_type=ResearchFindings,
        system_prompt="""
        You are a research analyst. Based on the provided outline and topic,
        synthesize key findings. Be factual and provide confidence scores
        based on the reliability of the information.
        """
    )

    @findings_agent.tool
    async def get_outline_context(ctx: RunContext[ResearchDeps]) -> str:
        """Get the research outline for context."""
        if ctx.deps.outline:
            return f"Outline: {ctx.deps.outline}"
        return "No outline available"

    # Report Agent
    report_agent = Agent(
        "openai:gpt-4o-mini",
        deps_type=ResearchDeps,
        output_type=FinalReport,
        system_prompt="""
        You are a report writer. Create a comprehensive research report based on
        the outline and findings provided. Be professional and actionable.
        """
    )

    _agents_initialized = True


# =============================================================================
# Research Saga
# =============================================================================

class AIResearchSaga(Saga):
    """
    AI-powered research assistant saga using Pydantic AI.

    Workflow:
    1. Plan research outline (pydantic-ai agent)
    2. Gather findings (pydantic-ai agent)
    3. Synthesize report (pydantic-ai agent)
    4. Quality validation
    """

    saga_name = "ai_research"

    # ==========================================================================
    # TRIGGER: Research Request
    # ==========================================================================

    @trigger(
        source="research_request",
        idempotency_key="request_id",
        max_concurrent=3
    )
    def on_research_request(self, event: dict) -> dict:
        """Handle incoming research requests."""
        if not event.get("topic"):
            return None

        return {
            "request_id": event.get("request_id", f"req-{datetime.now().timestamp()}"),
            "topic": event["topic"],
            "depth": event.get("depth", "standard"),
            "requester": event.get("requester", "anonymous"),
            "started_at": datetime.now().isoformat()
        }

    # ==========================================================================
    # STEP 1: Plan Research Outline
    # ==========================================================================

    @action("plan_outline")
    async def plan_research_outline(self, ctx: dict) -> dict:
        """Use Pydantic AI agent to create research outline."""

        _initialize_agents()  # Lazy init

        deps = ResearchDeps(topic=ctx["topic"], depth=ctx["depth"])

        result = await outline_agent.run(
            f"Create a research outline for: {ctx['topic']}. Depth level: {ctx['depth']}",
            deps=deps
        )

        outline = result.output


        return {
            "outline": outline.model_dump(),
            "outline_created": True
        }

    @compensate("plan_outline")
    async def cancel_outline(self, ctx: dict) -> None:
        """Log cancelled outline."""

    # ==========================================================================
    # STEP 2: Gather Findings
    # ==========================================================================

    @action("gather_findings", depends_on=["plan_outline"])
    async def gather_research_findings(self, ctx: dict) -> dict:
        """Use Pydantic AI agent to gather research findings."""

        _initialize_agents()  # Lazy init

        deps = ResearchDeps(
            topic=ctx["topic"],
            depth=ctx["depth"],
            outline=ctx["outline"]
        )

        prompt = f"""
        Research topic: {ctx['topic']}

        Based on this outline:
        - Key questions: {ctx['outline']['key_questions']}
        - Research areas: {ctx['outline']['research_areas']}

        Provide comprehensive research findings.
        """

        result = await findings_agent.run(prompt, deps=deps)
        findings = result.output


        return {
            "findings": findings.model_dump(),
            "findings_gathered": True
        }

    @compensate("gather_findings")
    async def discard_findings(self, ctx: dict) -> None:
        """Discard findings on failure."""

    # ==========================================================================
    # STEP 3: Synthesize Report
    # ==========================================================================

    @action("synthesize_report", depends_on=["gather_findings"])
    async def synthesize_final_report(self, ctx: dict) -> dict:
        """Use Pydantic AI agent to synthesize final report."""

        _initialize_agents()  # Lazy init

        deps = ResearchDeps(
            topic=ctx["topic"],
            depth=ctx["depth"],
            outline=ctx["outline"],
            findings=ctx["findings"]
        )

        prompt = f"""
        Create a research report for: {ctx['topic']}

        Outline: {ctx['outline']}
        Findings: {ctx['findings']}

        Provide a comprehensive, actionable report.
        """

        result = await report_agent.run(prompt, deps=deps)
        report = result.output


        return {
            "report": report.model_dump(),
            "report_ready": True
        }

    # ==========================================================================
    # STEP 4: Quality Validation
    # ==========================================================================

    @action("quality_check", depends_on=["synthesize_report"])
    async def validate_quality(self, ctx: dict) -> dict:
        """Validate report quality."""

        report = ctx["report"]
        findings = ctx["findings"]

        checks = {
            "has_summary": bool(report.get("executive_summary")),
            "has_conclusions": len(report.get("conclusions", [])) > 0,
            "has_recommendations": len(report.get("recommendations", [])) > 0,
            "confidence_threshold": findings["confidence_score"] >= 0.6,
            "sufficient_findings": len(findings.get("key_points", [])) >= 2
        }

        passed = sum(checks.values())
        total = len(checks)


        return {
            "quality_checks": checks,
            "quality_passed": passed == total,
            "completed_at": datetime.now().isoformat()
        }


# =============================================================================
# Demo Runner
# =============================================================================

async def run_demo():
    """Run the AI research demo."""

    # Check requirements
    if not PYDANTIC_AI_AVAILABLE:
        return

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return

    # Configure Sagaz
    config = SagaConfig(storage=InMemorySagaStorage())
    configure(config)


    # Fire research request
    request = {
        "request_id": "demo-001",
        "topic": "Best practices for implementing saga patterns in microservices",
        "depth": "comprehensive",
        "requester": "demo_user"
    }


    saga_ids = await fire_event("research_request", request)

    if saga_ids:
        pass

    # Wait for completion
    await asyncio.sleep(15)  # AI calls take time



if __name__ == "__main__":
    asyncio.run(run_demo())
