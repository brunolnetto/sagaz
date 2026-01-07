# ADR-026: Industry Examples Expansion Strategy

**Status:** Proposed  
**Date:** 2026-01-07  
**Deciders:** Sagaz Core Team

## Dependencies

**Prerequisites**:
- ADR-023: Pivot/Irreversible Steps (examples will demonstrate pivot feature)
- ADR-022: Compensation Result Passing (examples use result passing patterns)

**Enables**:
- Production adoption across diverse industries
- Pivot feature validation through real-world scenarios
- Community contributions with clear patterns

**Roadmap**: ⭐ **Phase 3 (v1.4.0)** - Expand examples post-pivot implementation

## Context

### Current State

Sagaz currently provides examples in 9 categories:
- **E-commerce**: Order Processing
- **Fintech**: Payment Processing, Trade Execution
- **Healthcare**: Patient Onboarding
- **IoT**: Device Orchestration, Smart Grid
- **Logistics**: Drone Delivery
- **ML**: Training Pipeline, Federated Learning
- **Travel**: Booking
- **Data Engineering**: ETL, Quality Gate, Migration, Lakehouse
- **Monitoring**: Main, Mermaid Demo

### Problem Statement

1. **Limited Industry Coverage**: Many industries with complex saga patterns aren't represented
2. **Pivot Feature Demonstration**: ADR-023 pivot feature needs real-world examples
3. **Forward Recovery Patterns**: No examples show forward recovery vs rollback strategies
4. **Physical/Irreversible Actions**: Limited examples of truly irreversible operations
5. **Regulatory Compliance**: Few examples show compliance-driven pivots

### Opportunity

Expanding examples will:
- Demonstrate pivot feature value across industries
- Provide copy-paste patterns for production adoption
- Validate the pivot/forward-recovery design
- Build community through recognizable industry scenarios

## Decision

Implement **24 new industry examples** across **12 categories**, each demonstrating:
1. Clear pivot identification (where applicable)
2. Forward recovery strategies (post-pivot)
3. Compensation patterns (pre-pivot)
4. Real-world failure scenarios

### New Example Categories

| Category | New Examples | Pivot Focus |
|----------|--------------|-------------|
| Fintech/Blockchain | 4 | Financial commitment, blockchain immutability |
| Manufacturing | 3 | Physical processes, material consumption |
| Healthcare | 3 | Consumable resources, patient safety |
| Telecommunications | 2 | Regulatory actions, network state |
| Media/Content | 2 | Global distribution, live events |
| Government | 2 | Regulatory submissions, biometric capture |
| Gaming | 2 | Match start, payment processing |
| Real Estate | 2 | Escrow release, legal commitments |
| Energy | 2 | Physical switches, billing activation |
| Education | 2 | Seat reservation, timed assessments |

## Detailed Example Specifications

---

## Category 1: Fintech / Blockchain

### Example 1.1: Cryptocurrency Exchange Saga

**Files:** `examples/fintech/crypto_exchange/`

**Description:** Trade execution with wallet transfers and blockchain confirmation pivots.

**Saga Flow:**
```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│ validate_trade  │ ──→ │  reserve_balance │ ──→ │ execute_exchange   │
│ (reversible)    │     │  (reversible)    │     │ (internal ledger)  │
└─────────────────┘     └──────────────────┘     └─────────┬──────────┘
                                                           │
                        ┌──────────────────────────────────┘
                        ↓
┌─────────────────────────────┐     ┌───────────────────┐     ┌─────────────────┐
│ broadcast_to_blockchain     │ ──→ │ wait_confirmation │ ──→ │ update_balances │
│ 🔒 PIVOT (once broadcast,   │     │ (forward only)    │     │ (forward only)  │
│   cannot undo on-chain)     │     │                   │     │                 │
└─────────────────────────────┘     └───────────────────┘     └─────────────────┘
```

**Pivot Step:** `broadcast_to_blockchain`
- Once transaction is broadcast to the network, it's in the mempool
- Even if not confirmed, it may eventually be mined
- Cannot be "cancelled" - only superseded with higher fee (RBF)

**Forward Recovery:**
- If confirmation fails: retry with higher gas, send RBF transaction
- If balance update fails: reconcile from blockchain state

