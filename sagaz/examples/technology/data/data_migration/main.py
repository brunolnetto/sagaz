"""
Data Migration Saga Example

Demonstrates cross-database migration with atomic guarantees.
Shows how Sagaz handles multi-table migrations with rollback on verification failure.

Key features:
- Export from source system
- Schema transformation
- Import to target system
- Row count and checksum verification
- Automatic rollback on mismatch

Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging

from sagaz.core.exceptions import SagaStepError
from sagaz.examples.technology.data.data_migration.saga import DataMigrationSaga

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def successful_migration_demo():
    """Demonstrate successful data migration."""

    saga = DataMigrationSaga()

    try:
        # Disable checksum verification for reliable "successful" demo
        # (Checksum verification is demonstrated in the failure demo)
        await saga.run(
            {
                "source_system": "legacy_mysql",
                "target_system": "new_postgres",
                "tables": ["customers", "orders", "order_items"],
                "verify_checksums": False,  # Skip for reliable demo
            }
        )

    except SagaStepError:
        pass


async def failed_migration_demo():
    """Demonstrate migration failure with automatic rollback."""

    saga = DataMigrationSaga()

    # Multiple tables increase chance of checksum failure
    for _attempt in range(3):
        try:
            await saga.run(
                {
                    "source_system": "old_warehouse",
                    "target_system": "new_lakehouse",
                    "tables": [
                        "fact_sales",
                        "dim_customers",
                        "dim_products",
                        "dim_dates",
                        "fact_inventory",
                    ],
                    "verify_checksums": True,
                }
            )
        except SagaStepError:
            break


async def main():
    """Run data migration demos."""
    await successful_migration_demo()
    await failed_migration_demo()


if __name__ == "__main__":
    asyncio.run(main())
