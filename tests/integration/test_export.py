"""Integration tests for dataset export / derived datasets
(spec/api.md -> POST /datasets/{id}/export, GET /datasets/{id}/derived,
GET /datasets/{id}/derived/{id}/download).

Real FastAPI TestClient, real isolated SQLite DB, real sandbox subprocess
execution of the QueryRun's code (no LLM needed — the code is already stored).
"""
from pathlib import Path

import pandas as pd

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SALES_CSV = FIXTURES_DIR / "sample_sales.csv"


def _set_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None


def _upload(api_client):
    return api_client.post(
        "/datasets",
        files={"file": ("sample_sales.csv", SALES_CSV.read_bytes(), "text/csv")},
    )


def _seed_query_run(dataset_id: str, generated_code: str) -> str:
    """Create a Conversation + QueryRun in the (isolated) DB and return the run id."""
    from db.models import Conversation, QueryRun
    from db.session import create_db_session

    with create_db_session() as session:
        conv = Conversation(dataset_id=dataset_id, title="export test")
        session.add(conv)
        session.flush()
        run = QueryRun(
            conversation_id=conv.id,
            dataset_id=dataset_id,
            question_text="filter big rows",
            generated_code=generated_code,
            execution_status="success",
        )
        session.add(run)
        session.flush()
        return run.id


def test_export_writes_csv_and_persists_derived(api_client, monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    dataset_id = _upload(api_client).json()["data"]["dataset"]["id"]

    # This code produces a derived (filtered) table — fewer than the 30 source rows.
    run_id = _seed_query_run(dataset_id, "result = df[df['amount'] > 300]")
    expected = pd.read_csv(SALES_CSV)
    expected_rows = int((expected["amount"] > 300).sum())
    assert 0 < expected_rows < len(expected)

    r = api_client.post(
        f"/datasets/{dataset_id}/export",
        json={"query_run_id": run_id, "name": "cleaned_sales.csv"},
    )
    assert r.status_code == 200, r.text
    derived = r.json()["data"]["derived_dataset"]
    assert derived["name"] == "cleaned_sales.csv"
    assert derived["row_count"] == expected_rows
    derived_id = derived["id"]
    assert derived["download_url"] == f"/datasets/{dataset_id}/derived/{derived_id}/download"

    # File actually landed on disk under derived/.
    stored = tmp_path / "datasets" / dataset_id / "derived" / f"{derived_id}.csv"
    assert stored.exists()
    written = pd.read_csv(stored)
    assert len(written) == expected_rows

    # Listing shows it.
    lst = api_client.get(f"/datasets/{dataset_id}/derived")
    assert lst.status_code == 200, lst.text
    items = lst.json()["data"]["derived_datasets"]
    assert any(i["id"] == derived_id for i in items)

    # Download returns the CSV bytes.
    dl = api_client.get(f"/datasets/{dataset_id}/derived/{derived_id}/download")
    assert dl.status_code == 200, dl.text
    assert "text/csv" in dl.headers["content-type"]
    downloaded = pd.read_csv(pd.io.common.BytesIO(dl.content))
    assert len(downloaded) == expected_rows


def test_export_unknown_query_run_404(api_client, monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    dataset_id = _upload(api_client).json()["data"]["dataset"]["id"]
    r = api_client.post(
        f"/datasets/{dataset_id}/export",
        json={"query_run_id": "nope", "name": "x.csv"},
    )
    assert r.status_code == 404, r.text


def test_export_scalar_result_rejected(api_client, monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    dataset_id = _upload(api_client).json()["data"]["dataset"]["id"]
    # A scalar result has no tabular form to export -> 400.
    run_id = _seed_query_run(dataset_id, "result = df['amount'].mean()")
    r = api_client.post(
        f"/datasets/{dataset_id}/export",
        json={"query_run_id": run_id, "name": "scalar.csv"},
    )
    assert r.status_code == 400, r.text


def test_export_unknown_dataset_404(api_client, monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    r = api_client.post(
        "/datasets/does-not-exist/export",
        json={"query_run_id": "whatever", "name": "x.csv"},
    )
    assert r.status_code == 404, r.text


def test_download_unknown_derived_404(api_client, monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    dataset_id = _upload(api_client).json()["data"]["dataset"]["id"]
    r = api_client.get(f"/datasets/{dataset_id}/derived/nope/download")
    assert r.status_code == 404, r.text
