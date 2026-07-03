"""Pydantic domain model tests for Dataset shapes (spec/api.md)."""
import pytest
from pydantic import ValidationError

from domain.dataset import (
    ColumnProfile,
    DatasetProfileResponse,
    DatasetResponse,
    DatasetWithProfileResponse,
)


def test_dataset_response_matches_api_shape():
    d = DatasetResponse(
        id="uuid-1",
        name="sales_q1.csv",
        kind="single_file",
        status="ready",
        created_at="2026-07-03T00:00:00Z",
    )
    assert d.kind == "single_file"
    assert d.status == "ready"


def test_column_profile_numeric_fields_null_for_non_numeric():
    c = ColumnProfile(
        name="order_date",
        dtype="datetime64",
        missing_count=0,
        missing_pct=0.0,
        unique_count=365,
        sample_values=["2025-01-02"],
        min="2025-01-01",
        max="2025-12-31",
    )
    assert c.mean is None


def test_column_profile_numeric_column_has_stats():
    c = ColumnProfile(
        name="amount",
        dtype="float64",
        missing_count=12,
        missing_pct=0.1,
        min=0.0,
        max=4200.5,
        mean=88.4,
    )
    assert c.mean == 88.4
    assert c.unique_count is None


def test_dataset_with_profile_full_envelope():
    payload = {
        "dataset": {
            "id": "uuid",
            "name": "sales_q1.csv",
            "kind": "single_file",
            "status": "ready",
            "created_at": "2026-07-03T00:00:00Z",
        },
        "profile": {
            "row_count": 12000,
            "column_count": 8,
            "columns": [
                {
                    "name": "amount",
                    "dtype": "float64",
                    "missing_count": 12,
                    "missing_pct": 0.1,
                    "min": 0.0,
                    "max": 4200.5,
                    "mean": 88.4,
                }
            ],
            "generated_at": "2026-07-03T00:00:00Z",
        },
    }
    result = DatasetWithProfileResponse.model_validate(payload)
    assert result.dataset.name == "sales_q1.csv"
    assert result.profile.row_count == 12000
    assert result.profile.columns[0].mean == 88.4


def test_dataset_response_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        DatasetResponse(id="uuid-1", name="x", kind="single_file")  # missing status/created_at


def test_dataset_profile_response_empty_columns_list_is_valid():
    """Edge case: a dataset with zero columns (degenerate upload) is still representable."""
    p = DatasetProfileResponse(
        row_count=0,
        column_count=0,
        columns=[],
        generated_at="2026-07-03T00:00:00Z",
    )
    assert p.columns == []
    assert p.row_count == 0
