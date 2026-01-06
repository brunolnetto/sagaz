# Healthcare Patient Onboarding Saga

HIPAA-compliant patient registration workflow with proper audit trails, PHI handling, and automatic data purging on failure.

## Overview

This example demonstrates a complete healthcare patient onboarding process that maintains HIPAA compliance, creates proper audit trails, and ensures PHI (Protected Health Information) is properly managed and purged if registration fails.

## Use Case

When onboarding a new patient to a healthcare system:
1. Identity must be verified before any records are created
2. All PHI must be encrypted and properly secured
3. Every action must be logged for audit trail
4. If onboarding fails, all PHI must be securely purged
5. No orphaned records should exist across systems

## Workflow

```
Patient Registration Started
    ↓
[1] Verify Patient Identity → (Compensation: Log verification rollback)
    ↓
[2] Create EHR Record → (Compensation: PURGE all PHI permanently)
    ↓
[3] Assign Primary Care Provider → (Compensation: Remove assignment)
    ↓
[4] Setup Patient Portal Access → (Compensation: Delete portal account)
    ↓
[5] Schedule Initial Appointment → (Compensation: Cancel appointment)
    ↓
[6] Send Welcome Materials (idempotent)
    ↓
Registration Complete
```

## Key Features

### HIPAA Compliance
- **PHI Encryption**: All patient data encrypted at rest and in transit
- **Audit Trail**: Every action logged with timestamps and user IDs
- **Data Minimization**: Only necessary PHI collected and stored
- **Right to be Forgotten**: Complete PHI purging on rollback
- **Access Controls**: Role-based access with MFA for portal

### Automatic Compensation
- **Complete PHI Purging**: All patient data removed from all systems
- **No Orphaned Records**: EHR, portal, appointments all cleaned up
- **Audit Preservation**: Audit logs retained per HIPAA requirements (even after rollback)
- **Provider Capacity**: Unassigned provider slots returned to availability

### Security Features
- Identity verification with high confidence scores
- Multi-factor authentication for patient portal
- Encrypted data storage
- Secure credential management
- Session invalidation on rollback

## Files

- **main.py** - Complete saga implementation with demo scenarios

## Usage

```python
from examples.healthcare_patient_onboarding.main import HealthcarePatientOnboardingSaga

# Create patient onboarding saga
saga = HealthcarePatientOnboardingSaga(
    patient_id="PAT-2026-001",
    first_name="Alice",
    last_name="Johnson",
    date_of_birth="1985-06-15",
    ssn_last_4="1234",
    email="alice.johnson@email.com",
    phone="+1-555-0123",
    simulate_failure=False
)

# Execute onboarding
result = await saga.run({"patient_id": saga.patient_id})
```

## Running the Example

```bash
python examples/healthcare_patient_onboarding/main.py
```

Expected output shows:
1. **Scenario 1**: Successful patient onboarding
2. **Scenario 2**: EHR failure with automatic PHI purging

## Actions

### verify_identity(ctx)
Verifies patient identity using SSN, DOB, and photo ID.

**Returns:**
```python
{
    "patient_id": "PAT-2026-001",
    "verification_method": "SSN + DOB + Photo ID",
    "verification_score": 98.5,
    "verified": True,
    "audit_log_id": "AUDIT-VERIFY-PAT-2026-001",
    "timestamp": "2026-01-01T14:30:00Z"
}
```

### create_ehr_record(ctx)
Creates encrypted Electronic Health Record with PHI.

**Returns:**
```python
{
    "ehr_id": "EHR-PAT-2026-001",
    "patient_id": "PAT-2026-001",
    "mrn": "MRN026001",  # Medical Record Number
    "created_at": "2026-01-01T14:30:00Z",
    "encrypted": True,
    "phi_fields": ["ssn", "dob", "address", "phone", "email"],
    "hipaa_compliant": True
}
```

### assign_primary_care_provider(ctx)
Assigns PCP based on availability, specialty, and location.

**Returns:**
```python
{
    "provider_id": "PCP-12345",
    "provider_name": "Dr. Sarah Johnson, MD",
    "specialty": "Family Medicine",
    "location": "Main Street Clinic",
    "accepting_patients": True,
    "assignment_id": "ASSIGN-PAT-2026-001"
}
```

### setup_patient_portal(ctx)
Creates secure patient portal account with MFA.

**Returns:**
```python
{
    "portal_user_id": "PORTAL-PAT-2026-001",
    "email": "alice.johnson@email.com",
    "username": "alice.johnson@email.com",
    "temporary_password": "TempPass123!",
    "mfa_enabled": True,
    "access_level": "patient",
    "features": ["view_records", "schedule_appointments", "messaging", "billing"]
}
```

### schedule_initial_appointment(ctx)
Schedules new patient visit with assigned PCP.

**Returns:**
```python
{
    "appointment_id": "APPT-PAT-2026-001-001",
    "patient_id": "PAT-2026-001",
    "provider_id": "PCP-12345",
    "appointment_type": "New Patient Visit",
    "date": "2026-01-15",
    "time": "10:00 AM",
    "duration_minutes": 60,
    "location": "Main Street Clinic - Room 3"
}
```