**Context Schema:**
```python
{
    "trade_id": str,
    "user_id": str,
    "from_currency": str,  # "BTC"
    "to_currency": str,    # "ETH"
    "amount": Decimal,
    "exchange_rate": Decimal,
    "destination_wallet": str,
    "network": str,  # "ethereum", "bitcoin"
}
```

---

### Example 1.2: Cross-Border Wire Transfer

**Files:** `examples/fintech/wire_transfer/`

**Description:** SWIFT messaging with regulatory holds and FX rate commitment pivots.

**Saga Flow:**
```
┌──────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ validate_transfer│ ──→ │ compliance_check│ ──→ │ reserve_fx_rate     │
│ (reversible)     │     │ (reversible)    │     │ (15 min window)     │
└──────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                            │
                         ┌──────────────────────────────────┘
                         ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ submit_swift_message        │ ──→ │ debit_source_account  │ ──→ │ notify_parties│
│ 🔒 PIVOT (SWIFT message     │     │ 🔒 PIVOT (funds       │     │ (forward only)│
│   sent to correspondent)    │     │   committed)          │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Steps:** `submit_swift_message` AND `debit_source_account`
- SWIFT MT103 message once sent is logged in banking networks
- Debit from source account is the commitment point

**Forward Recovery:**
- If SWIFT confirmation fails: check SWIFT gpi tracker, resend with new UETR
- If notification fails: retry notification, manual outreach

**Context Schema:**
```python
{
    "transfer_id": str,
    "sender_account": str,
    "receiver_account": str,
    "receiver_bic": str,
    "amount": Decimal,
    "currency": str,
    "fx_rate": Decimal,
    "purpose_code": str,
    "compliance_status": str,
}
```

---

### Example 1.3: Loan Origination

**Files:** `examples/fintech/loan_origination/`

**Description:** Application processing through to funds disbursement.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ submit_application│ ──→ │ run_credit_check│ ──→ │ underwriting_review │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ generate_loan_documents     │ ──→ │ disburse_funds        │ ──→ │ send_welcome  │
│ (reversible)                │     │ 🔒 PIVOT (money       │     │ (forward only)│
│                             │     │   transferred)        │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `disburse_funds`
- Once funds are in borrower's account, the loan is active
- Can only be "compensated" via loan payoff (expensive, complex)

**Forward Recovery:**
- If welcome email fails: retry, escalate to phone call
- If document storage fails: regenerate, manual filing

**Context Schema:**
```python
{
    "application_id": str,
    "applicant_id": str,
    "loan_amount": Decimal,
    "loan_term_months": int,
    "interest_rate": Decimal,
    "credit_score": int,
    "disbursement_account": str,
}
```

---

### Example 1.4: Insurance Claim Processing

**Files:** `examples/fintech/insurance_claim/`

**Description:** Claim assessment through to payment disbursement.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ submit_claim      │ ──→ │ validate_policy │ ──→ │ assess_damage       │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ approve_claim               │ ──→ │ disburse_payment      │ ──→ │ close_case    │
│ (reversible)                │     │ 🔒 PIVOT (payment     │     │ (forward only)│
│                             │     │   sent to claimant)   │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `disburse_payment`
- Once check is mailed or ACH initiated, funds are committed
- Can only recover via clawback (legal action)

**Forward Recovery:**
- If case closure fails: retry, manual closure
- If payment tracking fails: reconcile from bank records

---

## Category 2: Manufacturing / Industrial

### Example 2.1: Manufacturing Production Saga

**Files:** `examples/manufacturing/production/`

**Description:** Material reservation through production start (physical action pivot).

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ validate_order    │ ──→ │reserve_materials│ ──→ │ schedule_production │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ start_production            │ ──→ │ quality_check         │ ──→ │ package_ship  │
│ 🔒 PIVOT (machines running, │     │ (forward only)        │     │ (forward only)│
│   materials in process)     │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `start_production`
- Once CNC machines start cutting, materials are committed
- Physical transformation is irreversible
- Stopping mid-production creates scrap

**Forward Recovery:**
- If quality check fails: rework, scrap and restart, use secondary materials
- If packaging fails: repackage, hold for manual handling

**Context Schema:**
```python
{
    "work_order_id": str,
    "product_sku": str,
    "quantity": int,
    "materials": list[dict],  # [{sku, quantity, lot_number}]
    "machine_id": str,
    "operator_id": str,
    "quality_specs": dict,
}
```

---

### Example 2.2: Chemical Reactor Process

**Files:** `examples/manufacturing/chemical_reactor/`

**Description:** Chemical reaction that cannot be stopped mid-process.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ validate_recipe   │ ──→ │ load_ingredients│ ──→ │ preheat_reactor     │
│ (reversible)      │     │ (reversible*)   │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ start_reaction              │ ──→ │ cooling_phase         │ ──→ │ extract_product│
│ 🔒 PIVOT (chemical rxn      │     │ (forward only)        │     │ (forward only)│
│   started, exothermic)      │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `start_reaction`
- Chemical reaction once initiated must complete
- Stopping mid-reaction can be dangerous (runaway, pressure)
- Ingredients consumed in reaction

**Forward Recovery:**
- If cooling fails: emergency cooling, evacuate, contain
- If extraction fails: manual extraction, waste disposal

---

### Example 2.3: 3D Printing Job

**Files:** `examples/manufacturing/3d_printing/`

**Description:** Additive manufacturing with material commitment.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ validate_model    │ ──→ │ check_material  │ ──→ │ preheat_printer     │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ start_print                 │ ──→ │ post_process          │ ──→ │ quality_scan  │
│ 🔒 PIVOT (material being    │     │ (forward only)        │     │ (forward only)│
│   deposited, job committed) │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `start_print`
- Once first layer is deposited, material is committed
- Cancelling mid-print wastes material and time
- Must complete or scrap

---

## Category 3: Healthcare / Life Sciences

### Example 3.1: Medical Procedure Scheduling

**Files:** `examples/healthcare/procedure_scheduling/`

**Description:** Surgical procedure with anesthesia start as pivot.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ verify_insurance  │ ──→ │ pre_authorize   │ ──→ │ prep_patient        │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ start_anesthesia            │ ──→ │ perform_procedure     │ ──→ │ recovery_watch│
│ 🔒 PIVOT (patient under,    │     │ (forward only)        │     │ (forward only)│
│   cannot abort safely)      │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
                                                                          │
                                                              ┌───────────┘
                                                              ↓
                                                    ┌─────────────────┐
                                                    │ bill_procedure  │
                                                    │ (forward only)  │
                                                    └─────────────────┘
```

