"""
Star-schema model definitions for the sagaz analytics layer.

Classes here are sqldim ``DimensionModel`` / ``FactModel`` subclasses that
define the Silver-layer schema.  They are *never* imported in sagaz core —
the ``sagaz[analytics]`` extra is required.

Bronze layer input (raw dicts from StorageManager):
  - saga records: saga_id, saga_name, status, created_at, updated_at
  - step records: saga_id, step_name, action, outcome, duration_ms, attempt

Silver layer (these models):
  - DimSaga   → one row per saga lifecycle
  - DimStep   → one row per unique step definition per saga type
  - FactExecution → step-grain execution events

Gold layer outputs live in ``sagaz.analytics.queries`` as DuckDB SQL strings.
"""

from __future__ import annotations

from datetime import datetime

from sqldim import DimensionModel, FactModel, Field


class DimSaga(DimensionModel, table=True):
    """One row per saga lifecycle — SCD Type 1 (last-write-wins)."""

    saga_id: str = Field(primary_key=True, natural_key=True)
    saga_name: str = Field()
    status: str = Field()
    created_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)


class DimStep(DimensionModel, table=True):
    """One row per unique (saga_name, step_name) combination."""

    step_key: str = Field(primary_key=True, natural_key=True)  # "{saga_name}::{step_name}"
    saga_name: str = Field()
    step_name: str = Field()
    action: str | None = Field(default=None)


class FactExecution(FactModel, table=True):
    """Step-grain execution event — one row per step execution attempt."""

    id: int | None = Field(default=None, primary_key=True)
    saga_id: str = Field(foreign_key="dim_saga.saga_id")
    step_key: str = Field(foreign_key="dimstep.step_key")
    attempt: int = Field(default=1, measure=True, additive=False)
    duration_ms: float = Field(default=0.0, measure=True)
    outcome: str = Field()  # "success" | "failed" | "compensated"
    executed_at: datetime | None = Field(default=None)
