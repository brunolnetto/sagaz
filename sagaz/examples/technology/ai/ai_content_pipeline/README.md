# AI Content Generation Pipeline

Multi-step content creation pipeline with parallel quality and SEO processing.

## Description

This example demonstrates a production-ready content generation system using Pydantic AI agents in parallel stages with automatic quality gates.

## Features

- **Multi-stage workflow**: Outline → Generate → Quality Check (parallel) + SEO (parallel) → Review
- **Pydantic AI agents**: Specialized agents for each content task
- **Parallel processing**: Quality and SEO validation running concurrently
- **Quality gates**: Content must pass readability, structure, and engagement thresholds
- **SEO optimization**: Automatic keyword optimization and meta descriptions
- **Trigger-based**: Activation via content request events

## Prerequisites

```bash
pip install pydantic-ai
export OPENAI_API_KEY="your-key"
```

## Running the Example

```bash
python -m sagaz.examples.ai.digital_media.content_generation.ai_content_pipeline.main
```

## Workflow

```
content_request (topic, audience, tone, keywords)
    ↓
[create_outline] → Strategy Agent
    ↓ ContentOutline (title, sections, key_points)
    ↓
[generate_content] → Writer Agent
    ↓ GeneratedContent (full article)
    ├─→ [quality_check] → Quality Agent    ┐
    │                                       ├→ [final_review]
    └─→ [seo_optimization] → SEO Agent      ┘
    ↓ SEOOptimization (keywords, meta)
    ↓
Output: content_article_id
```

## Agent Types

1. **Outline Agent**: Creates article structure
2. **Content Agent**: Writes the full article
3. **Quality Agent**: Assesses readability, structure, engagement
4. **SEO Agent**: Optimizes for search engines

## Key Patterns

1. **Parallel Validation**: Quality and SEO checks run independently
2. **Structured Outputs**: Each agent has typed output model
3. **Content Dependencies**: Each stage passes output to next via context
4. **Agent Specialization**: Each agent has specific system prompt
5. **Quality Gates**: Validation against scoring thresholds

## Integration Points

- **Content Management System**: Store published articles
- **Publishing Platform**: Queue content for scheduling
- **Analytics**: Track engagement metrics per article
- **Keyword Research**: Pull trending keywords for optimization
- **Email Distribution**: Send articles to subscribers

## Quality Metrics

- **Readability Score**: 0-10 (Flesch-Kincaid)
- **Structure Score**: 0-10 (outline adherence)
- **Engagement Score**: 0-10 (persuasiveness, call-to-action)
- **SEO Keywords**: Density and placement optimization

## Performance

- Typical article generation: 30-60 seconds
- Parallel processing saves ~40% vs sequential
- Quality gate prevents low-quality content from publishing
