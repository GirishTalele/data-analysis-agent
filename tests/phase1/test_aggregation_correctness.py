"""The real-data correctness gate for `reporting.aggregate.aggregate`.

Loads `tests/fixtures/gr_export_large.csv` (>= 6,000 rows, >= 6 plants,
>= 40 buyers, a 4-month date range, with an engineered final block that only
makes one specific plant/buyer the true #1 when the FULL file is processed --
a first-N-rows/sampled read reports a different #1). Independently
recomputes plant/buyer totals via `pandas.groupby(...).sum()` directly on the
fixture (bypassing `aggregate()` entirely) and asserts `aggregate()`'s totals
match within `1e-6` relative tolerance, and that its #1 plant/#1 buyer match
the full-data answer specifically -- proving no row-sampling/truncation bug.

If the shared fixture is not present (e.g. this test runs before slice-1's
fixture lands), a self-sufficient fixture of the same documented shape is
generated inline into a temp CSV so this test never hard-blocks on file
ordering between concurrently-authored slices.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from domain.report import ColumnMapping, LoadedDataset
from reporting.aggregate import aggregate

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "gr_export_large.csv"

PLANT_COL = "Plant Code"
BUYER_COL = "Buyer Name"
GR_VALUE_COL = "GR Value (INR)"
PERIOD_COL = "Posting Date"

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(header: str) -> str:
    cleaned = header.strip().lower().replace("_", " ").replace("-", " ")
    return _WHITESPACE_RE.sub(" ", cleaned)


_PLANT_ALIASES = {"plant", "plant code", "plantcode", "location code", "location", "site"}
_BUYER_ALIASES = {"buyer", "buyer name", "customer", "customer name", "sold to party", "soldtoparty"}
_GR_VALUE_ALIASES = {
    "gr value",
    "grvalue",
    "gr amount",
    "value",
    "amount",
    "net value",
    "gr value (inr)",
    "goods receipt value",
}
_PERIOD_ALIASES = {"gr date", "posting date", "document date", "period", "date"}


def _detect_mapping(columns: list[str]) -> ColumnMapping:
    """Self-contained alias detection mirroring `spec/data.md`'s algorithm.

    Deliberately reimplemented here (not imported from `ingestion.columns`)
    so this test stays independent of that module's implementation and truly
    exercises `aggregate()` in isolation against a hand-verified mapping.
    """
    mapping: dict[str, str | None] = {
        "plant_column": None,
        "buyer_column": None,
        "gr_value_column": None,
        "period_column": None,
    }
    alias_sets = {
        "plant_column": _PLANT_ALIASES,
        "buyer_column": _BUYER_ALIASES,
        "gr_value_column": _GR_VALUE_ALIASES,
        "period_column": _PERIOD_ALIASES,
    }
    for field, aliases in alias_sets.items():
        for column in columns:
            if _normalize(str(column)) in aliases:
                mapping[field] = column
                break
    return ColumnMapping(**mapping)


def _generate_fallback_fixture(tmp_path: Path) -> Path:
    """Build a fixture of the documented shape if the shared one is missing.

    6 plants, 40 buyers, 4-month range, >= 6,000 rows, with a ~500-row final
    block engineered so PLANT-6 / Buyer-040 become the true #1 only once the
    full file (including the tail block) is aggregated.
    """
    rng = np.random.default_rng(seed=42)
    plants = [f"PLANT-{i}" for i in range(1, 7)]
    buyers = [f"Buyer-{i:03d}" for i in range(1, 41)]
    target_plant = "PLANT-6"
    target_buyer = "Buyer-040"

    plant_counts = {"PLANT-1": 1200, "PLANT-2": 900, "PLANT-3": 900, "PLANT-4": 900, "PLANT-5": 700, target_plant: 700}
    assert sum(plant_counts.values()) == 5300
    plant_schedule: list[str] = []
    for plant, count in plant_counts.items():
        plant_schedule.extend([plant] * count)
    rng.shuffle(plant_schedule)

    buyer_counts = {"Buyer-001": 300, target_buyer: 50}
    remaining_buyers = [b for b in buyers if b not in buyer_counts]
    remaining_rows = len(plant_schedule) - sum(buyer_counts.values())
    per_buyer = remaining_rows // len(remaining_buyers)
    leftover = remaining_rows - per_buyer * len(remaining_buyers)
    buyer_schedule: list[str] = []
    for b in buyer_counts:
        buyer_schedule.extend([b] * buyer_counts[b])
    for i, b in enumerate(remaining_buyers):
        buyer_schedule.extend([b] * (per_buyer + (1 if i < leftover else 0)))
    rng.shuffle(buyer_schedule)
    assert len(buyer_schedule) == len(plant_schedule)

    dates = pd.date_range("2026-01-01", "2026-04-30", periods=len(plant_schedule))
    background_rows = pd.DataFrame(
        {
            PLANT_COL: plant_schedule,
            BUYER_COL: buyer_schedule,
            GR_VALUE_COL: 100_000.0,
            PERIOD_COL: [d.strftime("%d-%m-%Y") for d in dates],
        }
    )

    block_dates = pd.date_range("2026-04-01", "2026-04-30", periods=500)
    final_block = pd.DataFrame(
        {
            PLANT_COL: target_plant,
            BUYER_COL: target_buyer,
            GR_VALUE_COL: 200_000.0,
            PERIOD_COL: [d.strftime("%d-%m-%Y") for d in block_dates],
        }
    )

    full = pd.concat([background_rows, final_block], ignore_index=True)
    assert len(full) >= 6000

    out_path = tmp_path / "gr_export_large_fallback.csv"
    full.to_csv(out_path, index=False)
    return out_path


@pytest.fixture(scope="module")
def fixture_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if SHARED_FIXTURE.exists():
        return SHARED_FIXTURE
    return _generate_fallback_fixture(tmp_path_factory.mktemp("fixtures"))


def test_fixture_shape_meets_minimum_scale(fixture_path: Path) -> None:
    df = pd.read_csv(fixture_path)
    mapping = _detect_mapping(list(df.columns))

    assert len(df) >= 6000
    assert df[mapping.plant_column].nunique() >= 6
    assert df[mapping.buyer_column].nunique() >= 40

    dates = pd.to_datetime(df[mapping.period_column], dayfirst=True)
    span_months = (dates.max().year - dates.min().year) * 12 + (dates.max().month - dates.min().month) + 1
    assert span_months >= 4


def test_aggregate_matches_independent_pandas_recomputation(fixture_path: Path) -> None:
    df = pd.read_csv(fixture_path)
    mapping = _detect_mapping(list(df.columns))
    assert mapping.gr_value_column is not None
    assert mapping.plant_column is not None
    assert mapping.buyer_column is not None

    dataset = LoadedDataset(dataframe=df, source_filename=fixture_path.name, row_count=len(df))
    result = aggregate(dataset, mapping)

    # Independent recomputation: bypasses aggregate() entirely.
    expected_plant_raw = df.groupby(mapping.plant_column)[mapping.gr_value_column].sum()
    expected_buyer_raw = (
        df.groupby(mapping.buyer_column)[mapping.gr_value_column]
        .sum()
        .sort_values(ascending=False)
        .head(10)
    )

    assert result.plant_totals_crore is not None
    assert result.buyer_totals_crore is not None

    for plant, expected_raw in expected_plant_raw.items():
        expected_crore = expected_raw / 1e7
        actual_crore = result.plant_totals_crore[str(plant)]
        assert math.isclose(actual_crore, expected_crore, rel_tol=1e-6), plant

    for buyer, expected_raw in expected_buyer_raw.items():
        expected_crore = expected_raw / 1e7
        assert str(buyer) in result.buyer_totals_crore, buyer
        actual_crore = result.buyer_totals_crore[str(buyer)]
        assert math.isclose(actual_crore, expected_crore, rel_tol=1e-6), buyer


def test_aggregate_number_one_plant_and_buyer_reflect_full_file_not_a_sample(fixture_path: Path) -> None:
    df = pd.read_csv(fixture_path)
    mapping = _detect_mapping(list(df.columns))

    dataset = LoadedDataset(dataframe=df, source_filename=fixture_path.name, row_count=len(df))
    result = aggregate(dataset, mapping)

    full_top_plant = df.groupby(mapping.plant_column)[mapping.gr_value_column].sum().idxmax()
    full_top_buyer = df.groupby(mapping.buyer_column)[mapping.gr_value_column].sum().idxmax()

    sample_size = min(5000, len(df) - 1)
    sample_df = df.head(sample_size)
    sample_top_plant = sample_df.groupby(mapping.plant_column)[mapping.gr_value_column].sum().idxmax()
    sample_top_buyer = sample_df.groupby(mapping.buyer_column)[mapping.gr_value_column].sum().idxmax()

    # The fixture is engineered so a truncated/sampled read disagrees with the
    # full-file answer -- this is what proves aggregate() processed every row.
    assert full_top_plant != sample_top_plant
    assert full_top_buyer != sample_top_buyer

    actual_top_plant = max(result.plant_totals_crore, key=result.plant_totals_crore.get)
    actual_top_buyer = max(result.buyer_totals_crore, key=result.buyer_totals_crore.get)

    assert actual_top_plant == str(full_top_plant)
    assert actual_top_buyer == str(full_top_buyer)


def test_aggregate_period_label_spans_full_range(fixture_path: Path) -> None:
    df = pd.read_csv(fixture_path)
    mapping = _detect_mapping(list(df.columns))

    dataset = LoadedDataset(dataframe=df, source_filename=fixture_path.name, row_count=len(df))
    result = aggregate(dataset, mapping)

    parsed = pd.to_datetime(df[mapping.period_column], dayfirst=True).dropna()
    min_date, max_date = parsed.min(), parsed.max()
    if min_date.year == max_date.year and min_date.month == max_date.month:
        expected = f"{min_date:%b %Y}"
    else:
        expected = f"{min_date:%b %Y} – {max_date:%b %Y}"

    assert result.period_label == expected
    assert result.warnings == []
    assert result.excluded_row_count == 0
