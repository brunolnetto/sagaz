# Industry Examples Expansion - Implementation Plan

**Version:** 1.0  
**Created:** 2026-01-07  
**Target Release:** v1.4.0 - v1.5.0  
**Related ADR:** [ADR-026: Industry Examples Expansion Strategy](adr/adr-026-industry-examples-expansion.md)

---

## Executive Summary

This implementation plan details the phased rollout of **24 new industry examples** across **10 categories**, each designed to demonstrate the Sagaz saga pattern with pivot/irreversible steps (ADR-023) and forward recovery strategies.

---

## Phase Overview

| Phase | Version | Examples | Focus |
|-------|---------|----------|-------|
| **Phase 0** | v1.3.0 | 0 | Pivot feature implementation ✅ **IMPLEMENTED** |
| **Phase 1** | v1.4.0 | 6 | Priority examples (one per pivot type) ✅ **CREATED** |
| **Phase 2** | v1.5.0 | 12 | Industry breadth expansion ✅ **CREATED** |
| **Phase 3** | v1.6.0 | 6 | Complete coverage ✅ **CREATED** |

> **Note (2026-01-07):** All 24 industry examples have been created!
> The pivot feature was already implemented in `sagaz/pivot.py`.
> Phase 3 examples use `pivot=True` and `@forward_recovery` features.
>
> **Examples Created (24 total):**
> - Phase 1 (6): crypto_exchange, production, live_streaming, lab_processing, number_porting, property_closing
> - Phase 2 (12): wire_transfer, loan_origination, insurance_claim, 3d_printing, prescription, 
>   tournament_match, in_game_purchase, visa_application, regulatory_filing, smart_meter,
>   course_enrollment, content_publishing
> - Phase 3 (6): rental_application, power_grid, exam_proctoring, chemical_reactor,
>   sim_provisioning, procedure_scheduling

---

## Phase 0: Prerequisites (v1.3.0)

### Objective
Implement ADR-023 pivot feature before examples can use it.

### Tasks

| Task ID | Description | Effort | Status |
|---------|-------------|--------|--------|
| P0-001 | Implement `pivot=True` parameter in `add_dag_step()` | 2d | ⬜ Pending |
| P0-002 | Implement taint propagation algorithm | 3d | ⬜ Pending |
| P0-003 | Add `SagaZones` calculation and visualization | 2d | ⬜ Pending |
| P0-004 | Implement `@forward_recovery` decorator | 2d | ⬜ Pending |
| P0-005 | Add `RecoveryAction` enum and handling | 1d | ⬜ Pending |
| P0-006 | Update `SagaResult` with pivot-aware fields | 1d | ⬜ Pending |
| P0-007 | Add Mermaid diagram zone coloring | 1d | ⬜ Pending |
| P0-008 | Write pivot feature unit tests | 2d | ⬜ Pending |
| P0-009 | Update documentation for pivot feature | 1d | ⬜ Pending |

**Total Effort:** 15 days  
**Dependency:** Blocks all Phase 1+ examples

---

## Phase 1: Priority Examples (v1.4.0)

### Objective
Implement 6 high-impact examples, one per pivot type category.

### Example Selection Criteria
- **Diverse pivot types**: Financial, physical, regulatory, consumable, real-time, legal
- **High recognition**: Developers immediately understand the scenario
- **Clear pivot point**: Obvious "point of no return"
- **Forward recovery patterns**: Show retry, alternate, escalation strategies

### Priority Examples

#### 1.1: Cryptocurrency Exchange Saga ⭐⭐⭐⭐⭐

**Category:** Fintech/Blockchain  
**Pivot Type:** Blockchain immutability  
**Path:** `examples/fintech/crypto_exchange/`

| Task ID | Description | Effort | Assignee |
|---------|-------------|--------|----------|
| P1-101 | Create directory structure and `__init__.py` | 0.5h | - |
| P1-102 | Implement `main.py` with saga class | 4h | - |
| P1-103 | Add blockchain simulation helpers | 2h | - |
| P1-104 | Implement forward recovery for confirmation timeout | 2h | - |
| P1-105 | Write unit tests | 2h | - |
| P1-106 | Write README.md with flow diagram | 1h | - |

