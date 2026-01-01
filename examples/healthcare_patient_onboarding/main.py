"""
Healthcare Patient Onboarding Saga Example

Demonstrates HIPAA-compliant patient registration workflow with proper
audit trails, PHI handling, and automatic data purging on rollback.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class HealthcarePatientOnboardingSaga(Saga):
    """HIPAA-compliant patient registration with audit trail and PHI protection."""

    saga_name = "healthcare-patient-onboarding"

    def __init__(
        self,
        patient_id: str,
        first_name: str,
        last_name: str,
        date_of_birth: str,
        ssn_last_4: str,
        email: str,
        phone: str,
        simulate_failure: bool = False,
    ):
        super().__init__()
        self.patient_id = patient_id
        self.first_name = first_name
        self.last_name = last_name
        self.date_of_birth = date_of_birth
        self.ssn_last_4 = ssn_last_4
        self.email = email
        self.phone = phone
        self.simulate_failure = simulate_failure

    @action("verify_identity")
    async def verify_identity(self, ctx: SagaContext) -> dict[str, Any]:
        """Verify patient identity using government ID and biometrics."""
        logger.info(f"🔍 Verifying identity for {self.first_name} {self.last_name}")
        await asyncio.sleep(0.2)

        # Simulate identity verification service (Experian, Equifax, etc.)
        verification_result = {
            "patient_id": self.patient_id,
            "verification_method": "SSN + DOB + Photo ID",
            "verification_score": 98.5,
            "verified": True,
            "audit_log_id": f"AUDIT-VERIFY-{self.patient_id}",
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(f"   ✅ Identity verified (score: {verification_result['verification_score']})")
        return verification_result

    @compensate("verify_identity")
    async def log_verification_rollback(self, ctx: SagaContext) -> None:
        """Log verification rollback for audit trail (HIPAA requirement)."""
        logger.warning(f"📋 Logging verification rollback for patient {self.patient_id}")

        audit_log_id = ctx.get("audit_log_id")
        logger.info(f"   Audit log entry: {audit_log_id} - ROLLED_BACK")

        await asyncio.sleep(0.05)

    @action("create_ehr_record", depends_on=["verify_identity"])
    async def create_ehr_record(self, ctx: SagaContext) -> dict[str, Any]:
        """Create Electronic Health Record (EHR) with encrypted PHI."""
        logger.info(f"📁 Creating EHR for patient {self.patient_id}")
        await asyncio.sleep(0.25)

        if self.simulate_failure:
            raise SagaStepError("EHR system temporarily unavailable - database connection timeout")

        # Simulate EHR creation (Epic, Cerner, Allscripts, etc.)
        ehr_record = {
            "ehr_id": f"EHR-{self.patient_id}",
            "patient_id": self.patient_id,
            "mrn": f"MRN{self.patient_id[-6:]}",  # Medical Record Number
            "created_at": datetime.now().isoformat(),
            "encrypted": True,
            "phi_fields": ["ssn", "dob", "address", "phone", "email"],
            "hipaa_compliant": True,
        }

        logger.info(f"   ✅ EHR created with MRN: {ehr_record['mrn']}")
        return ehr_record

    @compensate("create_ehr_record")
    async def purge_ehr_record(self, ctx: SagaContext) -> None:
        """Purge EHR record and all PHI (HIPAA data minimization)."""
        logger.warning(f"🗑️  PURGING EHR record for patient {self.patient_id}")

        ehr_id = ctx.get("ehr_id")
        mrn = ctx.get("mrn")

        logger.info(f"   Securely deleting EHR {ehr_id} (MRN: {mrn})")
        logger.info("   All PHI permanently removed from systems")
        logger.info("   Audit trail preserved per HIPAA retention requirements")

        await asyncio.sleep(0.2)

    @action("assign_primary_care_provider", depends_on=["create_ehr_record"])
    async def assign_primary_care_provider(self, ctx: SagaContext) -> dict[str, Any]:
        """Assign primary care provider (PCP) based on availability and location."""
        logger.info(f"👨‍⚕️ Assigning PCP for patient {self.patient_id}")
        await asyncio.sleep(0.15)

        # Simulate PCP assignment algorithm
        pcp_assignment = {
            "provider_id": "PCP-12345",
            "provider_name": "Dr. Sarah Johnson, MD",
            "specialty": "Family Medicine",
            "location": "Main Street Clinic",
            "accepting_patients": True,
            "assignment_id": f"ASSIGN-{self.patient_id}",
        }

        logger.info(f"   ✅ Assigned to {pcp_assignment['provider_name']}")
        return pcp_assignment

    @compensate("assign_primary_care_provider")
    async def unassign_provider(self, ctx: SagaContext) -> None:
        """Remove PCP assignment from patient record."""
        logger.warning(f"👨‍⚕️ Removing PCP assignment for patient {self.patient_id}")

        provider_name = ctx.get("provider_name")
        assignment_id = ctx.get("assignment_id")

        logger.info(f"   Unassigning {provider_name} (ID: {assignment_id})")

        await asyncio.sleep(0.1)

    @action("setup_patient_portal", depends_on=["assign_primary_care_provider"])
    async def setup_patient_portal(self, ctx: SagaContext) -> dict[str, Any]:
        """Create patient portal account for online access."""
        logger.info(f"🖥️  Setting up patient portal for {self.email}")
        await asyncio.sleep(0.2)

        # Simulate patient portal setup
        portal_account = {
            "portal_user_id": f"PORTAL-{self.patient_id}",
            "email": self.email,
            "username": self.email,
            "temporary_password": "TempPass123!",  # Sent via secure channel
            "mfa_enabled": True,
            "access_level": "patient",
            "features": ["view_records", "schedule_appointments", "messaging", "billing"],
        }

        logger.info(f"   ✅ Portal created for {portal_account['email']}")
        return portal_account

    @compensate("setup_patient_portal")
    async def delete_portal_account(self, ctx: SagaContext) -> None:
        """Delete patient portal account and credentials."""
        logger.warning(f"🗑️  Deleting patient portal for {self.email}")

        portal_user_id = ctx.get("portal_user_id")
        email = ctx.get("email")

        logger.info(f"   Removing portal account {portal_user_id} ({email})")
        logger.info("   All portal credentials and sessions invalidated")

        await asyncio.sleep(0.15)

    @action("schedule_initial_appointment", depends_on=["setup_patient_portal"])
    async def schedule_initial_appointment(self, ctx: SagaContext) -> dict[str, Any]:
        """Schedule initial new patient appointment."""
        logger.info(f"📅 Scheduling initial appointment for patient {self.patient_id}")
        await asyncio.sleep(0.15)

        # Simulate appointment scheduling
        appointment = {
            "appointment_id": f"APPT-{self.patient_id}-001",
            "patient_id": self.patient_id,
            "provider_id": ctx.get("provider_id", "PCP-12345"),
            "appointment_type": "New Patient Visit",
            "date": "2026-01-15",
            "time": "10:00 AM",
            "duration_minutes": 60,
            "location": "Main Street Clinic - Room 3",
        }

        logger.info(f"   ✅ Appointment scheduled for {appointment['date']} at {appointment['time']}")
        return appointment

    @compensate("schedule_initial_appointment")
    async def cancel_appointment(self, ctx: SagaContext) -> None:
        """Cancel scheduled appointment and free the time slot."""
        logger.warning(f"📅 Canceling appointment for patient {self.patient_id}")

        appointment_id = ctx.get("appointment_id")
        date = ctx.get("date")
        time = ctx.get("time")

        logger.info(f"   Canceling appointment {appointment_id} ({date} {time})")
        logger.info("   Time slot returned to availability")

        await asyncio.sleep(0.1)

    @action("send_welcome_materials", depends_on=["schedule_initial_appointment"])
    async def send_welcome_materials(self, ctx: SagaContext) -> dict[str, Any]:
        """Send welcome packet with forms and instructions (idempotent)."""
        logger.info(f"📧 Sending welcome materials to {self.email}")
        await asyncio.sleep(0.1)

        # Simulate sending welcome packet
        welcome_packet = {
            "email_sent": True,
            "recipient": self.email,
            "materials": [
                "New Patient Forms",
                "HIPAA Privacy Notice",
                "Patient Rights and Responsibilities",
                "Insurance Information Sheet",
                "Portal Login Instructions",
                f"Appointment Confirmation ({ctx.get('date')} {ctx.get('time')})",
            ],
            "delivery_status": "delivered",
        }

        logger.info(f"   ✅ Welcome packet sent with {len(welcome_packet['materials'])} documents")
        return welcome_packet


async def main():
    """Run the healthcare patient onboarding saga demo."""
    print("=" * 80)
    print("Healthcare Patient Onboarding Saga Demo - HIPAA-Compliant Registration")
    print("=" * 80)

    # Scenario 1: Successful patient onboarding
    print("\n🟢 Scenario 1: Successful Patient Registration")
    print("-" * 80)

    saga_success = HealthcarePatientOnboardingSaga(
        patient_id="PAT-2026-001",
        first_name="Alice",
        last_name="Johnson",
        date_of_birth="1985-06-15",
        ssn_last_4="1234",
        email="alice.johnson@email.com",
        phone="+1-555-0123",
        simulate_failure=False,
    )

    result_success = await saga_success.run({"patient_id": saga_success.patient_id})

    print(f"\n{'✅' if result_success.get('saga_id') else '❌'} Patient Onboarding Result:")
    print(f"   Saga ID: {result_success.get('saga_id')}")
    print(f"   Patient ID: {result_success.get('patient_id')}")
    print(f"   Patient: {saga_success.first_name} {saga_success.last_name}")
    print("   Status: Successfully onboarded with complete EHR setup")

    # Scenario 2: EHR system failure with automatic PHI purging
    print("\n\n🔴 Scenario 2: EHR System Failure with Automatic Data Purging")
    print("-" * 80)

    saga_failure = HealthcarePatientOnboardingSaga(
        patient_id="PAT-2026-002",
        first_name="Bob",
        last_name="Smith",
        date_of_birth="1978-03-22",
        ssn_last_4="5678",
        email="bob.smith@email.com",
        phone="+1-555-0456",
        simulate_failure=True,  # Simulate EHR creation failure
    )

    try:
        result_failure = await saga_failure.run({"patient_id": saga_failure.patient_id})
    except Exception:
        result_failure = {}

    print(f"\n{'❌' if not result_failure.get('saga_id') else '✅'} Rollback Result:")
    print(f"   Saga ID: {result_failure.get('saga_id', 'N/A')}")
    print(f"   Patient ID: {saga_failure.patient_id}")
    print(f"   Patient: {saga_failure.first_name} {saga_failure.last_name}")
    print("   Status: Failed - all PHI securely purged per HIPAA requirements")
    print("   Audit Trail: Preserved for compliance review")

    print("\n" + "=" * 80)
    print("Key Features Demonstrated:")
    print("  ✅ HIPAA-compliant data handling")
    print("  ✅ Complete audit trail for all operations")
    print("  ✅ Automatic PHI purging on failure")
    print("  ✅ Encrypted patient data (PHI)")
    print("  ✅ No orphaned records in systems")
    print("  ✅ Secure patient portal with MFA")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
