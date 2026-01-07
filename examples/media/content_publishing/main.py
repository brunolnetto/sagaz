"""
Content Publishing Pipeline Saga Example

Demonstrates content publishing as pivot point. Once content is
published, it's cached globally in CDN and indexed by search engines.

Pivot Step: publish_content
    Content is public, indexed by search.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any
import uuid

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ContentPublishingSaga(Saga):
    """Content publishing pipeline saga with publication pivot."""
    
    saga_name = "content-publishing"
    
    @action("submit_draft")
    async def submit_draft(self, ctx: SagaContext) -> dict[str, Any]:
        article_id = ctx.get("article_id")
        logger.info(f"📝 [{article_id}] Submitting draft...")
        await asyncio.sleep(0.1)
        return {"draft_submitted": True, "word_count": 2500}
    
    @compensate("submit_draft")
    async def archive_draft(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('article_id')}] Archiving draft...")
        await asyncio.sleep(0.05)
    
    @action("editorial_review", depends_on=["submit_draft"])
    async def editorial_review(self, ctx: SagaContext) -> dict[str, Any]:
        article_id = ctx.get("article_id")
        logger.info(f"✏️ [{article_id}] Editorial review...")
        await asyncio.sleep(0.2)
        return {"editorial_approved": True, "editor": "Jane Doe"}
    
    @compensate("editorial_review")
    async def return_to_draft(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('article_id')}] Returning to draft...")
        await asyncio.sleep(0.05)
    
    @action("legal_review", depends_on=["editorial_review"])
    async def legal_review(self, ctx: SagaContext) -> dict[str, Any]:
        article_id = ctx.get("article_id")
        logger.info(f"⚖️ [{article_id}] Legal review...")
        await asyncio.sleep(0.15)
        return {"legal_approved": True, "no_issues": True}
    
    @compensate("legal_review")
    async def void_legal_approval(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('article_id')}] Voiding legal approval...")
        await asyncio.sleep(0.05)
    
    @action("publish_content", depends_on=["legal_review"])
    async def publish_content(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Publish content - now public."""
        article_id = ctx.get("article_id")
        logger.info(f"🔒 [{article_id}] PIVOT: Publishing content...")
        await asyncio.sleep(0.3)
        return {
            "published": True,
            "publish_url": f"https://example.com/articles/{article_id}",
            "published_at": datetime.now().isoformat(),
            "indexed": True,
            "pivot_reached": True,
        }
    
    @action("distribute_cdn", depends_on=["publish_content"])
    async def distribute_cdn(self, ctx: SagaContext) -> dict[str, Any]:
        article_id = ctx.get("article_id")
        logger.info(f"🌐 [{article_id}] Distributing to CDN...")
        await asyncio.sleep(0.2)
        return {"cdn_distributed": True, "edge_locations": 150}
    
    @action("notify_social", depends_on=["distribute_cdn"])
    async def notify_social(self, ctx: SagaContext) -> dict[str, Any]:
        article_id = ctx.get("article_id")
        logger.info(f"📱 [{article_id}] Posting to social media...")
        await asyncio.sleep(0.1)
        return {"social_posted": True, "platforms": ["twitter", "linkedin", "facebook"]}


async def main():
    print("=" * 80)
    print("📰 Content Publishing Pipeline Saga Demo")
    print("=" * 80)
    
    saga = ContentPublishingSaga()
    result = await saga.run({
        "article_id": "ART-2026-001",
        "title": "Breaking News: Sagaz Goes Production",
        "author": "Tech Writer",
    })
    
    print(f"\n✅ Publishing Result:")
    print(f"   URL: {result.get('publish_url', 'N/A')}")
    print(f"   CDN Edges: {result.get('edge_locations', 0)}")
    print(f"   Social Platforms: {result.get('platforms', [])}")
    print(f"   Pivot Reached: {result.get('pivot_reached', False)}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
