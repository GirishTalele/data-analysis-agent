"""Normalized-alias column detection.

Implements the exact algorithm in `spec/data.md -> Input File Schema`:
headers are normalized identically, then for each canonical field the file's
header row is scanned left to right and the first column whose normalized
name equals one of that field's aliases is selected. Matching is
exact-after-normalization only — no fuzzy/typo tolerance.

GR Value *numeric coercion* (cleaning currency symbols/thousands separators,
`pandas.to_numeric`) is deliberately NOT done here — per
`spec/architecture.md -> Column Detection & Period Derivation`, that logic is
tied to the aggregation formulas and lives in `reporting/aggregate.py`. This
module only detects which column NAME matches each canonical field.
"""

from __future__ import annotations

import re

import pandas as pd

from domain.report import ColumnMapping

# Order of keys matches the field names on ColumnMapping.
_ALIASES: dict[str, tuple[str, ...]] = {
    "plant_column": (
        "plant",
        "plant code",
        "plantcode",
        "location code",
        "location",
        "site",
    ),
    "buyer_column": (
        "buyer",
        "buyer name",
        "customer",
        "customer name",
        "sold to party",
        "soldtoparty",
    ),
    "gr_value_column": (
        "gr value",
        "grvalue",
        "gr amount",
        "value",
        "amount",
        "net value",
        "gr value (inr)",
        "goods receipt value",
    ),
    "period_column": (
        "gr date",
        "posting date",
        "document date",
        "period",
        "date",
    ),
}

_WHITESPACE_RE = re.compile(r"\s+")


def normalize(header: str) -> str:
    """Apply the exact normalization rule from `spec/data.md`.

    normalize(h) = h.strip().lower().replace("_", " ").replace("-", " ")
                   -> collapse repeated internal whitespace to a single space
    """
    cleaned = header.strip().lower().replace("_", " ").replace("-", " ")
    return _WHITESPACE_RE.sub(" ", cleaned)


def detect_columns(df: pd.DataFrame) -> ColumnMapping:
    """Detect the Plant/Buyer/GR Value/Period columns in `df`'s header row."""
    normalized_headers = [(column, normalize(str(column))) for column in df.columns]

    detected: dict[str, str | None] = {}
    for field, aliases in _ALIASES.items():
        detected[field] = None
        for original, normalized in normalized_headers:
            if normalized in aliases:
                detected[field] = original
                break

    return ColumnMapping(**detected)
