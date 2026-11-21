# Lakehouse Ingestion Saga

Demonstrates the medallion architecture (Bronze → Silver → Gold) with layer-by-layer rollback.

## Use Case

Data lakehouses use a multi-layer architecture:
- **Bronze**: Raw data, exactly as received
- **Silver**: Cleaned, deduplicated, validated
- **Gold**: Aggregated, business-ready analytics

**The Problem**: Failures mid-pipeline can leave orphaned data in intermediate layers.

**The Solution**: Sagaz rolls back each layer in reverse order on failure.

## Medallion Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Data Lakehouse                              │
│                                                                 │
│  ┌────────────┐     ┌────────────┐     ┌────────────┐          │
│  │   BRONZE   │────▶│   SILVER   │────▶│    GOLD    │          │
│  │   (Raw)    │     │  (Clean)   │     │   (Agg)    │          │
│  │            │     │            │     │            │          │
│  │ • As-is    │     │ • Deduped  │     │ • Metrics  │          │
│  │ • +Metadata│     │ • Validated│     │ • KPIs     │          │
│  │ • Append   │     │ • Typed    │     │ • Dims     │          │
│  └────────────┘     └────────────┘     └────────────┘          │
│                                                                 │
│  Compensation:       Compensation:       Compensation:          │
│  Delete partition    Delete partition    Delete partition       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Pipeline Steps

```
Source → [Bronze: Ingest] → [Silver: Clean] → [Gold: Aggregate]
                                                       │
         [Notify] ← [Update Catalog] ←─────────────────┘
```

## Running the Example

```bash
python -m examples.data_engineering.lakehouse_ingestion.main
```

## Example Output

```
🏠 Lakehouse Ingestion Saga - Medallion Architecture Demo
================================================================================
    Bronze (Raw) → Silver (Clean) → Gold (Aggregated)
================================================================================
🥉 BRONZE: Ingesting raw data
   Source: s3://data-lake-raw/events/clickstream/
   Target: bronze.raw_clickstream
✅ BRONZE complete: 145,231 records from 25 files

🥈 SILVER: Processing and cleaning data
   Source: bronze.raw_clickstream
   Target: silver.cleaned_clickstream
   Duplicates removed: 5,234
   Nulls filled: 2,145
   Invalid records removed: 876
✅ SILVER complete: 139,121 records (95.8% retained)

🥇 GOLD: Aggregating for analytics
   Source: silver.cleaned_clickstream
   Target: gold.clickstream_metrics
   Aggregations: ['daily_event_counts', 'hourly_user_activity', ...]
✅ GOLD complete: 1,234 aggregated records

📚 Updating data catalog
   Registered: bronze.raw_clickstream/partition_date=2026-01-06
   Registered: silver.cleaned_clickstream/partition_date=2026-01-06
   Registered: gold.clickstream_metrics/partition_date=2026-01-06
✅ Catalog updated with lineage

📢 Notifying downstream consumers
✅ Notified 3 downstream consumers
```

## Compensation Flow

When Gold aggregation fails:

```
aggregate_to_gold FAILS
    ↓
delete_gold_partition (compensation) - nothing to delete
    ↓
delete_silver_partition (compensation) - 139,121 records removed
    ↓
delete_bronze_partition (compensation) - 145,231 records removed
    ↓
All layers rolled back ✅
```

## Integration with Delta Lake / Iceberg

```python
from delta import DeltaTable
from examples.data_engineering.lakehouse_ingestion import LakehouseIngestionSaga

class DeltaLakehouseSaga(LakehouseIngestionSaga):
    
    @action("process_to_silver", depends_on=["ingest_to_bronze"])
    async def process_to_silver(self, ctx):
        # Use Delta Lake for ACID transactions
        bronze_df = spark.read.format("delta").load(ctx["bronze_path"])
        
        silver_df = (bronze_df
            .dropDuplicates(["event_id"])
            .filter("user_id IS NOT NULL")
            .withColumn("processed_at", current_timestamp()))
        
        silver_df.write.format("delta").mode("overwrite").save(ctx["silver_path"])
        
        return {"silver_record_count": silver_df.count(), ...}
    
    @compensate("process_to_silver")
    async def delete_silver_partition(self, ctx):
        # Delta Lake time travel for rollback
        DeltaTable.forPath(spark, ctx["silver_path"]).restoreToVersion(0)
```

## Key Benefits

| Benefit | Description |
|---------|-------------|
| **Layer consistency** | All layers roll back together |
| **No orphaned data** | Failed ingestions leave no traces |
| **Data lineage** | Track data flow across layers |
| **Quality metrics** | Know exactly what was cleaned |
| **Downstream sync** | Consumers notified only on success |