**Pivot Step:** `start_anesthesia`
- Patient is sedated, cannot be "unsedated" mid-procedure
- Must complete procedure safely
- Billable charges begin

**Forward Recovery:**
- If procedure has complications: escalate, additional treatment
- If billing fails: retry, manual billing

---

### Example 3.2: Lab Test Processing

**Files:** `examples/healthcare/lab_processing/`

**Description:** Consumable sample processing.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ receive_sample    │ ──→ │ verify_requisition ──→ │ queue_for_testing │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ process_sample              │ ──→ │ run_analysis          │ ──→ │ report_results│
│ 🔒 PIVOT (sample consumed,  │     │ (forward only)        │     │ (forward only)│
│   cannot be re-tested)      │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `process_sample`
- Biological sample is consumed (centrifuged, aliquoted)
- Cannot restore original sample
- If test fails, need new draw from patient

**Forward Recovery:**
- If analysis fails: request new sample, flag for re-draw
- If reporting fails: retry, manual result entry

---

### Example 3.3: Prescription Fulfillment

**Files:** `examples/healthcare/prescription/`

**Description:** Medication dispensing with regulatory tracking.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ verify_prescription ──→ │ check_inventory │ ──→ │ insurance_adjudicate│
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ dispense_medication         │ ──→ │ patient_pickup        │ ──→ │ insurance_recon│
│ 🔒 PIVOT (controlled        │     │ (forward only)        │     │ (forward only)│
│   substance logged, sealed) │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `dispense_medication`
- Medication removed from inventory, sealed in patient's name
- DEA tracking for controlled substances
- PDMP (Prescription Drug Monitoring Program) updated

