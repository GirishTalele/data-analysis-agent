"""Export/derive datasets — Phase 2 (spec/api.md -> POST /datasets/{id}/export,
spec/data.md#DerivedDataset).

Owns the file-writing side of exporting a derived/cleaned dataset produced by a
prior QueryRun's code. The exported CSV is the USER'S OWN data written to their
own local disk under ``data/datasets/<id>/derived/`` — it is never sent to the
LLM, so the raw-row privacy boundary (which governs only LLM-bound payloads) is
respected by construction.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


class ExportError(ValueError):
    """Raised when a QueryRun's result cannot be materialized into a table for export."""


def result_to_dataframe(result: Any) -> pd.DataFrame:
    """Coerce an execution result into a DataFrame suitable for CSV export.

    Handles the shapes a QueryRun's `result` can take: a DataFrame (used as-is),
    a Series (one-column frame), or a dict/list of records. A bare scalar has no
    tabular form to export and raises ExportError.
    """
    if isinstance(result, pd.DataFrame):
        return result
    if isinstance(result, pd.Series):
        return result.to_frame()
    if isinstance(result, dict):
        # dict-of-records vs. a flat {key: value} mapping.
        try:
            return pd.DataFrame(result)
        except ValueError:
            return pd.DataFrame([result])
    if isinstance(result, (list, tuple)):
        return pd.DataFrame(list(result))
    raise ExportError(
        "The selected query produced a single value, not a table, so there is "
        "nothing to export as a dataset. Re-run a query that returns rows/columns."
    )


def write_derived_csv(absolute_path: str | Path, df: pd.DataFrame) -> int:
    """Write `df` to `absolute_path` as CSV, creating parent dirs. Returns row_count."""
    dest = Path(absolute_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    return int(len(df))
