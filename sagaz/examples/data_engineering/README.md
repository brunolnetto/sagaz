# Data Engineering Examples

This directory contains examples demonstrating Sagaz for **data engineering** use cases.

## When to Use Sagaz for Data Engineering

Sagaz is **not** a replacement for traditional data processing tools (Spark, dbt, Pandas). Instead, it excels at **orchestrating transactional workflows** where:

| Scenario | Why Sagaz Helps |
|----------|-----------------|
| **Multi-step pipelines** | Automatic rollback on failure |
| **Cross-system operations** | Coordinate between databases, APIs, storage |
| **Quality gates** | Reject bad data with compensation |
| **Resource cleanup** | Guaranteed cleanup of staging data |
| **Exactly-once processing** | Transactional outbox prevents duplicates |

## Examples

### 1. ETL Pipeline (`etl_pipeline/`)

**Use Case**: Extract data from source, transform with validation, load to warehouse.

**Sagaz Value**:
- Rollback staging tables on transform failure
- Clean up partial loads on warehouse errors
- Audit trail of all ETL operations

```python
# Quick start
from examples.data_engineering.etl_pipeline import ETLPipelineSaga

saga = ETLPipelineSaga()
result = await saga.run({
    "source_table": "raw_events",
    "target_table": "dim_events",
    "batch_date": "2026-01-06",
})
```

### 2. Data Quality Gate (`data_quality_gate/`)

**Use Case**: Validate data quality before loading to production.

**Sagaz Value**:
- Enforce schema, null checks, business rules
- Quarantine bad data automatically
- Rollback load if quality fails post-load

```python
from examples.data_engineering.data_quality_gate import DataQualityGateSaga

saga = DataQualityGateSaga()
result = await saga.run({
    "dataset_path": "/data/incoming/sales.parquet",
    "quality_rules": {
        "null_threshold": 0.05,
        "duplicate_threshold": 0.01,
    },
})
```

### 3. Data Migration (`data_migration/`)

**Use Case**: Migrate data between systems with atomic guarantees.

**Sagaz Value**:
- Export → Transform → Import as atomic unit
- Verify row counts and checksums
- Rollback target on verification failure

```python
from examples.data_engineering.data_migration import DataMigrationSaga

saga = DataMigrationSaga()
result = await saga.run({
    "source_system": "legacy_db",
    "target_system": "new_warehouse",
    "tables": ["customers", "orders", "products"],
})
```

### 4. Lakehouse Ingestion (`lakehouse_ingestion/`)

**Use Case**: Bronze → Silver → Gold medallion architecture.

**Sagaz Value**:
- Layer-by-layer rollback
- Data lineage tracking
- Guaranteed consistency across layers

```python
from examples.data_engineering.lakehouse_ingestion import LakehouseIngestionSaga

saga = LakehouseIngestionSaga()
result = await saga.run({
    "source_path": "s3://raw-bucket/events/",
    "bronze_table": "bronze.raw_events",
    "silver_table": "silver.cleaned_events",
    "gold_table": "gold.event_metrics",
})
```

## Running Examples

```bash
# Run individual examples
python -m examples.data_engineering.etl_pipeline.main
python -m examples.data_engineering.data_quality_gate.main
python -m examples.data_engineering.data_migration.main
python -m examples.data_engineering.lakehouse_ingestion.main

# Or via CLI
sagaz examples run data_engineering/etl_pipeline
sagaz examples run data_engineering/data_quality_gate
```

## Architecture: Sagaz + Data Engineering Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                    Data Platform                                │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────────┐  │
│  │   Airflow     │   │    dbt        │   │   Spark/Flink     │  │
│  │  (Scheduler)  │   │ (Transforms)  │   │  (Processing)     │  │
│  └───────┬───────┘   └───────┬───────┘   └─────────┬─────────┘  │
│          │                   │                     │             │
│          └───────────────────┼─────────────────────┘             │
│                              │                                   │
│                       ┌──────▼──────┐                            │
│                       │   Sagaz     │ ◄── Transaction            │
│                       │  (Sagas)    │     orchestration          │
│                       └──────┬──────┘                            │
│                              │                                   │
│          ┌───────────────────┼───────────────────┐               │
│     ┌────▼────┐        ┌─────▼─────┐       ┌─────▼─────┐         │
│     │ Kafka   │        │ Warehouse │       │ Lakehouse │         │
│     │(Events) │        │(Snowflake)│       │ (Iceberg) │         │
│     └─────────┘        └───────────┘       └───────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

## Key Patterns

### Pattern 1: Staging with Rollback

```python
@action("load_to_staging")
async def load_to_staging(self, ctx):
    staging_table = f"staging_{ctx['batch_id']}"
    # Load data to staging
    return {"staging_table": staging_table}

@compensate("load_to_staging")
async def drop_staging(self, ctx):
    # DROP TABLE staging_xxx
    await drop_table(ctx["staging_table"])
```

### Pattern 2: Quality Gate with Rejection

```python
@action("validate_quality")
async def validate_quality(self, ctx):
    null_ratio = check_nulls(ctx["data"])
    if null_ratio > ctx["null_threshold"]:
        raise SagaStepError(f"Quality check failed: {null_ratio:.1%} nulls")
    return {"quality_passed": True}
```

### Pattern 3: Atomic Swap

```python
@action("swap_tables")
async def swap_tables(self, ctx):
    # RENAME old_table TO old_table_backup
    # RENAME new_table TO old_table
    return {"backup_table": f"{ctx['table']}_backup"}

@compensate("swap_tables")
async def restore_backup(self, ctx):
    # RENAME old_table TO new_table_failed
    # RENAME old_table_backup TO old_table
    pass
```

## Comparison with Alternatives

| Feature | Sagaz | Airflow | dbt |
|---------|-------|---------|-----|
| Automatic rollback | ✅ | ❌ Manual | ❌ Manual |
| Step compensation | ✅ | ❌ | ❌ |
| Transaction guarantees | ✅ | ❌ | ❌ |
| DAG dependencies | ✅ | ✅ | ✅ |
| Scheduling | ❌ | ✅ | ❌ |
| SQL transforms | ❌ | ❌ | ✅ |

**Bottom line**: Use Sagaz **alongside** Airflow/dbt for transactional coordination.

## Related Documentation

- [Transactional Outbox Pattern](../../docs/patterns/optimistic-sending.md)
- [Consumer Inbox (Exactly-Once)](../../docs/patterns/consumer-inbox.md)
- [Dead Letter Queue](../../docs/patterns/dead-letter-queue.md)
