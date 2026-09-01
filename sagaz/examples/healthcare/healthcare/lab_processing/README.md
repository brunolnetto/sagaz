# Lab Test Processing Saga

**Category:** Healthcare/Life Sciences  
**Pivot Type:** Consumable Resource

## Description

This saga demonstrates a laboratory testing workflow where processing the sample is the **point of no return**. Once a biological sample is centrifuged and aliquoted, it is consumed and cannot be restored. If subsequent tests fail, a new sample must be collected from the patient.

## Saga Flow

```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ receive_sample    │ ──→ │verify_requisition──→ │ queue_for_testing   │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ process_sample              │ ──→ │ run_analysis          │ ──→ │ validate_report│
│ 🔒 PIVOT (sample consumed,  │     │ (forward only)        │     │ (forward only)│
│   cannot be re-tested)      │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

## Pivot Step: `process_sample`

Once the sample is processed:

### Why It's Irreversible

- Biological sample is physically consumed
- Centrifugation separates blood components
- Aliquots are created from limited sample volume
- Original sample cannot be reconstituted

### What Happens After Pivot

- Must use remaining aliquots for any retests
- If aliquots exhausted, need new patient sample
- Results must be reported (even partial)

## Forward Recovery Strategies

| Scenario | Strategy | Action |
|----------|----------|--------|
| Analysis failure (aliquots remain) | RETRY | Use backup aliquot |
| Analysis failure (no aliquots) | MANUAL_INTERVENTION | Schedule recollection |
| Result validation failure | RETRY | Pathologist review |
| Reporting failure | RETRY | Alternative delivery method |

## Usage

```python
from examples.healthcare.lab_processing import LabTestProcessingSaga

saga = LabTestProcessingSaga()

result = await saga.run(
    {
        "sample_id": "SAMP-2026-001",
        "patient_id": "PAT-12345",
        "sample_type": "blood",
        "ordering_provider": "DR-SMITH",
        "tests_ordered": ["CBC", "CMP", "LIPID"],
    }
)
```

## Context Schema

| Field | Type | Description |
|-------|------|-------------|
| `sample_id` | str | Unique sample identifier |
| `patient_id` | str | Patient identifier |
| `sample_type` | str | Type of sample (blood, urine, etc.) |
| `ordering_provider` | str | Provider who ordered tests |
| `tests_ordered` | list[str] | Tests to perform |

## Running the Example

```bash
python examples/healthcare/lab_processing/main.py
```

## Key Concepts Demonstrated

1. **Consumable Resources**: Biological samples are consumed during testing
2. **LIMS Integration**: Laboratory Information Management System patterns
3. **Critical Values**: Urgent result flagging and notification
4. **Aliquot Management**: Using backup sample portions for retests
5. **HL7 Reporting**: Healthcare interoperability standards
