# Data Engineering Examples
# -------------------------
# This module contains examples of using Sagaz for data engineering use cases.
#
# Examples:
#   - etl_pipeline: Extract-Transform-Load with automatic rollback
#   - data_quality_gate: Data validation with compensation
#   - data_migration: Cross-database migration saga
#   - lakehouse_ingestion: Bronze/Silver/Gold pipeline

from . import etl_pipeline
from . import data_quality_gate
from . import data_migration
from . import lakehouse_ingestion

__all__ = [
    "etl_pipeline",
    "data_quality_gate",
    "data_migration",
    "lakehouse_ingestion",
]
