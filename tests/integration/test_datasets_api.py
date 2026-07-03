"""Integration tests for the /datasets endpoints (spec/api.md).

Real FastAPI TestClient, real isolated SQLite DB (via the `_isolated_db`
autouse fixture in tests/conftest.py), real file upload — no mocking of
pandas or the DB.
"""
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SALES_CSV = FIXTURES_DIR / "sample_sales.csv"


def _upload_sales_csv(api_client, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    content = SALES_CSV.read_bytes()
    return api_client.post(
        "/datasets",
        files={"file": ("sample_sales.csv", content, "text/csv")},
    )


def test_upload_dataset_success(api_client, monkeypatch, tmp_path):
    r = _upload_sales_csv(api_client, monkeypatch, tmp_path)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None

    dataset = body["data"]["dataset"]
    profile = body["data"]["profile"]

    assert dataset["name"] == "sample_sales.csv"
    assert dataset["kind"] == "single_file"
    assert dataset["status"] == "ready"
    assert dataset["id"]
    assert dataset["created_at"]

    assert profile["row_count"] == 30
    assert profile["column_count"] == 4
    assert profile["generated_at"]
    names = [c["name"] for c in profile["columns"]]
    assert names == ["id", "category", "amount", "quantity"]

    # File actually landed on disk at the canonical path.
    stored_path = tmp_path / "datasets" / dataset["id"] / "original" / "sample_sales.csv"
    assert stored_path.exists()
    assert stored_path.read_bytes() == SALES_CSV.read_bytes()


def test_upload_dataset_oversized_rejected(api_client, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_MAX_UPLOAD_MB", "1")
    import config.settings as settings_module
    settings_module._settings = None

    content = b"id,val\n" + b"1,x\n" * 500_000  # comfortably over 1MB
    r = api_client.post(
        "/datasets",
        files={"file": ("big.csv", content, "text/csv")},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "BAD_FILE"


def test_upload_dataset_wrong_extension_rejected(api_client, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    r = api_client.post(
        "/datasets",
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )
    assert r.status_code == 400, r.text


def test_upload_dataset_corrupt_file_rejected(api_client, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    r = api_client.post(
        "/datasets",
        files={"file": ("broken.xlsx", b"not a real excel file at all", "application/octet-stream")},
    )
    assert r.status_code == 400, r.text


def test_get_dataset_returns_dataset_and_profile(api_client, monkeypatch, tmp_path):
    upload = _upload_sales_csv(api_client, monkeypatch, tmp_path)
    dataset_id = upload.json()["data"]["dataset"]["id"]

    r = api_client.get(f"/datasets/{dataset_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["dataset"]["id"] == dataset_id
    assert body["data"]["profile"]["row_count"] == 30


def test_get_dataset_profile_returns_profile_only(api_client, monkeypatch, tmp_path):
    upload = _upload_sales_csv(api_client, monkeypatch, tmp_path)
    dataset_id = upload.json()["data"]["dataset"]["id"]

    r = api_client.get(f"/datasets/{dataset_id}/profile")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["row_count"] == 30
    assert body["data"]["column_count"] == 4
    assert "dataset" not in body["data"]


def test_get_dataset_unknown_id_returns_404(api_client):
    r = api_client.get("/datasets/does-not-exist")
    assert r.status_code == 404


def test_get_dataset_profile_unknown_id_returns_404(api_client):
    r = api_client.get("/datasets/does-not-exist/profile")
    assert r.status_code == 404
