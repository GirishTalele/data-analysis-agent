"""Tests for src/tools/profiling.py (spec/api.md -> `profile` object,
spec/architecture.md -> Raw-Row Privacy Boundary)."""
from pathlib import Path

import pandas as pd
import pytest

from tools.profiling import (
    ProfilingError,
    SAMPLE_VALUES_LIMIT,
    load_dataframe,
    profile_dataframe,
    profile_file,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
SALES_CSV = FIXTURES_DIR / "sample_sales.csv"
MISSING_CSV = FIXTURES_DIR / "sample_with_missing.csv"


def test_profile_file_row_and_column_counts():
    profile = profile_file(SALES_CSV, "csv")
    assert profile["row_count"] == 30
    assert profile["column_count"] == 4
    names = [c["name"] for c in profile["columns"]]
    assert names == ["id", "category", "amount", "quantity"]


def test_profile_file_numeric_column_stats():
    profile = profile_file(SALES_CSV, "csv")
    amount_col = next(c for c in profile["columns"] if c["name"] == "amount")
    assert amount_col["dtype"] == "float64"
    assert amount_col["missing_count"] == 0
    assert amount_col["missing_pct"] == 0.0
    assert amount_col["min"] == pytest.approx(36.27)
    assert amount_col["max"] == pytest.approx(985.37)
    assert amount_col["mean"] is not None


def test_profile_file_non_numeric_column_has_null_numeric_stats():
    profile = profile_file(SALES_CSV, "csv")
    category_col = next(c for c in profile["columns"] if c["name"] == "category")
    assert category_col["min"] is None
    assert category_col["max"] is None
    assert category_col["mean"] is None
    assert category_col["unique_count"] == 4  # south/east/west/north


def test_profile_file_sample_values_never_exceed_limit_and_never_full_column():
    profile = profile_file(SALES_CSV, "csv")
    category_col = next(c for c in profile["columns"] if c["name"] == "category")
    assert len(category_col["sample_values"]) <= SAMPLE_VALUES_LIMIT
    assert len(category_col["sample_values"]) <= 5
    # 30 rows exist for category, but sample_values must never equal the full column.
    assert len(category_col["sample_values"]) < 30


def test_profile_file_missing_counts_and_pct():
    profile = profile_file(MISSING_CSV, "csv")
    amount_col = next(c for c in profile["columns"] if c["name"] == "amount")
    category_col = next(c for c in profile["columns"] if c["name"] == "category")

    assert amount_col["missing_count"] == 1
    assert amount_col["missing_pct"] == pytest.approx(20.0)  # 1/5 * 100
    assert category_col["missing_count"] == 1
    assert category_col["missing_pct"] == pytest.approx(20.0)


def test_profile_dataframe_empty_dataframe_does_not_crash():
    df = pd.DataFrame({"a": pd.Series(dtype="float64"), "b": pd.Series(dtype="object")})
    profile = profile_dataframe(df)
    assert profile["row_count"] == 0
    assert profile["column_count"] == 2
    for col in profile["columns"]:
        assert col["missing_pct"] == 0.0
        assert col["sample_values"] == []


def test_load_dataframe_corrupt_file_raises_profiling_error(tmp_path):
    bad_file = tmp_path / "corrupt.xlsx"
    bad_file.write_bytes(b"this is not a real excel file")
    with pytest.raises(ProfilingError):
        load_dataframe(bad_file, "xlsx")


def test_load_dataframe_unsupported_file_type_raises():
    with pytest.raises(ProfilingError):
        load_dataframe(SALES_CSV, "parquet")