**Saga Steps:**
```python
@action("validate_trade")
@action("reserve_balance", depends_on=["validate_trade"])
@action("execute_internal_exchange", depends_on=["reserve_balance"])
@action("broadcast_to_blockchain", depends_on=["execute_internal_exchange"], pivot=True)
@action("wait_confirmations", depends_on=["broadcast_to_blockchain"])
@action("update_balances", depends_on=["wait_confirmations"])

@forward_recovery("wait_confirmations")
async def handle_confirmation_timeout(ctx, error) -> RecoveryAction:
    if ctx.get("retry_count", 0) < 3:
        return RecoveryAction.RETRY
    if can_replace_by_fee():
        return RecoveryAction.RETRY_WITH_ALTERNATE  # RBF
    return RecoveryAction.MANUAL_INTERVENTION
```

**Total Effort:** 11.5 hours

---

#### 1.2: Manufacturing Production Saga ⭐⭐⭐⭐⭐

**Category:** Manufacturing  
**Pivot Type:** Physical action  
**Path:** `examples/manufacturing/production/`

| Task ID | Description | Effort | Assignee |
|---------|-------------|--------|----------|
| P1-201 | Create directory structure | 0.5h | - |
| P1-202 | Implement `main.py` with production saga | 4h | - |
| P1-203 | Add MES (Manufacturing Execution System) simulation | 2h | - |
| P1-204 | Implement quality check forward recovery | 2h | - |
| P1-205 | Write unit tests | 2h | - |
| P1-206 | Write README.md | 1h | - |

**Saga Steps:**
```python
@action("validate_work_order")
@action("reserve_materials", depends_on=["validate_work_order"])
@action("schedule_machine", depends_on=["reserve_materials"])
@action("start_production", depends_on=["schedule_machine"], pivot=True)
@action("run_quality_check", depends_on=["start_production"])
@action("package_product", depends_on=["run_quality_check"])
@action("ship_to_warehouse", depends_on=["package_product"])

@forward_recovery("run_quality_check")
async def handle_quality_failure(ctx, error) -> RecoveryAction:
    if error.type == "minor_defect" and ctx.get("rework_attempts", 0) < 2:
        return RecoveryAction.RETRY_WITH_ALTERNATE  # Rework
    if has_secondary_materials():
        ctx.set("use_secondary", True)
        return RecoveryAction.RETRY
    return RecoveryAction.MANUAL_INTERVENTION  # Scrap decision
```

**Total Effort:** 11.5 hours

---

#### 1.3: Live Streaming Saga ⭐⭐⭐⭐⭐

**Category:** Media/Content  
**Pivot Type:** Real-time event  
**Path:** `examples/media/live_streaming/`

| Task ID | Description | Effort | Assignee |
|---------|-------------|--------|----------|
| P1-301 | Create directory structure | 0.5h | - |
| P1-302 | Implement `main.py` with streaming saga | 4h | - |
| P1-303 | Add CDN/encoder simulation | 2h | - |
| P1-304 | Implement stream health forward recovery | 2h | - |
| P1-305 | Write unit tests | 2h | - |
| P1-306 | Write README.md | 1h | - |

**Saga Steps:**
```python
@action("validate_event")
@action("reserve_capacity", depends_on=["validate_event"])
@action("configure_encoders", depends_on=["reserve_capacity"])
@action("warmup_cdn", depends_on=["configure_encoders"])
@action("go_live", depends_on=["warmup_cdn"], pivot=True)
@action("monitor_stream", depends_on=["go_live"])
@action("archive_to_vod", depends_on=["monitor_stream"])

@forward_recovery("monitor_stream")
async def handle_stream_failure(ctx, error) -> RecoveryAction:
    if error.type == "encoder_failure" and has_backup_encoder():
        return RecoveryAction.RETRY_WITH_ALTERNATE
    if error.type == "cdn_partial":
        # Continue with reduced quality
        ctx.set("quality", "720p")
        return RecoveryAction.SKIP  # Skip problematic edge
    return RecoveryAction.MANUAL_INTERVENTION
```

**Total Effort:** 11.5 hours

---

#### 1.4: Lab Test Processing Saga ⭐⭐⭐⭐

**Category:** Healthcare  
**Pivot Type:** Consumable resource  
**Path:** `examples/healthcare/lab_processing/`

