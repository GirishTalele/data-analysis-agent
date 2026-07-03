"""Integration tests for QVD (QlikView Data) ingestion (Phase 3).

Real FastAPI TestClient, real isolated SQLite DB, real pandas, and — for the
aggregate-question test — the REAL Gemini API (skipped, never stubbed, if no key
is present). The `.qvd` fixture is generated PROGRAMMATICALLY at setup time with
pyqvd's writer (``QvdTable.from_pandas(df).to_qvd(path)``) so no binary blob is
committed; every assertion is checked against an independent read of the same
source data.

Proves:
  1. A QVD single_file dataset uploads -> profiles with row/column/missing counts
     matching an independent pyqvd read, and an aggregate question answers
     correctly via real pandas execution against the QVD-loaded frame.
  2. A QVD + CSV multi_file dataset unions to the summed row count.
"""
from __future__ import annotations

import pandas as pd
import pytest


def _set_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module

    settings_module._settings = None


def _make_qvd_bytes(df: pd.DataFrame, tmp_path, name: str) -> bytes:
    """Write `df` to a real QVD via pyqvd's writer and return its bytes."""
    from pyqvd import QvdTable

    path = tmp_path / name
    QvdTable.from_pandas(df).to_qvd(str(path))
    return path.read_bytes()


@pytest.fixture
def _require_gemini_key():
    from config.settings import get_settings

    if not get_settings().gemini_api_key:
        pytest.skip("No AGENT_GEMINI_API_KEY set in .env — skipping real-Gemini test.")


@pytest.fixture
def qvd_source_df():
    return pd.DataFrame(
        {
            "region": ["North", "South", "North", "East", "West", "South"],
            "amount": [100.0, 200.0, 300.0, None, 150.0, 250.0],
            "units": [1, 2, 3, 4, 5, 6],
        }
    )


def test_qvd_single_file_upload_profiles_correctly(
    api_client, monkeypatch, tmp_path, qvd_source_df
):
    _set_data_dir(monkeypatch, tmp_path)
    content = _make_qvd_bytes(qvd_source_df, tmp_path, "sales.qvd")

    resp = api_client.post(
        "/datasets",
        files={"file": ("sales.qvd", content, "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]

    assert body["dataset"]["kind"] == "single_file"
    profile = body["profile"]

    # Counts match an independent read of the same source data.
    assert profile["row_count"] == len(qvd_source_df)
    assert profile["column_count"] == qvd_source_df.shape[1]

    amount_col = next(c for c in profile["columns"] if c["name"] == "amount")
    assert amount_col["missing_count"] == int(qvd_source_df["amount"].isna().sum())


@pytest.mark.usefixtures("_require_gemini_key")
def test_qvd_aggregate_question_answers_correctly(
    api_client, monkeypatch, tmp_path, qvd_source_df
):
    _set_data_dir(monkeypatch, tmp_path)
    content = _make_qvd_bytes(qvd_source_df, tmp_path, "sales.qvd")

    upload = api_client.post(
        "/datasets",
        files={"file": ("sales.qvd", content, "application/octet-stream")},
    )
    assert upload.status_code == 200, upload.text
    dataset_id = upload.json()["data"]["dataset"]["id"]

    conv = api_client.post(f"/datasets/{dataset_id}/conversations", json={})
    assert conv.status_code == 200, conv.text
    conversation_id = conv.json()["data"]["id"]

    expected_total = round(float(qvd_source_df["amount"].sum()), 2)

    ask = api_client.post(
        f"/conversations/{conversation_id}/messages",
        json={"question": "What is the total amount across all rows?"},
    )
    assert ask.status_code == 200, ask.text
    query_run = ask.json()["data"]["query_run"]

    assert query_run["execution_status"] == "success", query_run
    assert query_run["key_numbers"], "key_numbers should be populated"

    found = any(
        _is_close(v, expected_total) for v in query_run["key_numbers"].values()
    )
    assert found, (
        f"Expected total ~{expected_total} in key_numbers, got "
        f"{query_run['key_numbers']!r} / answer={query_run['answer_text']!r}"
    )


def test_qvd_plus_csv_multifile_unions_row_count(
    api_client, monkeypatch, tmp_path, qvd_source_df
):
    _set_data_dir(monkeypatch, tmp_path)

    # 1) QVD file creates the dataset.
    qvd_bytes = _make_qvd_bytes(qvd_source_df, tmp_path, "part.qvd")
    first = api_client.post(
        "/datasets",
        files={"file": ("part.qvd", qvd_bytes, "application/octet-stream")},
    )
    assert first.status_code == 200, first.text
    dataset_id = first.json()["data"]["dataset"]["id"]
    assert first.json()["data"]["profile"]["row_count"] == len(qvd_source_df)

    # 2) A CSV file is added — the union re-profiles across both.
    csv_df = pd.DataFrame(
        {
            "region": ["North", "West"],
            "amount": [500.0, 600.0],
            "units": [7, 8],
        }
    )
    csv_bytes = csv_df.to_csv(index=False).encode()
    second = api_client.post(
        f"/datasets/{dataset_id}/files",
        files={"file": ("extra.csv", csv_bytes, "text/csv")},
    )
    assert second.status_code == 200, second.text
    body = second.json()["data"]

    assert body["dataset"]["kind"] == "multi_file"
    # The core assertion: unioned row_count == sum of both files' rows.
    assert body["profile"]["row_count"] == len(qvd_source_df) + len(csv_df)


def _is_close(value, target) -> bool:
    try:
        return abs(float(value) - float(target)) < 1.0
    except (TypeError, ValueError):
        return False
