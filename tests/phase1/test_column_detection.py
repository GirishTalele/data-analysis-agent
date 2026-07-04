"""Column-detection tests for `ingestion.columns.detect_columns`.

Covers the normalized-alias matching algorithm from
`spec/data.md -> Input File Schema` and the missing-column branch
classifications from `spec/architecture.md -> Error Handling & Reliability
Model`:

- F3 GR_VALUE_COLUMN_MISSING / F5 NO_GROUPING_COLUMN / P1 / P2 / P3 are all
  driven directly by which `ColumnMapping` fields come back `None` — this
  module verifies exactly that classification signal.
- F4 GR_VALUE_UNPARSABLE depends on per-cell numeric coercion, which is
  deliberately NOT implemented in `ingestion.columns` (it lives in
  `reporting.aggregate` per `spec/architecture.md -> Column Detection &
  Period Derivation`). The relevant assertion here is the precondition F4
  needs: when a GR-Value-aliased header is present, detection still resolves
  it to a real column name regardless of what its cells contain -- coercion
  failure is aggregate.py's concern, not this module's.
"""

import pandas as pd

from ingestion.columns import detect_columns, normalize


# --- normalization rule -----------------------------------------------------


def test_normalize_strips_lowercases_and_replaces_separators():
    assert normalize("Plant_Code") == "plant code"
    assert normalize("plant code") == "plant code"
    assert normalize("PLANT   CODE") == "plant code"
    assert normalize("Plant-Code") == "plant code"


def test_normalize_collapses_internal_whitespace():
    assert normalize("Buyer    Name") == "buyer name"
    assert normalize("  GR Value  ") == "gr value"


# --- alias matching across case/underscore/spacing variants ----------------


def test_alias_matching_across_header_variants():
    variants = ["Plant_Code", "plant code", "PLANT   CODE", "Plant-Code"]
    for header in variants:
        df = pd.DataFrame({header: ["1010"], "Buyer": ["b"], "GR Value": [100]})
        mapping = detect_columns(df)
        assert mapping.plant_column == header, f"failed for header variant {header!r}"


def test_all_four_canonical_fields_detected_from_mixed_case_headers():
    df = pd.DataFrame(
        {
            "PLANT_CODE": ["1010"],
            "Buyer Name": ["Acme"],
            "GR_Value": [1000],
            "Posting Date": ["01-01-2026"],
        }
    )
    mapping = detect_columns(df)
    assert mapping.plant_column == "PLANT_CODE"
    assert mapping.buyer_column == "Buyer Name"
    assert mapping.gr_value_column == "GR_Value"
    assert mapping.period_column == "Posting Date"


def test_non_canonical_gr_value_alias_with_currency_suffix():
    df = pd.DataFrame({"GR Value (INR)": [100], "Plant Code": ["1010"]})
    mapping = detect_columns(df)
    assert mapping.gr_value_column == "GR Value (INR)"


def test_location_and_site_aliases_map_to_plant():
    assert detect_columns(pd.DataFrame({"Location Code": ["x"]})).plant_column == "Location Code"
    assert detect_columns(pd.DataFrame({"Site": ["x"]})).plant_column == "Site"


def test_sold_to_party_alias_maps_to_buyer():
    df = pd.DataFrame({"Sold To Party": ["Acme"]})
    assert detect_columns(df).buyer_column == "Sold To Party"


def test_exact_after_normalization_only_no_fuzzy_matching():
    """A near-miss header (typo / partial word) must NOT match — no fuzzy tolerance."""
    df = pd.DataFrame({"Plants": ["1010"], "Buy": ["b"], "GR Val": [1]})
    mapping = detect_columns(df)
    assert mapping.plant_column is None
    assert mapping.buyer_column is None
    assert mapping.gr_value_column is None


def test_first_match_wins_when_multiple_headers_match_same_field():
    df = pd.DataFrame({"Site": ["a"], "Plant": ["b"]})
    mapping = detect_columns(df)
    assert mapping.plant_column == "Site", "leftmost matching header must win"


def test_empty_dataframe_with_headers_only_still_detects_columns():
    df = pd.DataFrame(columns=["Plant Code", "Buyer Name", "GR Value", "Posting Date"])
    mapping = detect_columns(df)
    assert mapping.plant_column == "Plant Code"
    assert mapping.buyer_column == "Buyer Name"
    assert mapping.gr_value_column == "GR Value"
    assert mapping.period_column == "Posting Date"


# --- fatal branch classification: F3 / F5 -----------------------------------


def test_f3_gr_value_column_missing_when_no_header_matches_gr_value_aliases():
    df = pd.DataFrame({"Plant": ["1010"], "Buyer": ["Acme"], "Posting Date": ["01-01-2026"]})
    mapping = detect_columns(df)
    assert mapping.gr_value_column is None


def test_f4_precondition_gr_value_column_still_resolves_regardless_of_cell_content():
    """Detection only inspects header names; unparsable cell values (F4) are
    aggregate.py's concern once the column name itself is resolved here."""
    df = pd.DataFrame({"GR Value": ["not-a-number", "also-bad", "still-bad"]})
    mapping = detect_columns(df)
    assert mapping.gr_value_column == "GR Value"


def test_f5_no_grouping_column_when_neither_plant_nor_buyer_detected():
    df = pd.DataFrame({"GR Value": [100], "Posting Date": ["01-01-2026"]})
    mapping = detect_columns(df)
    assert mapping.plant_column is None
    assert mapping.buyer_column is None
    assert mapping.gr_value_column == "GR Value"


# --- partial branch classification: P1 / P2 / P3 ----------------------------


def test_p1_plant_undetectable_with_buyer_and_gr_value_present():
    df = pd.DataFrame({"Buyer": ["Acme"], "GR Value": [100], "Posting Date": ["01-01-2026"]})
    mapping = detect_columns(df)
    assert mapping.plant_column is None
    assert mapping.buyer_column == "Buyer"
    assert mapping.gr_value_column == "GR Value"


def test_p2_buyer_undetectable_with_plant_and_gr_value_present():
    df = pd.DataFrame({"Plant": ["1010"], "GR Value": [100], "Posting Date": ["01-01-2026"]})
    mapping = detect_columns(df)
    assert mapping.buyer_column is None
    assert mapping.plant_column == "Plant"
    assert mapping.gr_value_column == "GR Value"


def test_p3_period_column_undetectable_with_plant_buyer_and_gr_value_present():
    df = pd.DataFrame({"Plant": ["1010"], "Buyer": ["Acme"], "GR Value": [100]})
    mapping = detect_columns(df)
    assert mapping.period_column is None
    assert mapping.plant_column == "Plant"
    assert mapping.buyer_column == "Buyer"
    assert mapping.gr_value_column == "GR Value"


def test_fully_unrecognizable_header_row_returns_all_none():
    df = pd.DataFrame({"Foo": [1], "Bar": [2], "Baz": [3]})
    mapping = detect_columns(df)
    assert mapping.plant_column is None
    assert mapping.buyer_column is None
    assert mapping.gr_value_column is None
    assert mapping.period_column is None