| Task ID | Description | Effort | Assignee |
|---------|-------------|--------|----------|
| P1-401 | Create directory structure | 0.5h | - |
| P1-402 | Implement `main.py` with lab saga | 4h | - |
| P1-403 | Add LIMS (Lab Info System) simulation | 2h | - |
| P1-404 | Implement analysis failure recovery | 2h | - |
| P1-405 | Write unit tests | 2h | - |
| P1-406 | Write README.md | 1h | - |

**Saga Steps:**
```python
@action("receive_sample")
@action("verify_requisition", depends_on=["receive_sample"])
@action("queue_for_testing", depends_on=["verify_requisition"])
@action("process_sample", depends_on=["queue_for_testing"], pivot=True)
@action("run_analysis", depends_on=["process_sample"])
@action("validate_results", depends_on=["run_analysis"])
@action("report_to_provider", depends_on=["validate_results"])

@forward_recovery("run_analysis")
async def handle_analysis_failure(ctx, error) -> RecoveryAction:
    if has_remaining_aliquot():
        return RecoveryAction.RETRY
    # Need new sample from patient
    await schedule_recollection(ctx)
    return RecoveryAction.MANUAL_INTERVENTION
```

**Total Effort:** 11.5 hours

---

#### 1.5: Mobile Number Porting Saga ⭐⭐⭐⭐

**Category:** Telecommunications  
**Pivot Type:** Regulatory action  
**Path:** `examples/telecom/number_porting/`

| Task ID | Description | Effort | Assignee |
|---------|-------------|--------|----------|
| P1-501 | Create directory structure | 0.5h | - |
| P1-502 | Implement `main.py` with porting saga | 4h | - |
| P1-503 | Add NPAC simulation | 2h | - |
| P1-504 | Implement activation failure recovery | 2h | - |
| P1-505 | Write unit tests | 2h | - |
| P1-506 | Write README.md | 1h | - |

**Saga Steps:**
```python
@action("submit_port_request")
@action("validate_customer", depends_on=["submit_port_request"])
@action("verify_with_donor", depends_on=["validate_customer"])
@action("execute_port", depends_on=["verify_with_donor"], pivot=True)  # NPAC updated
@action("activate_new_carrier", depends_on=["execute_port"])
@action("update_routing", depends_on=["activate_new_carrier"])
@action("notify_customer", depends_on=["update_routing"])

@forward_recovery("activate_new_carrier")
async def handle_activation_failure(ctx, error) -> RecoveryAction:
    if error.type == "provisioning_delay":
        return RecoveryAction.RETRY
    if error.type == "sim_not_ready":
        await expedite_sim_shipment(ctx)
        return RecoveryAction.RETRY_WITH_ALTERNATE
    return RecoveryAction.MANUAL_INTERVENTION
```

**Total Effort:** 11.5 hours

---

#### 1.6: Property Closing Saga ⭐⭐⭐⭐

**Category:** Real Estate  
**Pivot Type:** Legal commitment  
**Path:** `examples/real_estate/property_closing/`

| Task ID | Description | Effort | Assignee |
|---------|-------------|--------|----------|
| P1-601 | Create directory structure | 0.5h | - |
| P1-602 | Implement `main.py` with closing saga | 4h | - |
| P1-603 | Add escrow/title simulation | 2h | - |
| P1-604 | Implement deed recording recovery | 2h | - |
| P1-605 | Write unit tests | 2h | - |
| P1-606 | Write README.md | 1h | - |

**Saga Steps:**
```python
@action("title_search")
@action("appraisal_review", depends_on=["title_search"])
@action("clear_contingencies", depends_on=["appraisal_review"])
@action("final_walkthrough", depends_on=["clear_contingencies"])
@action("release_escrow", depends_on=["final_walkthrough"], pivot=True)
@action("record_deed", depends_on=["release_escrow"], pivot=True)
@action("transfer_keys", depends_on=["record_deed"])
@action("notify_parties", depends_on=["transfer_keys"])

@forward_recovery("record_deed")
async def handle_recording_failure(ctx, error) -> RecoveryAction:
    if error.type == "county_office_closed":
        ctx.set("recording_date", next_business_day())
        return RecoveryAction.RETRY
    if error.type == "document_rejection":
        await prepare_corrected_deed(ctx)
        return RecoveryAction.RETRY_WITH_ALTERNATE
    return RecoveryAction.MANUAL_INTERVENTION
```

**Total Effort:** 11.5 hours

---

### Phase 1 Summary

