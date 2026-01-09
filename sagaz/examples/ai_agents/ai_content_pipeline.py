"""
AI Content Generation Pipeline Saga

Real implementation using Pydantic AI for content generation.
Features:
- Multi-step content generation with structured outputs
- Parallel AI processing (SEO + Quality checks)
- Quality gates with validation
- Trigger-based activation

Prerequisites:
    pip install pydantic-ai
    export OPENAI_API_KEY="your-key"

Run:
    python ai_content_pipeline.py
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
# Pydantic Models for Content Pipeline
# =============================================================================


class ContentOutline(BaseModel):
    """Outline for content generation."""

    title: str = Field(description="Proposed article title")
    sections: list[str] = Field(description="Main section headings")
    key_points: list[str] = Field(description="Key points to cover")
    estimated_word_count: int = Field(description="Estimated final word count")


class GeneratedContent(BaseModel):
    """Generated content output."""

    title: str = Field(description="Final article title")
    introduction: str = Field(description="Article introduction paragraph")
    body: str = Field(description="Main article body")
    conclusion: str = Field(description="Article conclusion")
    meta_description: str = Field(description="SEO meta description (150 chars)")


class QualityReport(BaseModel):
    """Content quality assessment."""

    readability_score: float = Field(ge=0, le=10, description="Readability score 0-10")
    structure_score: float = Field(ge=0, le=10, description="Structure quality 0-10")
    engagement_score: float = Field(ge=0, le=10, description="Engagement potential 0-10")
    overall_score: float = Field(ge=0, le=10, description="Overall quality 0-10")
    improvements: list[str] = Field(description="Suggested improvements")


class SEOOptimization(BaseModel):
    """SEO optimization suggestions."""

    optimized_title: str = Field(description="SEO-optimized title")
    primary_keyword: str = Field(description="Primary target keyword")
    secondary_keywords: list[str] = Field(description="Secondary keywords")
    optimized_meta: str = Field(description="SEO-optimized meta description")
    recommendations: list[str] = Field(description="SEO recommendations")


# =============================================================================
# Dependencies
# =============================================================================


@dataclass
class ContentDeps:
    """Dependencies for content agents."""

    topic: str
    audience: str
    tone: str
    keywords: list[str]
    outline: dict | None = None
    content: dict | None = None


# =============================================================================
# Pydantic AI Agents (lazy-loaded)
# =============================================================================

PYDANTIC_AI_AVAILABLE = False
_agents_initialized = False
outline_agent = None
content_agent = None
quality_agent = None
seo_agent = None

try:
    from pydantic_ai import Agent, RunContext

    PYDANTIC_AI_AVAILABLE = True
except ImportError:
    pass


def _initialize_agents():
    """Initialize agents lazily (only when actually used)."""
    global _agents_initialized, outline_agent, content_agent, quality_agent, seo_agent

    if _agents_initialized:
        return

    if not PYDANTIC_AI_AVAILABLE:
        msg = "pydantic-ai not installed. Install with: pip install pydantic-ai"
        raise RuntimeError(msg)

    # Outline Agent
    outline_agent = Agent(
        "openai:gpt-4o-mini",
        deps_type=ContentDeps,
        output_type=ContentOutline,
        system_prompt="""
        You are a content strategist. Create detailed outlines for articles.
        Consider the target audience and ensure logical flow of sections.
        """,
    )

    # Content Generation Agent
    content_agent = Agent(
        "openai:gpt-4o-mini",
        deps_type=ContentDeps,
        output_type=GeneratedContent,
        system_prompt="""
        You are an expert content writer. Write engaging, well-structured articles
        based on the provided outline. Match the requested tone and audience.
        """,
    )

    # Quality Check Agent
    quality_agent = Agent(
        "openai:gpt-4o-mini",
        deps_type=ContentDeps,
        output_type=QualityReport,
        system_prompt="""
        You are a content quality analyst. Evaluate articles for readability,
        structure, and engagement. Provide constructive improvement suggestions.
        """,
    )

    # SEO Agent
    seo_agent = Agent(
        "openai:gpt-4o-mini",
        deps_type=ContentDeps,
        output_type=SEOOptimization,
        system_prompt="""
        You are an SEO expert. Optimize content for search engines while
        maintaining readability. Focus on provided target keywords.
        """,
    )

    _agents_initialized = True


# =============================================================================
# Content Pipeline Saga
# =============================================================================


class ContentPipelineSaga(Saga):
    """
    AI-powered content generation pipeline.

    Workflow:
    1. Create outline from brief
    2. Generate content from outline
    3. Quality check (parallel)
    4. SEO optimization (parallel)
    5. Final review
    """

    saga_name = "content_pipeline"

    # ==========================================================================
    # TRIGGER: Content Request
    # ==========================================================================

    @trigger(source="content_request", idempotency_key="request_id", max_concurrent=5)
    def on_content_request(self, event: dict) -> dict:
        """Handle content generation requests."""
        if not event.get("topic"):
            return None  # type: ignore[return-value]

        return {
            "request_id": event.get("request_id", f"content-{datetime.now().timestamp()}"),
            "topic": event["topic"],
            "audience": event.get("audience", "general"),
            "tone": event.get("tone", "professional"),
            "keywords": event.get("keywords", []),
            "requester": event.get("requester", "system"),
            "started_at": datetime.now().isoformat(),
        }

    # ==========================================================================
    # STEP 1: Create Outline
    # ==========================================================================

    @action("create_outline")
    async def create_content_outline(self, ctx: dict) -> dict:
        """Generate content outline using AI."""

        _initialize_agents()  # Lazy init

        deps = ContentDeps(
            topic=ctx["topic"], audience=ctx["audience"], tone=ctx["tone"], keywords=ctx["keywords"]
        )

        result = await outline_agent.run(  # type: ignore[union-attr]
            f"Create an article outline for: {ctx['topic']}. "
            f"Target audience: {ctx['audience']}. Tone: {ctx['tone']}.",
            deps=deps,
        )

        outline = result.output

        return {"outline": outline.model_dump()}

    @compensate("create_outline")
    async def cancel_outline(self, ctx: dict) -> None:
        pass

    # ==========================================================================
    # STEP 2: Generate Content
    # ==========================================================================

    @action("generate_content", depends_on=["create_outline"])
    async def generate_initial_content(self, ctx: dict) -> dict:
        """Generate article content from outline."""

        _initialize_agents()  # Lazy init

        deps = ContentDeps(
            topic=ctx["topic"],
            audience=ctx["audience"],
            tone=ctx["tone"],
            keywords=ctx["keywords"],
            outline=ctx["outline"],
        )

        prompt = f"""
        Write an article based on this outline:
        Title: {ctx["outline"]["title"]}
        Sections: {ctx["outline"]["sections"]}
        Key points: {ctx["outline"]["key_points"]}

        Tone: {ctx["tone"]}
        Audience: {ctx["audience"]}
        """

        result = await content_agent.run(prompt, deps=deps)  # type: ignore[union-attr]
        content = result.output

        return {"content": content.model_dump()}

    @compensate("generate_content")
    async def discard_content(self, ctx: dict) -> None:
        pass

    # ==========================================================================
    # STEP 3a: Quality Check (parallel)
    # ==========================================================================

    @action("quality_check", depends_on=["generate_content"])
    async def check_content_quality(self, ctx: dict) -> dict:
        """Assess content quality using AI."""

        _initialize_agents()  # Lazy init

        deps = ContentDeps(
            topic=ctx["topic"],
            audience=ctx["audience"],
            tone=ctx["tone"],
            keywords=ctx["keywords"],
            content=ctx["content"],
        )

        prompt = f"""
        Evaluate this article:
        Title: {ctx["content"]["title"]}
        Content: {ctx["content"]["body"][:2000]}...

        Assess readability, structure, and engagement.
        """

        result = await quality_agent.run(prompt, deps=deps)  # type: ignore[union-attr]
        quality = result.output

        return {"quality": quality.model_dump(), "meets_threshold": quality.overall_score >= 7.0}

    # ==========================================================================
    # STEP 3b: SEO Optimization (parallel)
    # ==========================================================================

    @action("seo_optimize", depends_on=["generate_content"])
    async def optimize_for_seo(self, ctx: dict) -> dict:
        """Optimize content for SEO."""

        _initialize_agents()  # Lazy init

        deps = ContentDeps(
            topic=ctx["topic"],
            audience=ctx["audience"],
            tone=ctx["tone"],
            keywords=ctx["keywords"],
            content=ctx["content"],
        )

        prompt = f"""
        Optimize this article for SEO:
        Title: {ctx["content"]["title"]}
        Meta: {ctx["content"]["meta_description"]}
        Target keywords: {ctx["keywords"]}

        Provide optimized title, meta, and recommendations.
        """

        result = await seo_agent.run(prompt, deps=deps)  # type: ignore[union-attr]
        seo = result.output

        return {"seo": seo.model_dump()}

    # ==========================================================================
    # STEP 4: Final Review
    # ==========================================================================

    @action("final_review", depends_on=["quality_check", "seo_optimize"])
    async def final_review(self, ctx: dict) -> dict:
        """Final review and compilation."""

        quality = ctx["quality"]
        seo = ctx["seo"]
        content = ctx["content"]

        # Determine status
        status = "needs_revision" if not ctx["meets_threshold"] else "ready"

        final_content = {
            "title": seo["optimized_title"],
            "meta_description": seo["optimized_meta"],
            "content": content,
            "quality_score": quality["overall_score"],
            "seo_keywords": [seo["primary_keyword"]] + seo["secondary_keywords"],
            "status": status,
        }

        return {
            "final_content": final_content,
            "status": status,
            "completed_at": datetime.now().isoformat(),
        }


# =============================================================================
# Demo Runner
# =============================================================================


async def run_demo():
    """Run the content pipeline demo."""

    # Check requirements
    if not PYDANTIC_AI_AVAILABLE:
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return

    # Configure Sagaz
    config = SagaConfig(storage=InMemorySagaStorage())
    configure(config)

    # Content request
    request = {
        "request_id": "content-001",
        "topic": "How to Build Resilient Microservices with Saga Patterns",
        "audience": "software developers",
        "tone": "technical but accessible",
        "keywords": ["saga pattern", "microservices", "distributed transactions", "compensation"],
    }

    saga_ids = await fire_event("content_request", request)

    if saga_ids:
        pass

    # Wait for completion
    await asyncio.sleep(30)  # AI calls take time


if __name__ == "__main__":
    asyncio.run(run_demo())
