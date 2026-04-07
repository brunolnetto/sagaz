"""
sagaz.analytics — opt-in analytics pipeline for saga OLTP data.

Install with:  pip install sagaz[analytics]

The pipeline implements a Bronze → Silver → Gold medallion architecture
using DuckDB as the in-process analytical engine and sqldim for star-schema
model definitions.

Public API::

    from sagaz.analytics import SagaAnalyticsPipeline
    from sagaz.analytics.schema import DimSaga, DimStep, FactExecution
    from sagaz.analytics.queries import SagaQueries
"""

from __future__ import annotations

from sagaz.analytics.pipeline import SagaAnalyticsPipeline
from sagaz.analytics.queries import SagaQueries
from sagaz.analytics.schema import DimSaga, DimStep, FactExecution

__all__ = [
    "DimSaga",
    "DimStep",
    "FactExecution",
    "SagaAnalyticsPipeline",
    "SagaQueries",
]