| Metric | Value |
|--------|-------|
| **Examples** | 6 |
| **Total Effort** | 69 hours (~9 days) |
| **Pivot Types Covered** | Blockchain, Physical, Real-time, Consumable, Regulatory, Legal |
| **Target Release** | v1.4.0 |

---

## Phase 2: Industry Breadth (v1.5.0)

### Objective
Expand to 12 more examples covering remaining industries.

### Example List

| # | Example | Category | Pivot Step | Effort |
|---|---------|----------|------------|--------|
| 2.1 | Cross-Border Wire Transfer | Fintech | `submit_swift_message` | 10h |
| 2.2 | Loan Origination | Fintech | `disburse_funds` | 10h |
| 2.3 | Insurance Claim Processing | Fintech | `disburse_payment` | 10h |
| 2.4 | Chemical Reactor Process | Manufacturing | `start_reaction` | 10h |
| 2.5 | 3D Printing Job | Manufacturing | `start_print` | 10h |
| 2.6 | Medical Procedure Scheduling | Healthcare | `start_anesthesia` | 10h |
| 2.7 | Prescription Fulfillment | Healthcare | `dispense_medication` | 10h |
| 2.8 | SIM Provisioning | Telecom | `activate_sim` | 10h |
| 2.9 | Content Publishing Pipeline | Media | `publish_content` | 10h |
| 2.10 | Visa Application Processing | Government | `capture_biometrics` | 10h |
| 2.11 | Regulatory Filing | Government | `submit_to_authority` | 10h |
| 2.12 | Tournament Match Saga | Gaming | `start_match` | 10h |

### Phase 2 Summary

| Metric | Value |
|--------|-------|
| **Examples** | 12 |
| **Total Effort** | 120 hours (~15 days) |
| **New Categories** | Government, Gaming |
| **Target Release** | v1.5.0 |

---

## Phase 3: Complete Coverage (v1.6.0)

### Objective
Complete all 24 examples and establish community contribution patterns.

### Example List

| # | Example | Category | Pivot Step | Effort |
|---|---------|----------|------------|--------|
| 3.1 | In-Game Purchase | Gaming | `charge_payment` | 10h |
| 3.2 | Rental Application | Real Estate | `charge_security_deposit` | 10h |
| 3.3 | Smart Meter Deployment | Energy | `activate_meter` | 10h |
| 3.4 | Power Grid Switching | Energy | `execute_switch` | 10h |
| 3.5 | Course Enrollment | Education | `confirm_enrollment` | 10h |
| 3.6 | Exam Proctoring | Education | `start_exam` | 10h |

### Community Contribution Tasks

| Task ID | Description | Effort |
|---------|-------------|--------|
| P3-C01 | Create CONTRIBUTING.md for examples | 4h |
| P3-C02 | Create example template (`_template/`) | 4h |
| P3-C03 | Add example validation CI workflow | 4h |
| P3-C04 | Create "good first issue" labels for new examples | 2h |

### Phase 3 Summary

| Metric | Value |
|--------|-------|
| **Examples** | 6 |
| **Community Tasks** | 4 |
| **Total Effort** | 74 hours (~10 days) |
| **Target Release** | v1.6.0 |

---

## File Structure Template

Each example follows this structure:

```
examples/<category>/<example_name>/
├── __init__.py           # Package initialization, exports saga class
├── main.py               # Saga implementation with demo scenarios
├── README.md             # Documentation with flow diagram
├── helpers.py            # Optional: simulation/mock helpers
└── test_<example_name>.py    # Unit tests (optional, in tests/ directory)
```

### `__init__.py` Template

```python
"""
<Example Name> Saga Example

<Brief description of the saga and its industry use case.>
"""

from .main import <SagaClassName>

__all__ = ["<SagaClassName>"]
```

### `main.py` Template

