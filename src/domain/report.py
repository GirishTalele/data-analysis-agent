"""Domain models shared across the GR Report Agent pipeline.

Every model here is transient and in-memory only — see `spec/data.md -> Entities`.
Nothing is ever persisted; each object lives only for the duration of one
`POST /reports/send` request and is garbage-collected once the response is
returned. The pipeline is a strict one-way flow:

    LoadedDataset -> ColumnMapping -> ReportBundle -> SendResult

No entity is re-read or mutated after the next stage consumes it.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class LoadedDataset(BaseModel):
    """The parsed, in-memory representation of one uploaded GR export file."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataframe: pd.DataFrame
    source_filename: str
    row_count: int


class ColumnMapping(BaseModel):
    """Result of normalized-alias column detection against a LoadedDataset.

    Detection is exact-after-normalization only (no fuzzy matching); a `None`
    field means no header cell matched any alias for that canonical field.
    See `spec/data.md -> Input File Schema` for the alias tables and the
    normalization rule.
    """

    plant_column: str | None = None
    buyer_column: str | None = None
    gr_value_column: str | None = None
    period_column: str | None = None


class ReportBundle(BaseModel):
    """The fully-computed report, ready for email composition."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    plant_chart_png: bytes | None = None
    plant_table_html: str | None = None
    buyer_chart_png: bytes | None = None
    period_label: str
    excluded_row_count: int
    warnings: list[str] = Field(default_factory=list)


class SendResult(BaseModel):
    """Returned by the pipeline to the API layer on a successful send.

    Fatal outcomes never produce a `SendResult` — they raise a typed
    exception instead (see `spec/architecture.md -> Error Handling & Reliability Model`).
    """

    status: Literal["sent"] = "sent"
    source_filename: str
    period: str
    recipients_sent: list[str] = Field(default_factory=list)
    recipients_rejected: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
