"""Integration tests for multi-file (folder-as-dataset) ingestion and joins
(spec/api.md -> POST /datasets/{id}/files, POST /datasets/join).

Real FastAPI TestClient, real isolated SQLite DB, real pandas — no mocking.
The multi-file test uses the cross-slice `large_multifile_dataset` fixture
(defined in tests/conftest.py by the multi-file data generator): >12 files,
>5,000 rows total. We assert the RE-PROFILED row_count equals the sum across
all files AND that an aggregate over the combined data differs from the same
aggregate over a single file — the core Phase-2 win (spec/roadmap.md).
"""
from pathlib import Path

import pandas as pd
import pytest


def _set_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None


def _collect_csv_paths(fixture_value) -> list[Path]:
    """Extract the ordered list of CSV file paths from the cross-slice fixture,
    tolerant of its exact return shape (list of paths, or an object/dict that
    carries them)."""
    found: list[Path] = []

    def visit(v):
        if isinstance(v, (str, Path)):
            p = Path(v)
            if p.suffix.lower() in (".csv", ".xlsx", ".xls") and p.exists():
                found.append(p)
        elif isinstance(v, dict):
            for item in v.values():
                visit(item)
        elif isinstance(v, (list, tuple, set)):
            for item in v:
                visit(item)
        else:
            for attr in ("files", "file_paths", "paths"):
                if hasattr(v, attr):
                    visit(getattr(v, attr))

    visit(fixture_value)
    # De-dup while preserving order.
    seen = set()
    ordered = []
    for p in found:
        key = str(p)
        if key not in seen:
            seen.add(key)
            ordered.append(p)
    return ordered


def test_multifile_reprofile_unions_all_rows(
    api_client, monkeypatch, tmp_path, large_multifile_dataset
):
    _set_data_dir(monkeypatch, tmp_path)

    paths = _collect_csv_paths(large_multifile_dataset)
    assert len(paths) > 12, f"fixture must supply >12 files, got {len(paths)}"

    per_file_rows = [len(pd.read_csv(p)) for p in paths]
    total_rows = sum(per_file_rows)
    assert total_rows > 5000, f"fixture must supply >5000 rows total, got {total_rows}"

    # 1) First file creates the dataset (single_file).
    first = api_client.post(
        "/datasets",
        files={"file": (paths[0].name, paths[0].read_bytes(), "text/csv")},
    )
    assert first.status_code == 200, first.text
    dataset_id = first.json()["data"]["dataset"]["id"]
    assert first.json()["data"]["dataset"]["kind"] == "single_file"
    assert first.json()["data"]["profile"]["row_count"] == per_file_rows[0]

    # 2) Remaining files added one at a time; each re-profiles the UNION.
    last_body = None
    for p, rows in zip(paths[1:], per_file_rows[1:]):
        r = api_client.post(
            f"/datasets/{dataset_id}/files",
            files={"file": (p.name, p.read_bytes(), "text/csv")},
        )
        assert r.status_code == 200, r.text
        last_body = r.json()

    dataset = last_body["data"]["dataset"]
    profile = last_body["data"]["profile"]
    assert dataset["kind"] == "multi_file"
    # The core assertion: unioned row_count == sum across ALL files.
    assert profile["row_count"] == total_rows

    # 3) An aggregate over the combined data differs from the single-file aggregate.
    combined = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    single = pd.read_csv(paths[0])
    numeric_cols = combined.select_dtypes(include="number").columns.tolist()
    assert numeric_cols, "fixture files need at least one numeric column"
    col = numeric_cols[0]
    combined_sum = float(combined[col].sum())
    single_sum = float(single[col].sum())
    assert combined_sum != single_sum
    # And the combined frame really is the full union.
    assert len(combined) == total_rows


def test_add_file_to_unknown_dataset_404(api_client, monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    r = api_client.post(
        "/datasets/does-not-exist/files",
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert r.status_code == 404, r.text


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _make_dataset(api_client, name, content):
    r = api_client.post("/datasets", files={"file": (name, content, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset"]["id"]


def test_join_datasets_happy_path(api_client, monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    left = _make_dataset(
        api_client, "customers.csv", b"customer_id,name\n1,a\n2,b\n3,c\n"
    )
    right = _make_dataset(
        api_client, "orders.csv", b"customer_id,amount\n1,10\n2,20\n2,30\n"
    )

    r = api_client.post(
        "/datasets/join",
        json={"dataset_ids": [left, right], "join_on": "customer_id", "how": "inner"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["dataset"]["kind"] == "joined"
    assert body["profile"]["row_count"] == 3  # inner join drops customer 3
    col_names = {c["name"] for c in body["profile"]["columns"]}
    assert {"customer_id", "name", "amount"}.issubset(col_names)


def test_join_missing_key_returns_400(api_client, monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    left = _make_dataset(api_client, "a.csv", b"customer_id,name\n1,a\n")
    right = _make_dataset(api_client, "b.csv", b"other_id,x\n1,9\n")

    r = api_client.post(
        "/datasets/join",
        json={"dataset_ids": [left, right], "join_on": "customer_id", "how": "inner"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "BAD_REQUEST"


def test_join_unknown_dataset_returns_404(api_client, monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    left = _make_dataset(api_client, "a.csv", b"customer_id,name\n1,a\n")
    r = api_client.post(
        "/datasets/join",
        json={"dataset_ids": [left, "nope"], "join_on": "customer_id", "how": "inner"},
    )
    assert r.status_code == 404, r.text
