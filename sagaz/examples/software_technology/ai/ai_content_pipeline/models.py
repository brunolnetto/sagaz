"""
Structured data models for the AI content pipeline example.

Pydantic output models for each AI agent plus the shared agent dependencies.
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field

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
