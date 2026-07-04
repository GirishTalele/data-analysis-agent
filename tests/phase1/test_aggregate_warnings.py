"""Edge-case and error-path coverage for `reporting.aggregate.aggregate`.

Complements `test_aggregation_correctness.py` (the large-scale happy-path
correctness gate) with the P1/P2/P3/P4 warning-text scenarios and the F4
fatal-exception scenario from `spec/architecture.md -> Error Handling &
Reliability Model`, plus the "never applied twice" ₹-Crores conversion rule
and the ₹-symbol/thousands-separator coercion rule from `spec/data.md`.
"""

from __future__ import annotations

import pandas as pd
import pytest

from domain.report import ColumnMapping, LoadedDataset
from reporting.aggregate import (
    WARNING_BUYER_UNDETECTABLE,
    WARNING_PERIOD_UNDETECTABLE,
    WARNING_PLANT_UNDETECTABLE,
    GRValueUnparsableError,
    aggregate,
)


def _dataset(df: pd.DataFrame) -> LoadedDataset:
    return LoadedDataset(dataframe=df, source_filename="test.csv", row_count=len(df))


def test_happy_path_full_mapping_produces_no_warnings() -> None:
    df = pd.DataFrame(
        {
            "Plant": ["1010", "1010", "1020"],
            "Buyer": ["Acme", "Acme", "Beta"],
            "GR Value": [1_00_00_000, 2_00_00_000, 5_00_00_000],
            "GR Date": ["01-01-2026", "15-01-2026", "20-01-2026"],
        }
    )
    mapping = ColumnMapping(
        plant_column="Plant", buyer_column="Buyer", gr_value_column="GR Value", period_column="GR Date"
    )

    result = aggregate(_dataset(df), mapping)

    assert result.warnings == []
    assert result.excluded_row_count == 0
    assert result.period_label == "Jan 2026"
    assert result.plant_totals_crore == {"1010": pytest.approx(3.0), "1020": pytest.approx(5.0)}
    assert result.buyer_totals_crore == {"Beta": pytest.approx(5.0), "Acme": pytest.approx(3.0)}


def test_missing_plant_column_produces_p1_warning_and_none_totals() -> None:
    df = pd.DataFrame(
        {
            "Buyer": ["Acme", "Beta"],
            "GR Value": [1_00_00_000, 2_00_00_000],
            "GR Date": ["01-01-2026", "02-01-2026"],
        }
    )
    mapping = ColumnMapping(plant_column=None, buyer_column="Buyer", gr_value_column="GR Value", period_column="GR Date")

    result = aggregate(_dataset(df), mapping)

    assert result.plant_totals_crore is None
    assert result.buyer_totals_crore is not None
    assert WARNING_PLANT_UNDETECTABLE in result.warnings


def test_missing_buyer_column_produces_p2_warning_and_none_totals() -> None:
    df = pd.DataFrame(
        {
            "Plant": ["1010", "1020"],
            "GR Value": [1_00_00_000, 2_00_00_000],
            "GR Date": ["01-01-2026", "02-01-2026"],
        }
    )
    mapping = ColumnMapping(plant_column="Plant", buyer_column=None, gr_value_column="GR Value", period_column="GR Date")

    result = aggregate(_dataset(df), mapping)

    assert result.buyer_totals_crore is None
    assert result.plant_totals_crore is not None
    assert WARNING_BUYER_UNDETECTABLE in result.warnings


def test_missing_period_column_produces_p3_warning_and_placeholder_label() -> None:
    df = pd.DataFrame(
        {
            "Plant": ["1010", "1020"],
            "Buyer": ["Acme", "Beta"],
            "GR Value": [1_00_00_000, 2_00_00_000],
        }
    )
    mapping = ColumnMapping(plant_column="Plant", buyer_column="Buyer", gr_value_column="GR Value", period_column=None)

    result = aggregate(_dataset(df), mapping)

    assert result.period_label == "Reporting period could not be determined"
    assert WARNING_PERIOD_UNDETECTABLE in result.warnings


