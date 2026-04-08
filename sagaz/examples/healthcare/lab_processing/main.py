"""
Lab Test Processing Saga Example

Demonstrates consumable resource as a pivot point. Once a biological sample
is processed (centrifuged, aliquoted), it is consumed and cannot be restored.
If the test fails, a new sample must be collected from the patient.

Pivot Step: process_sample
    Biological sample is consumed during processing.
    Cannot restore original sample.
    If test fails, need new draw from patient.

Forward Recovery:
    - Analysis failure: Request new sample, flag for re-draw
    - Reporting failure: Retry, manual result entry
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate, forward_recovery
from sagaz.core.exceptions import SagaStepError
from sagaz.execution.pivot import RecoveryAction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Simulation Helpers
# =============================================================================


class LIMSSimulator:
    """Laboratory Information Management System (LIMS) simulator."""

    @staticmethod
    async def receive_sample(
        sample_id: str,
        patient_id: str,
        sample_type: str,
    ) -> dict:
        """Log sample receipt in LIMS."""
        await asyncio.sleep(0.05)
        return {
            "accession_number": f"ACC-{sample_id}",
            "received_at": datetime.now().isoformat(),
            "sample_type": sample_type,
            "condition": "acceptable",
        }

    @staticmethod
    async def verify_requisition(
        accession_number: str,
        ordering_provider: str,
    ) -> dict:
        """Verify test requisition and insurance authorization."""
        await asyncio.sleep(0.1)
        return {
            "verified": True,
            "tests_ordered": ["CBC", "CMP", "LIPID"],
            "priority": "routine",
            "insurance_auth": "AUTH-12345",
        }

    @staticmethod
    async def queue_for_testing(
        accession_number: str,
        tests: list[str],
    ) -> dict:
        """Add sample to testing queue."""
        await asyncio.sleep(0.05)
        return {
            "queue_position": 12,
            "estimated_completion": "2 hours",
            "assigned_analyzer": "CHEM-01",
        }

    @staticmethod
    async def process_sample(
        accession_number: str,
        sample_type: str,
    ) -> dict:
        """Process the sample (centrifuge, aliquot) - CONSUMES THE SAMPLE."""
        await asyncio.sleep(0.3)

        # Simulate occasional issues
        import random

        if random.random() < 0.05:  # 5% failure rate
            msg = "Sample hemolyzed during centrifugation"
            raise SagaStepError(msg)

        return {
            "processing_id": f"PROC-{accession_number}",
            "aliquots_created": 3,
            "serum_volume_ml": 2.5,
            "sample_consumed": True,
            "processed_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def run_analysis(
        processing_id: str,
        tests: list[str],
    ) -> dict:
        """Run laboratory analysis on processed sample."""
        await asyncio.sleep(0.4)

        # Simulate test results
        results = {
            "CBC": {
                "WBC": 7.5,
                "RBC": 4.8,
                "HGB": 14.2,
                "HCT": 42.1,
                "PLT": 250,
            },
            "CMP": {
                "GLUCOSE": 95,
                "BUN": 15,
                "CREATININE": 1.0,
                "SODIUM": 140,
                "POTASSIUM": 4.2,
            },
            "LIPID": {
                "CHOLESTEROL": 185,
                "TRIGLYCERIDES": 120,
                "HDL": 55,
                "LDL": 110,
            },
        }

        return {
            "analysis_id": f"ANAL-{processing_id}",
            "results": {t: results.get(t, {}) for t in tests},
            "analyzer": "CHEM-01",
            "completed_at": datetime.now().isoformat(),
        }

    @staticmethod
    async def validate_results(
        analysis_id: str,
        results: dict,
    ) -> dict:
        """Validate results against reference ranges and previous values."""
        await asyncio.sleep(0.1)

        # Check if any values are critical
        critical_flags = []
        if results.get("CMP", {}).get("POTASSIUM", 4.0) > 6.0:
            critical_flags.append("CRITICAL_POTASSIUM")

        return {
            "validation_id": f"VAL-{analysis_id}",
            "validated": True,
            "validated_by": "PATHOLOGIST-01",
            "critical_flags": critical_flags,
            "delta_check_passed": True,
        }

    @staticmethod
    async def report_to_provider(
        validation_id: str,
        provider_id: str,
    ) -> dict:
        """Send results to ordering provider."""
        await asyncio.sleep(0.1)
        return {
            "report_id": f"RPT-{validation_id}",
            "sent_to": provider_id,
            "sent_at": datetime.now().isoformat(),
            "delivery_method": "HL7",
        }


# =============================================================================
# Saga Definition
# =============================================================================


class LabTestProcessingSaga(Saga):
    """
    Lab test processing saga with consumable resource pivot.

    This saga demonstrates the irreversibility of consuming biological samples.
    Once a sample is processed (centrifuged, aliquoted), it cannot be restored.
    If subsequent tests fail, a new sample must be collected from the patient.

    Expected context:
        - sample_id: str - Unique sample identifier
        - patient_id: str - Patient identifier
        - sample_type: str - Type of sample (blood, urine, etc.)
        - ordering_provider: str - Provider who ordered tests
        - tests_ordered: list[str] - Tests to perform
    """

    saga_name = "lab-test-processing"

    # === REVERSIBLE ZONE ===

    @action("receive_sample")
    async def receive_sample(self, ctx: SagaContext) -> dict[str, Any]:
        """Log sample receipt in LIMS."""
        sample_id = ctx.get("sample_id")
        patient_id = ctx.get("patient_id")
        sample_type = ctx.get("sample_type", "blood")

        logger.info(f"🧪 [{sample_id}] Receiving {sample_type} sample from {patient_id}...")

        result = await LIMSSimulator.receive_sample(sample_id, patient_id, sample_type)

        logger.info(
            f"✅ [{sample_id}] Sample received: {result['accession_number']}, "
            f"condition: {result['condition']}"
        )

        return {
            "accession_number": result["accession_number"],
            "sample_condition": result["condition"],
            "received_at": result["received_at"],
        }

    @compensate("receive_sample")
    async def reject_sample(self, ctx: SagaContext) -> None:
        """Log sample rejection."""
        sample_id = ctx.get("sample_id")
        accession_number = ctx.get("accession_number")

        logger.warning(f"↩️ [{sample_id}] Rejecting sample {accession_number}...")
        await asyncio.sleep(0.05)

    @action("verify_requisition", depends_on=["receive_sample"])
    async def verify_requisition(self, ctx: SagaContext) -> dict[str, Any]:
        """Verify test requisition and insurance authorization."""
        sample_id = ctx.get("sample_id")
        accession_number = ctx.get("accession_number")
        ordering_provider = ctx.get("ordering_provider", "DR-001")

        logger.info(f"📋 [{sample_id}] Verifying requisition from {ordering_provider}...")

        result = await LIMSSimulator.verify_requisition(accession_number, ordering_provider)

        if not result["verified"]:
            msg = "Requisition verification failed"
            raise SagaStepError(msg)

        logger.info(
            f"✅ [{sample_id}] Requisition verified, tests: {', '.join(result['tests_ordered'])}"
        )

        return {
            "tests_ordered": result["tests_ordered"],
            "insurance_auth": result["insurance_auth"],
            "priority": result["priority"],
        }

    @compensate("verify_requisition")
    async def cancel_requisition(self, ctx: SagaContext) -> None:
        """Cancel requisition verification."""
        sample_id = ctx.get("sample_id")
        logger.warning(f"↩️ [{sample_id}] Cancelling requisition...")
        await asyncio.sleep(0.05)

    @action("queue_for_testing", depends_on=["verify_requisition"])
    async def queue_for_testing(self, ctx: SagaContext) -> dict[str, Any]:
        """Add sample to testing queue."""
        sample_id = ctx.get("sample_id")
        accession_number = ctx.get("accession_number")
        tests_ordered = ctx.get("tests_ordered", [])

        logger.info(f"📥 [{sample_id}] Queueing for {len(tests_ordered)} tests...")

        result = await LIMSSimulator.queue_for_testing(accession_number, tests_ordered)

        logger.info(
            f"✅ [{sample_id}] Queued at position {result['queue_position']}, "
            f"ETA: {result['estimated_completion']}"
        )

        return {
            "queue_position": result["queue_position"],
            "assigned_analyzer": result["assigned_analyzer"],
        }

    @compensate("queue_for_testing")
    async def remove_from_queue(self, ctx: SagaContext) -> None:
        """Remove sample from testing queue."""
        sample_id = ctx.get("sample_id")
        logger.warning(f"↩️ [{sample_id}] Removing from queue...")
        await asyncio.sleep(0.05)

    # === PIVOT STEP ===

    @action("process_sample", depends_on=["queue_for_testing"], pivot=True)
    async def process_sample(self, ctx: SagaContext) -> dict[str, Any]:
        """
        🔒 PIVOT STEP: Process the sample (centrifuge, aliquot).

        Once this step completes, the sample has been CONSUMED.
        The original sample cannot be restored. If subsequent
        tests fail, a new sample must be collected from the patient.
        """
        sample_id = ctx.get("sample_id")
        accession_number = ctx.get("accession_number")
        sample_type = ctx.get("sample_type", "blood")

        logger.info(f"🔒 [{sample_id}] PIVOT: Processing sample...")
        logger.info("   ⚠️ Sample will be consumed (centrifuged, aliquoted)")

        result = await LIMSSimulator.process_sample(accession_number, sample_type)

        logger.info(
            f"✅ [{sample_id}] Sample processed! "
            f"{result['aliquots_created']} aliquots, "
            f"{result['serum_volume_ml']}mL serum"
        )

        return {
            "processing_id": result["processing_id"],
            "aliquots_created": result["aliquots_created"],
            "serum_volume_ml": result["serum_volume_ml"],
            "sample_consumed": result["sample_consumed"],
            "pivot_reached": True,  # Point of no return
        }

    # Note: No compensation for process_sample - it's a pivot step!
    # The biological sample has been consumed. Cannot restore.

    # === COMMITTED ZONE (Forward Recovery Only) ===

    @action("run_analysis", depends_on=["process_sample"])
    async def run_analysis(self, ctx: SagaContext) -> dict[str, Any]:
        """Run laboratory analysis on processed sample."""
        sample_id = ctx.get("sample_id")
        processing_id = ctx.get("processing_id")
        tests_ordered = ctx.get("tests_ordered", [])

        logger.info(f"🔬 [{sample_id}] Running {len(tests_ordered)} tests...")

        result = await LIMSSimulator.run_analysis(processing_id, tests_ordered)

        logger.info(f"✅ [{sample_id}] Analysis complete: {result['analysis_id']}")

        return {
            "analysis_id": result["analysis_id"],
            "results": result["results"],
            "analyzer": result["analyzer"],
        }

    @forward_recovery("run_analysis")
    async def handle_analysis_failure(self, ctx: SagaContext, error: Exception) -> RecoveryAction:
        """
        Forward recovery for analysis failures.

        Strategies:
        1. RETRY - Use remaining aliquot if available
        2. MANUAL_INTERVENTION - Schedule patient recollection
        """
        aliquots_remaining = ctx.get("aliquots_created", 0) - 1

        if aliquots_remaining > 0:
            ctx.set("aliquots_created", aliquots_remaining)
            logger.info(f"🧪 Using backup aliquot ({aliquots_remaining} remaining)")
            return RecoveryAction.RETRY

        # No more aliquots - need new sample
        logger.warning("❌ No remaining aliquots. Scheduling patient recollection.")
        return RecoveryAction.MANUAL_INTERVENTION

    @action("validate_results", depends_on=["run_analysis"])
    async def validate_results(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate results against reference ranges."""
        sample_id = ctx.get("sample_id")
        analysis_id = ctx.get("analysis_id")
        results = ctx.get("results", {})

        logger.info(f"✔️ [{sample_id}] Validating results...")

        result = await LIMSSimulator.validate_results(analysis_id, results)

        if result["critical_flags"]:
            logger.warning(f"⚠️ [{sample_id}] CRITICAL VALUES: {result['critical_flags']}")
        else:
            logger.info(f"✅ [{sample_id}] Results validated by {result['validated_by']}")

        return {
            "validation_id": result["validation_id"],
            "validated": result["validated"],
            "critical_flags": result["critical_flags"],
        }

    @action("report_to_provider", depends_on=["validate_results"])
    async def report_to_provider(self, ctx: SagaContext) -> dict[str, Any]:
        """Send results to ordering provider."""
        sample_id = ctx.get("sample_id")
        validation_id = ctx.get("validation_id")
        ordering_provider = ctx.get("ordering_provider", "DR-001")

        logger.info(f"📤 [{sample_id}] Reporting to {ordering_provider}...")

        result = await LIMSSimulator.report_to_provider(validation_id, ordering_provider)

        logger.info(
            f"✅ [{sample_id}] Results reported: {result['report_id']}, "
            f"via {result['delivery_method']}"
        )

        return {
            "report_id": result["report_id"],
            "report_sent_at": result["sent_at"],
            "delivery_method": result["delivery_method"],
        }


# =============================================================================
# Demo Scenarios
# =============================================================================


async def main():
    """Run the lab test processing saga demo."""

    saga = LabTestProcessingSaga()

    # Scenario 1: Successful lab processing

    result = await saga.run(
        {
            "sample_id": "SAMP-2026-001",
            "patient_id": "PAT-12345",
            "sample_type": "blood",
            "ordering_provider": "DR-SMITH",
            "tests_ordered": ["CBC", "CMP", "LIPID"],
        }
    )

    # Display some results
    results = result.get("results", {})
    if results:
        for _test, values in results.items():
            for _key, _value in list(values.items())[:3]:
                pass

    # Scenario 2: Pre-pivot failure

    # Scenario 3: Post-pivot scenarios


if __name__ == "__main__":
    asyncio.run(main())
