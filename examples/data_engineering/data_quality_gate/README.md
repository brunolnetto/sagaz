# Data Quality Gate Saga

Demonstrates data validation pipeline with automatic rejection and quarantine.

## Use Case

Before loading data to production systems, you need to validate:
1. Schema compatibility
2. Null values in required fields
3. Duplicate records
4. Business rule compliance

**The Problem**: Traditional validation scripts don't handle partial failures well - bad data can slip through.

**The Solution**: Sagaz enforces quality gates with automatic quarantine and rollback.

## Pipeline Steps

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Ingest to  │────▶│   Validate   │────▶│    Check     │
│   Landing    │     │    Schema    │     │    Nulls     │
└──────────────┘     └──────────────┘     └──────────────┘
                                                 │
┌──────────────┐     ┌──────────────┐     ┌──────▼───────┐
│   Update     │◀────│   Load to    │◀────│    Check     │
│   Metrics    │     │  Production  │     │  Duplicates  │
└──────────────┘     └──────────────┘     └──────────────┘
                            ▲
                     ┌──────┴───────┐
                     │   Business   │
                     │    Rules     │
                     └──────────────┘
```

## Quality Rules

```python
quality_rules = {
    "null_threshold": 0.05,        # Max 5% nulls
    "duplicate_threshold": 0.01,   # Max 1% duplicates
    "max_violation_ratio": 0.03,   # Max 3% business rule violations
}
```

## Running the Example

```bash
python -m examples.data_engineering.data_quality_gate.main
```

## Example Output (Failure)

```
⚠️  Data Quality Gate Saga - Failure with Quarantine Demo
================================================================================
📥 Ingesting data from /incoming/user_events_messy.parquet to landing zone
✅ Ingested 23,456 records to /landing/20260106_143521
📋 Validating schema against production.user_events
✅ Schema valid: 5 columns match
🔍 Checking nulls in /landing/20260106_143521 (threshold: 1.0%)
❌ Null check failed: 3.45% nulls exceeds 1.0% threshold

Automatic actions taken:
  • Data quarantined for review
  • Quality metrics recorded
  • Landing zone cleaned up
  • No bad data reached production
```

## Integration with Great Expectations

```python
from great_expectations import DataContext
from examples.data_engineering.data_quality_gate import DataQualityGateSaga

class GreatExpectationsGateSaga(DataQualityGateSaga):
    
    @action("validate_with_ge", depends_on=["ingest_to_landing"])
    async def validate_with_ge(self, ctx):
        context = DataContext()
        batch = context.get_batch(ctx["landing_path"])
        results = context.run_validation_operator(
            "action_list_operator",
            assets_to_validate=[batch],
        )
        if not results["success"]:
            raise SagaStepError(f"Great Expectations validation failed: {results}")
        return {"ge_results": results}
```

## Key Benefits

| Benefit | Description |
|---------|-------------|
| **Early termination** | Fail fast on first quality issue |
| **Automatic quarantine** | Bad data isolated for review |
| **No partial loads** | All-or-nothing to production |
| **Quality metrics** | Track quality score over time |
| **Audit trail** | Full logging of all validation steps |