```python
"""
<Example Name> Saga

<Detailed description of the saga flow, pivot points, and forward recovery.>

Pivot Step: <step_name>
    <Why this step is irreversible>

Forward Recovery:
    - <Recovery scenario 1>
    - <Recovery scenario 2>
"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.pivot import forward_recovery, RecoveryAction
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class <SagaClassName>(Saga):
    """
    <Detailed docstring with:
    - Description
    - Expected context schema
    - Pivot step explanation
    - Forward recovery strategies>
    """

    saga_name = "<saga-name>"

    # === REVERSIBLE ZONE ===
    
    @action("<step_1>")
    async def step_1(self, ctx: SagaContext) -> dict[str, Any]:
        """<Step description>."""
        logger.info(f"<emoji> <Action description>")
        await asyncio.sleep(0.1)
        return {"key": "value"}

    @compensate("<step_1>")
    async def compensate_step_1(self, ctx: SagaContext) -> None:
        """<Compensation description>."""
        logger.warning(f"<emoji> <Compensation description>")
        await asyncio.sleep(0.1)

    # === PIVOT STEP ===
    
    @action("<pivot_step>", depends_on=["<previous_step>"], pivot=True)
    async def pivot_step(self, ctx: SagaContext) -> dict[str, Any]:
        """
        🔒 PIVOT STEP: <Why this is point of no return>
        
        Once this step completes, all ancestors are tainted and
        forward recovery is used for subsequent failures.
        """
        logger.info(f"🔒 <Pivot action description>")
        await asyncio.sleep(0.2)
        return {"pivot_result": "value"}

    # === COMMITTED ZONE (Forward Recovery Only) ===
    
    @action("<post_pivot_step>", depends_on=["<pivot_step>"])
    async def post_pivot_step(self, ctx: SagaContext) -> dict[str, Any]:
        """<Post-pivot step description>."""
        logger.info(f"<emoji> <Action description>")
        await asyncio.sleep(0.1)
        return {"key": "value"}

    @forward_recovery("<post_pivot_step>")
    async def recover_post_pivot(
        self, ctx: SagaContext, error: Exception
    ) -> RecoveryAction:
        """
        Forward recovery for post-pivot failures.
        
        Strategies:
        1. RETRY - <When to retry>
        2. RETRY_WITH_ALTERNATE - <When to use alternate>
        3. MANUAL_INTERVENTION - <When to escalate>
        """
        retry_count = ctx.get("retry_count", 0)
        
        if retry_count < 3:
            ctx.set("retry_count", retry_count + 1)
            return RecoveryAction.RETRY
            
        if self._has_alternate_path(ctx):
            return RecoveryAction.RETRY_WITH_ALTERNATE
            
        return RecoveryAction.MANUAL_INTERVENTION


async def main():
    """Run the <example_name> saga demo."""
    print("=" * 80)
    print("<Example Title>")
    print("=" * 80)

    saga = <SagaClassName>()

    # Scenario 1: Successful execution
    print("\n🟢 Scenario 1: Successful Execution")
    print("-" * 80)

    result = await saga.run({
        # Context data
    })

    print(f"\n{'✅' if result.get('saga_id') else '❌'} Result:")
    print(f"   Saga ID: {result.get('saga_id')}")

    # Scenario 2: Pre-pivot failure (rollback)
    print("\n\n🟡 Scenario 2: Pre-Pivot Failure (Full Rollback)")
    print("-" * 80)
    # ...

    # Scenario 3: Post-pivot failure (forward recovery)
    print("\n\n🔴 Scenario 3: Post-Pivot Failure (Forward Recovery)")
    print("-" * 80)
    # ...


if __name__ == "__main__":
    asyncio.run(main())
```

### `README.md` Template

```markdown
# <Example Name> Saga

**Category:** <Category>  
**Pivot Type:** <Pivot Type>

## Description

<Detailed description of the saga and its real-world application.>

## Saga Flow

```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ <step_1>          │ ──→ │ <step_2>        │ ──→ │ <step_3>            │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐
│ <pivot_step>                │ ──→ │ <post_pivot_step>     │
│ 🔒 PIVOT (<why>)            │     │ (forward only)        │
└─────────────────────────────┘     └───────────────────────┘
```

## Pivot Step: `<pivot_step>`

<Explanation of why this step is the point of no return.>

### Why It's Irreversible

- <Reason 1>
- <Reason 2>

### What Happens After Pivot

- <Consequence 1>
- <Consequence 2>

## Forward Recovery Strategies

| Scenario | Strategy | Action |
|----------|----------|--------|
| <Scenario 1> | RETRY | <Action> |
| <Scenario 2> | RETRY_WITH_ALTERNATE | <Action> |
| <Scenario 3> | MANUAL_INTERVENTION | <Action> |

## Usage

\`\`\`python
from examples.<category>.<example_name> import <SagaClassName>

saga = <SagaClassName>()

result = await saga.run({
    # Context data
})
\`\`\`

## Context Schema

| Field | Type | Description |
|-------|------|-------------|
| <field_1> | <type> | <description> |
| <field_2> | <type> | <description> |

## Running the Example

\`\`\`bash
sagaz examples run <category>/<example_name>
\`\`\`
```

