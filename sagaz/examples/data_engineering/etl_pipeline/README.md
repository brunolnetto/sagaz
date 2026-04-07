# ETL Pipeline Saga

Demonstrates Extract-Transform-Load orchestration with automatic rollback capabilities.

## Use Case

Data engineers often need to:
1. Extract data from source systems (APIs, databases, files)
2. Load to staging tables for transformation
3. Apply business logic transformations
4. Validate data quality
5. Load to target warehouse
6. Update metadata catalog

**The Problem**: Traditional ETL leaves orphaned staging data when pipelines fail mid-execution.

**The Solution**: Sagaz automatically compensates (rolls back) each step on failure.

## Pipeline Steps

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Extract    │────▶│ Load Staging │────▶│  Transform   │
│  from Source │     │              │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
                                                 │
┌──────────────┐     ┌──────────────┐     ┌──────▼───────┐
│   Update     │◀────│    Load      │◀────│   Validate   │
│   Catalog    │     │  Warehouse   │     │     Data     │
└──────────────┘     └──────────────┘     └──────────────┘
```

## Compensation Flow

When validation fails:

```
validate_data FAILS
    ↓
log_validation_failure (compensation)
    ↓
drop_transformed_table (compensation)
    ↓
drop_staging_table (compensation)
    ↓
cleanup_extract_files (compensation)
    ↓
Pipeline rolled back cleanly ✅
```

## Running the Example

```bash
# From repository root
python -m examples.data_engineering.etl_pipeline.main

# Or via CLI
sagaz examples run data_engineering/etl_pipeline
```

## Example Output

```
📊 ETL Pipeline Saga - Successful Execution Demo
================================================================================
📥 Extracting from raw_events.clickstream for 2026-01-06
✅ Extracted 45,231 records to /tmp/extract/raw_events.clickstream_2026-01-06.parquet
📤 Loading 45,231 records to staging.etl_20260106_3847
✅ Staging table created: staging.etl_20260106_3847
⚙️ Transforming staging.etl_20260106_3847 with config: {...}
✅ Transformation complete:
   Duplicates removed: 1,234
   Nulls handled: 456
   Output records: 43,541
🔍 Validating staging.etl_20260106_3847_transformed
✅ All validation checks passed
🏭 Loading 43,541 records to warehouse.fact_events
✅ Warehouse load complete: warehouse.fact_events/batch_date=2026-01-06
📚 Updating catalog for warehouse.fact_events
✅ Catalog updated

✅ ETL Pipeline Result:
   Saga ID:            saga-abc123
   Source Records:     45,231
   Transformed Records:43,541
   Loaded Records:     43,541
   Partition:          warehouse.fact_events/batch_date=2026-01-06
   Catalog Updated:    True
```

## Integration with Airflow

```python
from airflow import DAG
from airflow.operators.python import PythonOperator
from examples.data_engineering.etl_pipeline import ETLPipelineSaga


async def run_etl(**context):
    saga = ETLPipelineSaga()
    result = await saga.run({
        "source_table": context["params"]["source"],
        "target_table": context["params"]["target"],
        "batch_date": context["ds"],
    })
    return result


with DAG("etl_with_sagaz", ...) as dag:
    etl_task = PythonOperator(
        task_id="run_etl_saga",
        python_callable=run_etl,
        params={"source": "raw.events", "target": "warehouse.events"},
    )
```

## Key Benefits

| Benefit | Description |
|---------|-------------|
| **Auto-cleanup** | Staging tables dropped on failure |
| **Audit trail** | Full logging of all operations |
| **Reusable** | Same saga for different sources/targets |
| **Type-safe** | Python type hints throughout |
| **Testable** | Mock individual steps for unit tests |
