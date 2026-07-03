"""Unit tests for src/tools/export.py (spec/api.md -> POST /datasets/{id}/export)."""
import pandas as pd
import pytest

from tools.export import ExportError, result_to_dataframe, write_derived_csv


def test_result_to_dataframe_passthrough():
    df = pd.DataFrame({"a": [1, 2]})
    assert result_to_dataframe(df) is df


def test_result_to_dataframe_from_series():
    s = pd.Series([1, 2, 3], name="vals")
    out = result_to_dataframe(s)
    assert isinstance(out, pd.DataFrame)
    assert out.shape == (3, 1)


def test_result_to_dataframe_from_records():
    out = result_to_dataframe([{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    assert list(out.columns) == ["a", "b"]
    assert len(out) == 2


def test_result_to_dataframe_from_flat_dict():
    out = result_to_dataframe({"average": 88.4})
    assert len(out) == 1
    assert out.iloc[0]["average"] == 88.4


def test_result_to_dataframe_scalar_rejected():
    with pytest.raises(ExportError):
        result_to_dataframe(42)


def test_write_derived_csv_creates_file_and_dirs(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    dest = tmp_path / "datasets" / "d1" / "derived" / "x.csv"
    row_count = write_derived_csv(dest, df)
    assert row_count == 2
    assert dest.exists()
    reloaded = pd.read_csv(dest)
    assert list(reloaded.columns) == ["a", "b"]
    assert len(reloaded) == 2