### send_welcome_materials(ctx)
Sends welcome packet via email (idempotent).

**Returns:**
```python
{
    "email_sent": True,
    "recipient": "alice.johnson@email.com",
    "materials": [
        "New Patient Forms",
        "HIPAA Privacy Notice",
        "Patient Rights and Responsibilities",
        "Insurance Information Sheet",
        "Portal Login Instructions",
        "Appointment Confirmation (2026-01-15 10:00 AM)"
    ],
    "delivery_status": "delivered"
}
```

## Compensations

### log_verification_rollback(ctx)
**Audit Trail**: Logs verification rollback for HIPAA compliance (audit logs never deleted).

### purge_ehr_record(ctx)
**CRITICAL**: Permanently deletes all PHI from EHR system per HIPAA data minimization.

### unassign_provider(ctx)
Removes PCP assignment and returns provider capacity to pool.

### delete_portal_account(ctx)
Deletes portal account, credentials, and invalidates all sessions.

### cancel_appointment(ctx)
Cancels appointment and returns time slot to provider availability.

## Error Scenarios

### Identity Verification Failure
If identity cannot be verified (low score):
- No compensations needed (no records created yet)
- Audit log entry created for attempt

### EHR System Unavailable
If EHR creation fails:
- Identity verification audit log preserved
- All verified data discarded
- Patient must restart registration

### Portal Creation Failure
If portal setup fails:
- EHR record permanently deleted
- PCP assignment removed
- All PHI purged from systems
- Audit trail preserved

## HIPAA Compliance Details

### Protected Health Information (PHI)
The saga handles these PHI elements:
- Full name
- Date of birth
- Social Security Number (last 4 digits)
- Email address
- Phone number
- Medical Record Number (MRN)
- Appointment details

### Audit Requirements
Every action logs:
- Timestamp (ISO 8601)
- User/System performing action
- Action type and result
- Patient identifier (de-identified in logs when possible)

### Data Retention
- **PHI on failure**: Immediately purged (right to be forgotten)
- **Audit logs**: Retained per HIPAA requirements (6+ years)
- **Successful records**: Retained per medical records laws

## Real-World Integration

### EHR Systems
- **Epic**: HL7 FHIR API integration
- **Cerner**: Millennium Platform API
- **Allscripts**: TouchWorks API
- **Athenahealth**: More Platform API

### Identity Verification
```python
import aiohttp

async def verify_patient_identity(ssn: str, dob: str, name: str):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            "https://api.experian.com/identityverification/v1/verify",
            headers={"Authorization": "Bearer <token>"},
            json={
                "ssn": ssn,
                "dateOfBirth": dob,
                "fullName": name
            }
        )
        return await response.json()
```

### EHR Creation (Epic FHIR)
```python
async def create_epic_patient(patient_data: dict):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            "https://fhir.epic.com/Patient",
            headers={
                "Authorization": "Bearer <token>",
                "Content-Type": "application/fhir+json"
            },
            json={
                "resourceType": "Patient",
                "name": [{"family": patient_data["last_name"], "given": [patient_data["first_name"]]}],
                "birthDate": patient_data["date_of_birth"],
                # ... more FHIR fields
            }
        )
        return await response.json()
```

## Testing

```bash
# Run with default settings
python examples/healthcare_patient_onboarding/main.py

# Test custom scenario
python -c "
import asyncio
from examples.healthcare_patient_onboarding.main import HealthcarePatientOnboardingSaga

async def test():
    saga = HealthcarePatientOnboardingSaga(
        patient_id='TEST-001',
        first_name='Test',
        last_name='Patient',
        date_of_birth='1990-01-01',
        ssn_last_4='9999',
        email='test@example.com',
        phone='+1-555-9999',
        simulate_failure=False
    )
    result = await saga.run({'patient_id': saga.patient_id})
    print(f'Result: {result}')

asyncio.run(test())
"
```

## Related Examples

- **Order Processing** - Basic saga patterns
- **IoT Device Orchestration** - Multi-device coordination
- **Supply Chain Drone Delivery** - Regulatory compliance patterns

## Best Practices

1. **Never log PHI in plain text** - Use de-identified patient IDs in logs
2. **Always encrypt PHI at rest and in transit**
3. **Implement comprehensive audit trails** for all PHI access
4. **Use strong identity verification** before creating records
5. **Test PHI purging thoroughly** in failure scenarios
6. **Implement proper access controls** with RBAC and MFA
7. **Follow HIPAA breach notification rules** if failures occur in production

## Security Considerations

- Use proper encryption (AES-256 for data at rest, TLS 1.3 for transit)
- Implement key rotation for encryption keys
- Use secure random for password generation
- Invalidate sessions on any security event
- Monitor for unusual access patterns
- Implement rate limiting on identity verification

---

**Questions?** Check the [main documentation](../../README.md) or open an issue.

**Disclaimer**: This is a demonstration example. Production healthcare systems require additional security measures, certifications, and compliance validations.
