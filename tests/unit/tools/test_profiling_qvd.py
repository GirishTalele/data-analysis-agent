"""Unit tests for QVD (QlikView Data) support in the read path (Phase 3).

QVD is QlikView's proprietary binary columnar format. It is read locally into a
pandas.DataFrame via the pure-Python `pyqvd` reader — no Qlik runtime, no
external service. These tests generate a real `.qvd` fixture PROGRAMMATICALLY at
setup time with pyqvd's writer (``QvdTable.from_pandas(df).to_qvd(path)``), so no
binary blob is committed, and assert it round-trips through `load_dataframe` /
profiling with counts matching an independent pandas read of the source data.
"""
from __future__ import annotations

import pandas as pd
import pytest

from tools.profiling import ProfilingError, load_dataframe, profile_file


def _write_qvd(path, df: pd.DataFrame) -> None:
    """Write `df` to a real QVD file using pyqvd's writer."""
    from pyqvd import QvdTable

    QvdTable.from_pandas(df).to_qvd(str(path))


@pytest.fixture
def sample_qvd(tmp_path):
    """A deterministic source DataFrame + its QVD file on disk.

    Includes a missing value so per-column missing_count is exercised.
    Returns (qvd_path, source_df)."""
    df = pd.DataFrame(
        {
            "region": ["North", "South", "North", "East", "West"],
            "revenue": [100.5, 200.0, 300.0, None, 150.25],
            "units": [1, 2, 3, 4, 5],
        }
    )
    path = tmp_path / "sales.qvd"
    _write_qvd(path, df)
    return path, df


def test_load_dataframe_qvd_roundtrips_shape(sample_qvd):
    path, source_df = sample_qvd
    loaded = load_dataframe(path, "qvd")

    # Row and column counts match an independent read of the same source data.
    assert loaded.shape[0] == source_df.shape[0]
    assert loaded.shape[1] == source_df.shape[1]
    assert list(loaded.columns) == list(source_df.columns)


def test_load_dataframe_qvd_preserves_values_and_missing(sample_qvd):
    path, source_df = sample_qvd
    loaded = load_dataframe(path, "qvd")

    # Missing value survives the round trip (NaN in `revenue`).
    assert loaded["revenue"].isna().sum() == source_df["revenue"].isna().sum() == 1
    assert loaded["units"].tolist() == source_df["units"].tolist()
    assert loaded["region"].tolist() == source_df["region"].tolist()


def test_profile_file_qvd_matches_independent_pandas(sample_qvd):
    path, source_df = sample_qvd
    profile = profile_file(path, "qvd")

    assert profile["row_count"] == len(source_df)
    assert profile["column_count"] == source_df.shape[1]

    revenue_col = next(c for c in profile["columns"] if c["name"] == "revenue")
    assert revenue_col["missing_count"] == int(source_df["revenue"].isna().sum())
    assert revenue_col["mean"] == pytest.approx(float(source_df["revenue"].mean()))


def test_load_dataframe_qvd_corrupt_file_raises_profiling_error(tmp_path):
    bad = tmp_path / "corrupt.qvd"
    bad.write_bytes(b"this is not a real qvd file")
    with pytest.raises(ProfilingError) as excinfo:
        load_dataframe(bad, "qvd")
    # The file name is surfaced, matching the csv/xlsx branch pattern.
    assert "corrupt.qvd" in str(excinfo.value)
