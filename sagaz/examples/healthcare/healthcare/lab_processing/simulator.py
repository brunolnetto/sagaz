"""
Simulated laboratory information management system (LIMS) for the lab processing example.
"""

import asyncio
from datetime import datetime

from sagaz.core.exceptions import SagaStepError


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
