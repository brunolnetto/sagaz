# Data Migration Saga

Demonstrates cross-database migration with atomic guarantees and verification.

## Use Case

When migrating data between systems, you need:
1. Backup of target (in case of rollback)
2. Export from source
3. Schema transformation
4. Import to target
5. Verification (row counts, checksums)

**The Problem**: Failed migrations can leave systems in inconsistent states.

**The Solution**: Sagaz ensures atomic migration with automatic rollback.

## Pipeline Steps

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Backup     │────▶│   Export     │────▶│  Transform   │
│   Target     │     │ from Source  │     │   Schema     │
└──────────────┘     └──────────────┘     └──────────────┘
                                                 │
┌──────────────┐     ┌──────────────┐     ┌──────▼───────┐
│   Finalize   │◀────│   Verify     │◀────│   Import     │
│   Migration  │     │  Checksums   │     │  to Target   │
└──────────────┘     └──────────────┘     └──────────────┘
                            ▲
                     ┌──────┴───────┐
                     │    Verify    │
                     │  Row Counts  │
                     └──────────────┘
```

## Compensation Flow

When checksum verification fails:

```
verify_checksums FAILS
    ↓
log_checksum_failure (compensation)
    ↓
log_verification_failure (compensation)
    ↓
rollback_target_import (compensation) ◄── Restore from backup!
    ↓
cleanup_transformed_files (compensation)
    ↓
cleanup_export_files (compensation)
    ↓
cleanup_backup (compensation)
    ↓
Target system restored to pre-migration state ✅
```

## Running the Example

```bash
python -m examples.data_engineering.data_migration.main
```

## Example Output

```
🚀 Data Migration Saga - Successful Migration Demo
================================================================================
💾 Creating backup of target system: new_postgres
   Backing up customers → customers_backup_20260106_143521
   Backing up orders → orders_backup_20260106_143521
   Backing up order_items → order_items_backup_20260106_143521
✅ Backup complete: backup_20260106_143521
📤 Exporting from legacy_mysql
   customers: 45,231 records (checksum: a1b2c3d4)
   orders: 123,456 records (checksum: e5f6g7h8)
   order_items: 456,789 records (checksum: i9j0k1l2)
✅ Export complete: 625,476 total records from 3 tables
🔄 Transforming schema: legacy_mysql → new_postgres
   customers: 3 transformations applied
   orders: 3 transformations applied
   order_items: 3 transformations applied
✅ Schema transformation complete
📥 Importing to new_postgres
   customers: 45,231 records imported
   orders: 123,456 records imported
   order_items: 456,789 records imported
✅ Import complete: 625,476 total records
🔢 Verifying row counts
   ✅ customers: 45,231 ≈ 45,231
   ✅ orders: 123,456 ≈ 123,456
   ✅ order_items: 456,789 ≈ 456,789
✅ All row counts verified
🔐 Verifying data checksums
   ✅ customers: checksums match
   ✅ orders: checksums match
   ✅ order_items: checksums match
✅ All checksums verified
🎉 Finalizing migration
✅ Migration complete: migration_20260106_143522
```

## Key Benefits

| Benefit | Description |
|---------|-------------|
| **Atomic migration** | All tables migrate or none |
| **Automatic backup** | Target backed up before migration |
| **Verification** | Row counts + checksums verified |
| **Full rollback** | Restore from backup on failure |
| **Audit trail** | Complete logging of all steps |
