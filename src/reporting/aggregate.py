"""GR Value aggregation: numeric coercion, period derivation, plant/buyer totals.

Implements the exact formulas in `spec/data.md -> GR Value numeric coercion`,
`-> Period derivation`, and `-> Aggregation formulas`. The Rupees-to-Crores
conversion (`value / 1e7`) is applied here, and only here, at the point
`plant_totals_crore` / `buyer_totals_crore` are produced -- every intermediate
sum and the `excluded_row_count` figure stay in raw rupees, per
`spec/architecture.md -> Rupees-Crores Conversion`'s "never applied twice" rule.

Public entry point: `aggregate(dataset, mapping) -> AggregationResult`.

`AggregationResult` is a deliberately intermediate structure -- not the final
`ReportBundle` (see `domain.report.ReportBundle`) -- because this module has
no opinion on chart PNG bytes or the rendered `<table>` HTML string. Those are
produced downstream (charts.py for PNGs; the pipeline/email layer for the
table HTML) from the `plant_totals_crore` / `buyer_totals_crore` dicts this
module returns. Dict iteration order is guaranteed descending-by-value
(Python dicts preserve insertion order, and both totals are inserted in
`sort_values(ascending=False)` order) so downstream consumers never need to
re-sort.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from domain.report import ColumnMapping, LoadedDataset

WARNING_PLANT_UNDETECTABLE = (
    "Plant-wise chart and table could not be generated: no recognizable "
    "Plant column found in the source file."
)
WARNING_BUYER_UNDETECTABLE = (
    "Top-10 Buyer chart could not be generated: no recognizable Buyer "
    "column found in the source file."
)
WARNING_PERIOD_UNDETECTABLE = (
    "Reporting period could not be determined: no recognizable date "
    "column found in the source file."
)
PERIOD_UNAVAILABLE_LABEL = "Reporting period could not be determined"

_BUYER_TOP_N = 10
_CRORE = 1e7


class GRValueUnparsableError(ValueError):
    """Every row failed GR Value numeric coercion. Maps to F4 / GR_VALUE_UNPARSABLE."""


class AggregationResult(BaseModel):
    """Intermediate aggregation output consumed by charts.py and the pipeline.

    `plant_totals_crore` / `buyer_totals_crore` are `None` exactly when the
    corresponding column was undetectable (P1 / P2) -- distinct from an empty
    dict, which would mean the column was detected but produced no groups.
    Both dicts, when present, are already sorted descending by value; the
    buyer dict is already truncated to the top 10.
    """

    plant_totals_crore: dict[str, float] | None = None
    buyer_totals_crore: dict[str, float] | None = None
    period_label: str
    excluded_row_count: int
    warnings: list[str] = Field(default_factory=list)


def _coerce_gr_value(series: pd.Series) -> pd.Series:
    """Strip currency symbols/thousands separators and coerce to numeric.

    Per `spec/data.md -> GR Value numeric coercion`. Unparsable cells become
    `NaN` (not raised) so the caller can count/exclude them.
    """
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("₹", "", regex=False)  # "₹"
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _derive_period_label(df: pd.DataFrame, period_column: str | None) -> tuple[str, bool]:
    """Return (period_label, is_available) per `spec/data.md -> Period derivation`."""
    if period_column is None:
        return PERIOD_UNAVAILABLE_LABEL, False

    parsed = pd.to_datetime(df[period_column], errors="coerce", dayfirst=True).dropna()
    if parsed.empty:
        return PERIOD_UNAVAILABLE_LABEL, False

    min_date, max_date = parsed.min(), parsed.max()
    if min_date.year == max_date.year and min_date.month == max_date.month:
        return f"{min_date:%b %Y}", True
    return f"{min_date:%b %Y} – {max_date:%b %Y}", True


def aggregate(dataset: LoadedDataset, mapping: ColumnMapping) -> AggregationResult:
    """Aggregate GR Value by Plant and by Buyer (top 10), in Rupee Crores.

    Assumes the caller (the pipeline) has already enforced the fatal
    pre-conditions that don't require row-level processing: `mapping.gr_value_column`
    is not `None` (F3) and at least one of `mapping.plant_column` /
    `mapping.buyer_column` is not `None` (F5). This function is responsible
    for the one fatal condition that DOES require row-level processing:

    Raises:
        GRValueUnparsableError: every row fails GR Value numeric coercion (F4).
    """
    if mapping.gr_value_column is None:
        raise ValueError("ColumnMapping.gr_value_column is required for aggregation.")

    df = dataset.dataframe
    gr_value_column = mapping.gr_value_column

    numeric = _coerce_gr_value(df[gr_value_column])
    valid_mask = numeric.notna()
    excluded_row_count = int((~valid_mask).sum())

    if not valid_mask.any():
        raise GRValueUnparsableError(
            f"GR Value column '{gr_value_column}' has no numerically parsable rows."
        )

    work_df = df.loc[valid_mask].copy()
    work_df[gr_value_column] = numeric.loc[valid_mask]

    warnings: list[str] = []
    if excluded_row_count > 0:
        warnings.append(
            f"{excluded_row_count} of {dataset.row_count} rows had a non-numeric "
            "GR Value and were excluded from the totals below."
        )

    plant_totals_crore: dict[str, float] | None = None
    if mapping.plant_column is not None:
        plant_totals_raw = (
            work_df.groupby(mapping.plant_column)[gr_value_column]
            .sum()
            .sort_values(ascending=False)
        )
        plant_totals_crore = {str(k): v for k, v in (plant_totals_raw / _CRORE).items()}
    else:
        warnings.append(WARNING_PLANT_UNDETECTABLE)

    buyer_totals_crore: dict[str, float] | None = None
    if mapping.buyer_column is not None:
        buyer_totals_raw = (
            work_df.groupby(mapping.buyer_column)[gr_value_column]
            .sum()
            .sort_values(ascending=False)
            .head(_BUYER_TOP_N)
        )
        buyer_totals_crore = {str(k): v for k, v in (buyer_totals_raw / _CRORE).items()}
    else:
        warnings.append(WARNING_BUYER_UNDETECTABLE)

    period_label, period_available = _derive_period_label(df, mapping.period_column)
    if not period_available:
        warnings.append(WARNING_PERIOD_UNDETECTABLE)

    return AggregationResult(
        plant_totals_crore=plant_totals_crore,
        buyer_totals_crore=buyer_totals_crore,
        period_label=period_label,
        excluded_row_count=excluded_row_count,
        warnings=warnings,
    )
