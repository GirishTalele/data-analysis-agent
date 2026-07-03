"""Unit tests for the Phase-2 multi-file helpers in src/tools/storage.py."""
import pandas as pd

from tools.storage import (
    FileSpec,
    combined_csv_cache_path,
    derived_csv_path,
    load_dataset_dataframe,
    resolve_execution_source,
)


def _write_csv(base, dataset_id, name, df):
    d = base / "datasets" / dataset_id / "original"
    d.mkdir(parents=True, exist_ok=True)
    df.to_csv(d / name, index=False)
    return FileSpec(stored_path=f"datasets/{dataset_id}/original/{name}", file_type="csv")


def test_load_dataset_dataframe_concatenates(tmp_path):
    ds = "ds1"
    s1 = _write_csv(tmp_path, ds, "a.csv", pd.DataFrame({"x": [1, 2]}))
    s2 = _write_csv(tmp_path, ds, "b.csv", pd.DataFrame({"x": [3, 4, 5]}))
    combined = load_dataset_dataframe(tmp_path, [s1, s2])
    assert len(combined) == 5
    assert combined["x"].sum() == 15


def test_resolve_execution_source_single_file_passthrough(tmp_path):
    ds = "ds2"
    s1 = _write_csv(tmp_path, ds, "only.csv", pd.DataFrame({"x": [1]}))
    path, ftype = resolve_execution_source(tmp_path, [s1], ds)
    assert path == tmp_path / "datasets" / ds / "original" / "only.csv"
    assert ftype == "csv"


def test_resolve_execution_source_multifile_materializes_combined(tmp_path):
    ds = "ds3"
    s1 = _write_csv(tmp_path, ds, "a.csv", pd.DataFrame({"x": [1, 2]}))
    s2 = _write_csv(tmp_path, ds, "b.csv", pd.DataFrame({"x": [3, 4]}))
    path, ftype = resolve_execution_source(tmp_path, [s1, s2], ds)
    assert path == combined_csv_cache_path(tmp_path, ds)
    assert ftype == "csv"
    assert path.exists()
    assert len(pd.read_csv(path)) == 4
    # The cache must live OUTSIDE original/ so it's never a backing file.
    assert "original" not in path.parts


def test_derived_csv_path_shape(tmp_path):
    abs_path, stored = derived_csv_path(tmp_path, "dsX", "derived9")
    assert abs_path == tmp_path / "datasets" / "dsX" / "derived" / "derived9.csv"
    assert stored == "datasets/dsX/derived/derived9.csv"