---

## Category 4: Telecommunications

### Example 4.1: Mobile Number Porting

**Files:** `examples/telecom/number_porting/`

**Description:** Regulatory number port with FCC compliance.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ submit_port_request ──→ │ validate_customer ──→ │ donor_verification │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ execute_port                │ ──→ │ activate_new_carrier  │ ──→ │ notify_customer│
│ 🔒 PIVOT (NPAC updated,     │     │ (forward only)        │     │ (forward only)│
│   number officially ported) │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `execute_port`
- Number Portability Administration Center (NPAC) updated
- Regulatory action, recorded in national database
- Port-back requires new full port request

---

### Example 4.2: SIM Provisioning

**Files:** `examples/telecom/sim_provisioning/`

**Description:** SIM card activation with HLR registration.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ verify_identity   │ ──→ │ validate_device │ ──→ │ check_contract      │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ activate_sim                │ ──→ │ register_hlr          │ ──→ │ send_welcome  │
│ 🔒 PIVOT (SIM active,       │     │ (forward only)        │     │ (forward only)│
│   billing starts)           │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `activate_sim`
- SIM activated in network, can make/receive calls
- Billing cycle begins
- Deactivation is separate process (not rollback)

---

## Category 5: Media / Content

### Example 5.1: Live Streaming Saga

**Files:** `examples/media/live_streaming/`

**Description:** Real-time broadcast with global CDN distribution.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ validate_event    │ ──→ │reserve_capacity │ ──→ │ configure_encoders  │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ go_live                     │ ──→ │ monitor_stream        │ ──→ │ archive_vod   │
│ 🔒 PIVOT (stream active,    │     │ (forward only)        │     │ (forward only)│
│   viewers connected)        │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `go_live`
- Stream is public, viewers are watching
- Cannot "undo" that viewers saw content
- Must handle gracefully (end stream, not rollback)

**Forward Recovery:**
- If monitoring fails: continue stream, alert ops
- If archival fails: retry from buffer, lose VOD

---

### Example 5.2: Content Publishing Pipeline

**Files:** `examples/media/content_publishing/`

**Description:** Article/post publishing with global CDN cache.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ submit_draft      │ ──→ │ editorial_review│ ──→ │ legal_review        │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ publish_content             │ ──→ │ distribute_cdn        │ ──→ │ notify_social │
│ 🔒 PIVOT (content public,   │     │ (forward only)        │     │ (forward only)│
│   indexed by search)        │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `publish_content`
- Content is public, indexed by Google
- Cached globally in CDN (100+ edge locations)
- Cannot truly "unpublish" - only replace or redirect

---

## Category 6: Government / Compliance

### Example 6.1: Visa Application Processing

**Files:** `examples/government/visa_application/`

**Description:** Immigration application with biometric capture.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ submit_application│ ──→ │ document_check  │ ──→ │ schedule_interview  │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ capture_biometrics          │ ──→ │ background_check      │ ──→ │ render_decision│
│ 🔒 PIVOT (fingerprints,     │     │ (forward only)        │     │ (forward only)│
│   photo in govt database)   │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `capture_biometrics`
- Biometrics stored in government database
- Cannot be "deleted" - only flagged
- Application is now officially "in process"

---

### Example 6.2: Regulatory Filing

**Files:** `examples/government/regulatory_filing/`

**Description:** SEC/FDA/EPA submission with official acknowledgment.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ prepare_filing    │ ──→ │ validate_format │ ──→ │ sign_filing         │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ submit_to_authority         │ ──→ │ receive_acknowledgment│ ──→ │ archive_record│
│ 🔒 PIVOT (filing received,  │     │ (forward only)        │     │ (forward only)│
│   officially on record)     │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `submit_to_authority`
- Filing received by regulatory body (SEC EDGAR, FDA ESG)
- Public record, cannot be "unfiled"
- Only amendments can be submitted

---

## Category 7: Gaming / Entertainment

### Example 7.1: Tournament Match Saga

**Files:** `examples/gaming/tournament_match/`

