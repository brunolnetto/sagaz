"""
Star-schema model definitions for the sagaz analytics layer.

Classes here are sqldim ``DimensionModel`` / ``FactModel`` subclasses that
define the Silver-layer schema.  They are *never* imported in sagaz core —
the ``sagaz[analytics]`` extra is required.

Bronze layer input (raw dicts from StorageManager):
  - saga records: saga_id, saga_name, status, created_at, updated_at
  - step records: saga_id, step_name, action, outcome, duration_ms, attempt

Silver layer (these models):
  - DimSaga            → one row per saga lifecycle (SCD Type 1)
  - DimStep            → one row per unique step definition per saga type (SCD Type 1)
  - FactExecution      → step-grain transaction fact (one row per step execution attempt)
  - FactSagaLifecycle  → accumulating snapshot (one row per saga, updated at each milestone)

Gold layer outputs live in ``sagaz.analytics.queries`` as DuckDB SQL strings.
"""

from __future__ import annotations

from datetime import datetime

from sqldim import AccumulatingFact, DimensionModel, Field, TransactionFact


class DimSaga(DimensionModel, table=True):
    """One row per saga lifecycle — SCD Type 1 (last-write-wins).

    ``__natural_key__`` tells sqldim loaders which column uniquely identifies
    the entity so they can issue upserts without a surrogate-key lookup.
    ``__scd_type__ = 1`` means incoming records overwrite the existing row
    (no history tracking); the latest status is always reflected.
    """

    __natural_key__ = ["saga_id"]
    __scd_type__ = 1

    saga_id: str = Field(primary_key=True)
    saga_name: str = Field()
    status: str = Field()
    created_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)


class DimStep(DimensionModel, table=True):
    """One row per unique (saga_name, step_name) combination — SCD Type 1."""

    __natural_key__ = ["step_key"]
    __scd_type__ = 1

    step_key: str = Field(primary_key=True)  # "{saga_name}::{step_name}"
    saga_name: str = Field()
    step_name: str = Field()
    action: str | None = Field(default=None)


class FactExecution(TransactionFact, table=True):
    """Step-grain transaction fact — one row per step execution attempt.

    ``TransactionFact`` signals that each row is an immutable, point-in-time
    event (Kimball transaction grain).  ``__grain__`` documents the composite
    key that defines one measurement event.
    """

    __grain__ = "step_attempt"  # (saga_id, step_key, attempt) → one row per event

    id: int | None = Field(default=None, primary_key=True)
    saga_id: str = Field(foreign_key="dim_saga.saga_id")
    step_key: str = Field(foreign_key="dim_step.step_key")
    attempt: int = Field(default=1, measure=True, additive=False)
    duration_ms: float = Field(default=0.0, measure=True)
    outcome: str = Field()  # "success" | "failed" | "compensated"
    executed_at: datetime | None = Field(default=None)


class FactSagaLifecycle(AccumulatingFact, table=True):
    """Accumulating snapshot — one row per saga, updated at each milestone.

    ``AccumulatingFact`` (Kimball accumulating snapshot grain) models processes
    that have a well-defined set of milestone dates.  For a saga the milestones
    are: creation, first step execution, completion or rollback.  The row is
    *upserted* each time a new milestone is reached.
    """

    __grain__ = "saga"  # one row per saga_id, updated as milestones are hit

    saga_id: str = Field(primary_key=True, foreign_key="dim_saga.saga_id")
    created_at: datetime | None = Field(default=None)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    rolled_back_at: datetime | None = Field(default=None)
    total_duration_ms: float = Field(default=0.0, measure=True)
    step_count: int = Field(default=0, measure=True, additive=True)
    compensation_count: int = Field(default=0, measure=True, additive=True)
