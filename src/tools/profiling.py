"""Dataset profiling (spec/architecture.md -> Data Flow step 3, spec/api.md ->
`profile` object).

`profile_file`/`profile_dataframe` produce exactly the structure persisted as
`DatasetProfile.columns_json` (spec/data.md#DatasetProfile) — this is the ONLY
thing the LLM ever sees about a dataset's shape (spec/architecture.md -> Raw-Row
Privacy Boundary). It must never contain raw row data: `sample_values` is capped
to a small handful of distinct non-null values, never the full column.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

# Small handful, per spec/api.md's example ("sample_values": ["2025-01-02"]) and
# the code-generator brief ("first 3-5 distinct non-null values").
SAMPLE_VALUES_LIMIT = 5


class ProfilingError(ValueError):
    """Raised when a file can't be loaded/parsed as a dataframe."""


def load_dataframe(path: str | Path, file_type: str) -> pd.DataFrame:
    """Load a CSV/Excel file into a DataFrame, raising ProfilingError on failure."""
    resolved = Path(path)
    if file_type == "csv":
        reader = pd.read_csv
    elif file_type in ("xlsx", "xls"):
        reader = pd.read_excel
    else:
        raise ProfilingError(f"Unsupported file type '{file_type}'")

    try:
        return reader(resolved)
    except Exception as exc:
        raise ProfilingError(f"Could not read file '{resolved.name}': {exc}") from exc


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Compute the profile dict: {row_count, column_count, columns: [...]}.

    Numeric-only fields (`min`/`max`/`mean`) are `None` for non-numeric columns.
    """
    row_count = int(len(df))
    columns: list[dict[str, Any]] = []

    for col in df.columns:
        series = df[col]
        non_null = series.dropna()

        missing_count = int(series.isna().sum())
        missing_pct = round((missing_count / row_count) * 100, 2) if row_count else 0.0
        unique_count = int(non_null.nunique())

        sample_values = [_to_jsonable(v) for v in non_null.unique()[:SAMPLE_VALUES_LIMIT]]

        col_min: float | str | None = None
        col_max: float | str | None = None
        col_mean: float | None = None

        if pd.api.types.is_numeric_dtype(series):
            if not non_null.empty:
                col_min = float(non_null.min())
                col_max = float(non_null.max())
                col_mean = float(non_null.mean())
        elif pd.api.types.is_datetime64_any_dtype(series):
            if not non_null.empty:
                col_min = str(non_null.min())
                col_max = str(non_null.max())

        columns.append(
            {
                "name": str(col),
                "dtype": str(series.dtype),
                "missing_count": missing_count,
                "missing_pct": missing_pct,
                "unique_count": unique_count,
                "sample_values": sample_values,
                "min": col_min,
                "max": col_max,
                "mean": col_mean,
            }
        )

    return {
        "row_count": row_count,
        "column_count": int(len(df.columns)),
        "columns": columns,
    }


def profile_file(path: str | Path, file_type: str) -> dict[str, Any]:
    """Load a file and compute its profile. Raises ProfilingError on unreadable/corrupt files."""
    df = load_dataframe(path, file_type)
    return profile_dataframe(df)


def _to_jsonable(value: Any) -> Any:
    """Coerce a single sample value (possibly a numpy scalar) to a JSON-safe primitive."""
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