**Description:** Esports match with anti-cheat and prize pool.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ validate_players  │ ──→ │ check_eligibility ──→ │ reserve_server     │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ start_match                 │ ──→ │ track_progress        │ ──→ │ finalize_result│
│ 🔒 PIVOT (match underway,   │     │ (forward only)        │     │ (forward only)│
│   tournament bracket locked)│     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
                                                                          │
                                                              ┌───────────┘
                                                              ↓
                                                    ┌─────────────────┐
                                                    │ distribute_prizes│
                                                    │ (forward only)  │
                                                    └─────────────────┘
```

**Pivot Step:** `start_match`
- Match timer starts, players are committed
- Tournament bracket locked at this position
- Forfeit rules apply (cannot just "cancel")

---

### Example 7.2: In-Game Purchase

**Files:** `examples/gaming/in_game_purchase/`

**Description:** Microtransaction with virtual item delivery.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ validate_cart     │ ──→ │ check_balance   │ ──→ │ reserve_items       │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ charge_payment              │ ──→ │ deliver_items         │ ──→ │ update_inventory│
│ 🔒 PIVOT (payment charged,  │     │ (forward only)        │     │ (forward only)│
│   cannot refund without TOS)│     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `charge_payment`
- Payment charged to player
- Virtual items committed
- Refunds require support escalation (TOS dependent)

---

## Category 8: Real Estate

### Example 8.1: Property Closing Saga

**Files:** `examples/real_estate/property_closing/`

**Description:** Real estate transaction with escrow release.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ title_search      │ ──→ │ appraisal_review│ ──→ │ clear_contingencies │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ release_escrow              │ ──→ │ record_deed           │ ──→ │ transfer_keys │
│ 🔒 PIVOT (funds released,   │     │ 🔒 PIVOT (ownership   │     │ (forward only)│
│   transaction committed)    │     │   legally transferred)│     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Steps:** `release_escrow` AND `record_deed`
- Escrow release = funds to seller
- Deed recording = legal transfer of ownership
- Reversing requires new transaction (sale or lawsuit)

---

### Example 8.2: Rental Application

**Files:** `examples/real_estate/rental_application/`

**Description:** Tenant screening with security deposit.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ submit_application│ ──→ │ credit_check    │ ──→ │ landlord_approval   │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ charge_security_deposit     │ ──→ │ generate_lease        │ ──→ │ welcome_tenant│
│ 🔒 PIVOT (deposit charged,  │     │ (forward only)        │     │ (forward only)│
│   unit held for tenant)     │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `charge_security_deposit`
- Deposit commits the unit to this tenant
- Other applications now rejected
- Refund only per local tenancy laws

---

## Category 9: Energy / Utilities

### Example 9.1: Smart Meter Deployment

**Files:** `examples/energy/smart_meter/`

**Description:** Meter activation with billing system integration.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ schedule_install  │ ──→ │ verify_location │ ──→ │ install_hardware    │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ activate_meter              │ ──→ │ verify_readings       │ ──→ │ notify_customer│
│ 🔒 PIVOT (meter live,       │     │ (forward only)        │     │ (forward only)│
│   billing starts)           │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `activate_meter`
- Meter is transmitting readings
- Billing cycle has begun
- Deactivation requires service termination request

---

### Example 9.2: Power Grid Switching

**Files:** `examples/energy/grid_switching/`

**Description:** Physical grid reconfiguration.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ analyze_load      │ ──→ │ notify_operators│ ──→ │ verify_clearances   │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ execute_switch              │ ──→ │ monitor_stability     │ ──→ │ confirm_complete│
│ 🔒 PIVOT (physical breakers │     │ (forward only)        │     │ (forward only)│
│   changed, grid reconfigured│     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `execute_switch`
- Physical breakers opened/closed
- Grid topology changed
- Reversing requires another switching operation

---

## Category 10: Education

### Example 10.1: Course Enrollment

**Files:** `examples/education/course_enrollment/`

**Description:** University registration with seat confirmation.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ check_prerequisites ──→ │ check_availability ─→ │ process_payment     │
│ (reversible)      │     │ (reversible)    │     │ (reversible*)       │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ confirm_enrollment          │ ──→ │ grant_lms_access      │ ──→ │ send_welcome  │
│ 🔒 PIVOT (seat reserved,    │     │ (forward only)        │     │ (forward only)│
│   registrar updated)        │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

**Pivot Step:** `confirm_enrollment`
- Seat is reserved in course roster
- Other students may be waitlisted because of this
- Withdrawal follows academic calendar/refund policy

---

### Example 10.2: Exam Proctoring

**Files:** `examples/education/exam_proctoring/`

**Description:** Remote proctored exam with timer start.

**Saga Flow:**
```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ verify_identity   │ ──→ │ check_environment ─→ │ launch_lockdown    │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ start_exam                  │ ──→ │ receive_submission    │ ──→ │ grade_exam    │
│ 🔒 PIVOT (timer started,    │     │ (forward only)        │     │ (forward only)│
│   exam attempt recorded)    │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
                                                                          │
                                                              ┌───────────┘
                                                              ↓
                                                    ┌─────────────────┐
                                                    │ publish_results │
                                                    │ (forward only)  │
                                                    └─────────────────┘