def test_unparsable_period_values_also_produce_p3_warning() -> None:
    df = pd.DataFrame(
        {
            "Plant": ["1010", "1020"],
            "Buyer": ["Acme", "Beta"],
            "GR Value": [1_00_00_000, 2_00_00_000],
            "GR Date": ["not-a-date", "also-not-a-date"],
        }
    )
    mapping = ColumnMapping(
        plant_column="Plant", buyer_column="Buyer", gr_value_column="GR Value", period_column="GR Date"
    )

    result = aggregate(_dataset(df), mapping)

    assert result.period_label == "Reporting period could not be determined"
    assert WARNING_PERIOD_UNDETECTABLE in result.warnings


def test_some_rows_with_non_numeric_gr_value_produce_p4_warning_and_are_excluded() -> None:
    df = pd.DataFrame(
        {
            "Plant": ["1010", "1010", "1020"],
            "Buyer": ["Acme", "Acme", "Beta"],
            "GR Value": ["₹1,00,00,000", "not-a-number", "5,00,00,000"],
            "GR Date": ["01-01-2026", "02-01-2026", "03-01-2026"],
        }
    )
    mapping = ColumnMapping(
        plant_column="Plant", buyer_column="Buyer", gr_value_column="GR Value", period_column="GR Date"
    )

    result = aggregate(_dataset(df), mapping)

    assert result.excluded_row_count == 1
    assert any("1 of 3 rows had a non-numeric GR Value" in w for w in result.warnings)
    # The excluded row must never contribute to any total.
    assert result.plant_totals_crore == {"1020": pytest.approx(5.0), "1010": pytest.approx(1.0)}


def test_gr_value_with_currency_symbol_and_thousands_separators_coerces_correctly() -> None:
    df = pd.DataFrame(
        {
            "Plant": ["1010"],
            "Buyer": ["Acme"],
            "GR Value": ["₹1,23,45,678.90"],
            "GR Date": ["01-01-2026"],
        }
    )
    mapping = ColumnMapping(
        plant_column="Plant", buyer_column="Buyer", gr_value_column="GR Value", period_column="GR Date"
    )

    result = aggregate(_dataset(df), mapping)

    assert result.excluded_row_count == 0
    assert result.plant_totals_crore["1010"] == pytest.approx(12345678.90 / 1e7)


def test_all_rows_non_numeric_gr_value_raises_gr_value_unparsable_error() -> None:
    df = pd.DataFrame(
        {
            "Plant": ["1010", "1020"],
            "Buyer": ["Acme", "Beta"],
            "GR Value": ["not-a-number", "also-not-a-number"],
            "GR Date": ["01-01-2026", "02-01-2026"],
        }
    )
    mapping = ColumnMapping(
        plant_column="Plant", buyer_column="Buyer", gr_value_column="GR Value", period_column="GR Date"
    )

    with pytest.raises(GRValueUnparsableError):
        aggregate(_dataset(df), mapping)


def test_multi_month_period_produces_range_label() -> None:
    df = pd.DataFrame(
        {
            "Plant": ["1010", "1020", "1010"],
            "Buyer": ["Acme", "Beta", "Acme"],
            "GR Value": [1_00_00_000, 2_00_00_000, 3_00_00_000],
            "GR Date": ["05-01-2026", "10-03-2026", "20-04-2026"],
        }
    )
    mapping = ColumnMapping(
        plant_column="Plant", buyer_column="Buyer", gr_value_column="GR Value", period_column="GR Date"
    )

    result = aggregate(_dataset(df), mapping)

    assert result.period_label == "Jan 2026 – Apr 2026"


def test_buyer_totals_capped_at_exactly_top_ten() -> None:
    plants = [f"1{i:03d}" for i in range(15)]
    buyers = [f"Buyer-{i:02d}" for i in range(15)]
    values = [float(i + 1) * 1e7 for i in range(15)]
    df = pd.DataFrame(
        {
            "Plant": plants,
            "Buyer": buyers,
            "GR Value": values,
            "GR Date": ["01-01-2026"] * 15,
        }
    )
    mapping = ColumnMapping(
        plant_column="Plant", buyer_column="Buyer", gr_value_column="GR Value", period_column="GR Date"
    )

    result = aggregate(_dataset(df), mapping)

    assert len(result.buyer_totals_crore) == 10
    # Descending order preserved; highest value (Buyer-14) is first.
    assert next(iter(result.buyer_totals_crore)) == "Buyer-14"
