"""
Regulatory Filing Saga Example

Demonstrates regulatory submission as pivot point. Once a filing
is submitted to SEC/FDA/EPA, it becomes public record.

Pivot Step: submit_to_authority
    Filing received by regulatory body, now public record.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class RegulatoryFilingSaga(Saga):
    """Regulatory filing saga with submission pivot."""

    saga_name = "regulatory-filing"

    @action("prepare_filing")
    async def prepare_filing(self, ctx: SagaContext) -> dict[str, Any]:
        filing_id = ctx.get("filing_id")
        logger.info(f"📝 [{filing_id}] Preparing filing documents...")
        await asyncio.sleep(0.1)
        return {"documents_prepared": True, "page_count": 150}

    @compensate("prepare_filing")
    async def archive_draft(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('filing_id')}] Archiving draft...")
        await asyncio.sleep(0.05)

    @action("validate_format", depends_on=["prepare_filing"])
    async def validate_format(self, ctx: SagaContext) -> dict[str, Any]:
        filing_id = ctx.get("filing_id")
        logger.info(f"✔️ [{filing_id}] Validating format...")
        await asyncio.sleep(0.1)
        return {"format_valid": True, "xbrl_valid": True}

    @compensate("validate_format")
    async def release_validation(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('filing_id')}] Releasing validation...")
        await asyncio.sleep(0.05)

    @action("sign_filing", depends_on=["validate_format"])
    async def sign_filing(self, ctx: SagaContext) -> dict[str, Any]:
        filing_id = ctx.get("filing_id")
        logger.info(f"✍️ [{filing_id}] Getting executive signatures...")
        await asyncio.sleep(0.2)
        return {"signed": True, "signers": ["CEO", "CFO", "Controller"]}

    @compensate("sign_filing")
    async def void_signatures(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('filing_id')}] Voiding signatures...")
        await asyncio.sleep(0.05)

    @action("submit_to_authority", depends_on=["sign_filing"])
    async def submit_to_authority(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Submit to regulatory authority - public record."""
        filing_id = ctx.get("filing_id")
        authority = ctx.get("authority", "SEC")
        logger.info(f"🔒 [{filing_id}] PIVOT: Submitting to {authority}...")
        await asyncio.sleep(0.4)
        return {
            "submission_id": f"{authority}-{uuid.uuid4().hex[:8].upper()}",
            "accepted": True,
            "timestamp": datetime.now().isoformat(),
            "public_record": True,
            "pivot_reached": True,
        }

    @action("receive_acknowledgment", depends_on=["submit_to_authority"])
    async def receive_acknowledgment(self, ctx: SagaContext) -> dict[str, Any]:
        filing_id = ctx.get("filing_id")
        logger.info(f"📬 [{filing_id}] Receiving acknowledgment...")
        await asyncio.sleep(0.1)
        return {"acknowledgment_received": True, "accession_number": f"0001-26-{filing_id}"}

    @action("archive_record", depends_on=["receive_acknowledgment"])
    async def archive_record(self, ctx: SagaContext) -> dict[str, Any]:
        filing_id = ctx.get("filing_id")
        logger.info(f"🗄️ [{filing_id}] Archiving for compliance...")
        await asyncio.sleep(0.1)
        return {"archived": True, "retention_years": 7}


async def main():

    saga = RegulatoryFilingSaga()
    await saga.run({
        "filing_id": "10K-2026-Q4",
        "company": "Acme Corp",
        "authority": "SEC",
        "filing_type": "10-K",
    })



if __name__ == "__main__":
    asyncio.run(main())
