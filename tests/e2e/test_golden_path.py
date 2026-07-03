"""Mandatory golden-path test (harness/rules/ai-agents.md Rule 6): walks the
FULL primary user journey end-to-end via TestClient against the real
LLM/API — upload -> profile -> ask -> answer -> history — asserting response
CONTENT, not just status codes.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SALES_CSV = FIXTURES_DIR / "sample_sales.csv"


@pytest.fixture
def _require_gemini_key():
    from config.settings import get_settings

    if not get_settings().gemini_api_key:
        pytest.skip("No AGENT_GEMINI_API_KEY set in .env — skipping real-Gemini golden path test.")


@pytest.mark.usefixtures("_require_gemini_key")
def test_golden_path_upload_profile_ask_answer(api_client, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module

    settings_module._settings = None

    df = pd.read_csv(SALES_CSV)
    expected_row_count = len(df)
    expected_column_count = len(df.columns)
    expected_avg_amount = round(float(df["amount"].mean()), 2)

    # 1. Upload the dataset — assert real profile content.
    upload_resp = api_client.post(
        "/datasets",
        files={"file": ("sample_sales.csv", SALES_CSV.read_bytes(), "text/csv")},
    )
    assert upload_resp.status_code == 200, upload_resp.text
    upload_body = upload_resp.json()["data"]
    dataset_id = upload_body["dataset"]["id"]

    assert upload_body["dataset"]["status"] == "ready"
    assert upload_body["profile"]["row_count"] == expected_row_count
    assert upload_body["profile"]["column_count"] == expected_column_count
    column_names = [c["name"] for c in upload_body["profile"]["columns"]]
    assert column_names == list(df.columns)

    # 2. Re-fetch the dataset + profile independently — must match.
    get_resp = api_client.get(f"/datasets/{dataset_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["data"]["profile"]["row_count"] == expected_row_count

    profile_resp = api_client.get(f"/datasets/{dataset_id}/profile")
    assert profile_resp.status_code == 200, profile_resp.text
    assert profile_resp.json()["data"]["column_count"] == expected_column_count

    # 3. Create a conversation explicitly.
    conv_resp = api_client.post(f"/datasets/{dataset_id}/conversations", json={})
    assert conv_resp.status_code == 200, conv_resp.text
    conversation_id = conv_resp.json()["data"]["id"]
    assert conv_resp.json()["data"]["title"] == "Untitled analysis"

    # 4. Ask a real question — the agent must run real pandas code against the
    #    real file via Gemini and produce a plain-language answer naming the
    #    correct computed number.
    ask_resp = api_client.post(
        f"/conversations/{conversation_id}/messages",
        json={"question": "What is the average order amount?"},
    )
    assert ask_resp.status_code == 200, ask_resp.text
    ask_data = ask_resp.json()["data"]
    query_run = ask_data["query_run"]
    message = ask_data["message"]

    assert query_run["execution_status"] == "success"
    assert query_run["generated_code"]
    assert message["role"] == "assistant"
    assert message["content"]

    # The correct computed average must appear somewhere in the answer or
    # key_numbers (within float tolerance) — proves the real pipeline ran.
    numbers_to_check = [message["content"]]
    key_numbers_values = list((query_run["key_numbers"] or {}).values())
    found = any(
        _approx_in_text(str(expected_avg_amount), text) for text in numbers_to_check
    ) or any(
        isinstance(v, (int, float)) and abs(float(v) - expected_avg_amount) < 1.0
        for v in key_numbers_values
    )
    assert found, (
        f"Expected average ~{expected_avg_amount} in answer={message['content']!r} "
        f"or key_numbers={query_run['key_numbers']!r}"
    )

    # 5. GET the full history — persisted correctly, real cost/token totals.
    history_resp = api_client.get(f"/conversations/{conversation_id}/messages")
    assert history_resp.status_code == 200, history_resp.text
    history = history_resp.json()["data"]
    assert len(history["messages"]) == 2
    assert history["session_tokens_total"] > 0
    assert history["session_cost_total_usd"] > 0


def _approx_in_text(number_str: str, text: str) -> bool:
    """Loose containment check tolerant of formatting (e.g. $, commas)."""
    cleaned_number = number_str.replace(".0", "")
    cleaned_text = text.replace(",", "")
    return number_str in cleaned_text or cleaned_number in cleaned_text