```

**Pivot Step:** `start_exam`
- Exam timer started, cannot be paused
- Attempt recorded in academic record
- Student cannot "un-start" and try later

---

## Implementation Approach

### Phase 1: Foundation (v1.3.0)
- Implement ADR-023 pivot feature
- Update existing examples with pivot markers
- Add forward recovery patterns to framework

### Phase 2: Core Examples (v1.4.0)
- Implement 6 priority examples:
  1. Crypto Exchange (blockchain pivot)
  2. Manufacturing Production (physical pivot)
  3. Live Streaming (real-time pivot)
  4. Lab Processing (consumable pivot)
  5. Number Porting (regulatory pivot)
  6. Property Closing (legal pivot)

### Phase 3: Industry Expansion (v1.5.0)
- Remaining 18 examples
- Community-contributed examples
- Industry-specific documentation

### File Structure

```
examples/
├── fintech/
│   ├── crypto_exchange/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── README.md
│   │   └── test_crypto_exchange.py
│   ├── wire_transfer/
│   ├── loan_origination/
│   └── insurance_claim/
├── manufacturing/
│   ├── production/
│   ├── chemical_reactor/
│   └── 3d_printing/
├── healthcare/
│   ├── procedure_scheduling/
│   ├── lab_processing/
│   └── prescription/
├── telecom/
│   ├── number_porting/
│   └── sim_provisioning/
├── media/
│   ├── live_streaming/
│   └── content_publishing/
├── government/
│   ├── visa_application/
│   └── regulatory_filing/
├── gaming/
│   ├── tournament_match/
│   └── in_game_purchase/
├── real_estate/
│   ├── property_closing/
│   └── rental_application/
├── energy/
│   ├── smart_meter/
│   └── grid_switching/
└── education/
    ├── course_enrollment/
    └── exam_proctoring/
```

## Consequences

### Positive
- **Comprehensive Coverage**: 24 new examples across 10 industries
- **Pivot Validation**: Real-world scenarios prove pivot feature value
- **Adoption Catalyst**: Copy-paste patterns accelerate production use
- **Documentation by Example**: Each example documents a saga pattern
- **Community Growth**: Recognizable scenarios invite contributions

### Negative
- **Maintenance Burden**: 24 new examples to maintain
- **Scope Creep Risk**: Each example could grow complex
- **Testing Overhead**: Need tests for all examples
- **Documentation Load**: Each needs README and inline docs

### Neutral
- **Learning Curve**: Users must find relevant example for their domain
- **Framework Changes**: Examples must update when API changes

## Success Metrics

1. **Example Coverage**: 100% of 24 planned examples implemented
2. **Test Coverage**: Each example has unit tests passing
3. **Documentation**: Each example has README.md with clear explanation
4. **Pivot Demonstration**: At least 20/24 examples demonstrate pivot feature
5. **Community Adoption**: Tracking example-based issues/PRs

## References

- [ADR-023: Pivot/Irreversible Steps](adr-023-pivot-irreversible-steps.md)
- [ADR-022: Compensation Result Passing](adr-022-compensation-result-passing.md)
- [Saga Pattern - Chris Richardson](https://microservices.io/patterns/data/saga.html)