---

## Testing Strategy

### Unit Test Template

```python
"""Tests for <Example Name> Saga."""

import pytest

from examples.<category>.<example_name> import <SagaClassName>


class Test<SagaClassName>:
    """Test suite for <SagaClassName>."""

    @pytest.fixture
    def saga(self):
        """Create saga instance."""
        return <SagaClassName>()

    @pytest.fixture
    def valid_context(self):
        """Create valid context for saga."""
        return {
            # Valid context data
        }

    @pytest.mark.asyncio
    async def test_successful_execution(self, saga, valid_context):
        """Test successful saga execution."""
        result = await saga.run(valid_context)
        
        assert result.get("saga_id") is not None
        # Additional assertions

    @pytest.mark.asyncio
    async def test_pre_pivot_failure_triggers_rollback(self, saga, valid_context):
        """Test that pre-pivot failure triggers full rollback."""
        valid_context["simulate_pre_pivot_failure"] = True
        
        with pytest.raises(SagaStepError):
            await saga.run(valid_context)
        
        # Verify rollback occurred

    @pytest.mark.asyncio
    async def test_post_pivot_failure_triggers_forward_recovery(
        self, saga, valid_context
    ):
        """Test that post-pivot failure uses forward recovery."""
        valid_context["simulate_post_pivot_failure"] = True
        
        result = await saga.run(valid_context)
        
        # Verify forward recovery was used
        assert result.get("recovery_action") in ["RETRY", "RETRY_WITH_ALTERNATE"]

    @pytest.mark.asyncio
    async def test_pivot_taints_ancestors(self, saga, valid_context):
        """Test that pivot step taints ancestor steps."""
        result = await saga.run(valid_context)
        
        assert result.get("pivot_reached") is True
        # Verify ancestors are marked as tainted
```

---

## CI/CD Integration

### Example Validation Workflow

```yaml
# .github/workflows/validate-examples.yml
name: Validate Examples

on:
  push:
    paths:
      - 'examples/**'
  pull_request:
    paths:
      - 'examples/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
          
      - name: Run example lint
        run: |
          ruff check examples/
          
      - name: Type check examples
        run: |
          mypy examples/ --ignore-missing-imports
          
      - name: Run example tests
        run: |
          pytest tests/test_examples/ -v
          
      - name: Verify all examples are runnable
        run: |
          python scripts/validate_examples.py
```

---

## Milestones

### Milestone 1: Pivot Feature Complete (v1.3.0)
- [ ] P0-001 through P0-009 complete
- [ ] All existing tests pass
- [ ] Documentation updated

### Milestone 2: Priority Examples Complete (v1.4.0)
- [ ] 6 priority examples implemented
- [ ] All examples have README.md
- [ ] Example validation CI passing
- [ ] Examples accessible via `sagaz examples`

### Milestone 3: Industry Breadth (v1.5.0)
- [ ] 18 total examples implemented
- [ ] All 10 industry categories covered
- [ ] Community contribution guide published

### Milestone 4: Full Coverage (v1.6.0)
- [ ] All 24 examples implemented
- [ ] Example template published
- [ ] "Good first issue" examples identified

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Example Count** | 24 | Count of examples in `examples/` |
| **Test Coverage** | >90% | Codecov report for `examples/` |
| **Documentation** | 100% | All examples have README.md |
| **Runnable** | 100% | `sagaz examples run` works for all |
| **Pivot Demo** | >80% | Examples demonstrating pivot feature |
| **Forward Recovery** | >50% | Examples demonstrating forward recovery |

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Pivot feature delayed | Medium | High | Can implement examples without pivot, add later |
| Example scope creep | High | Medium | Strict template adherence, code review |
| Maintenance burden | Medium | Medium | Automated testing, template updates, community help |
| API changes break examples | Low | High | Examples as integration test targets |

---

## References

- [ADR-026: Industry Examples Expansion Strategy](adr/adr-026-industry-examples-expansion.md)
- [ADR-023: Pivot/Irreversible Steps](adr/adr-023-pivot-irreversible-steps.md)
- [ADR-022: Compensation Result Passing](adr/adr-022-compensation-result-passing.md)
- [Examples README](../../examples/README.md)
