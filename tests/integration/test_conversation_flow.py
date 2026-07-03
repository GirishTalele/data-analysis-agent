"""Integration tests for the conversation endpoints (spec/api.md).

Real FastAPI TestClient, real isolated SQLite DB, real CSV upload, REAL
Gemini API calls (skipped, never stubbed, if no key is present).
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
        pytest.skip("No AGENT_GEMINI_API_KEY set in .env — skipping real-Gemini integration test.")


def _upload_sales_csv(api_client, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module

    settings_module._settings = None

    content = SALES_CSV.read_bytes()
    return api_client.post(
        "/datasets",
        files={"file": ("sample_sales.csv", content, "text/csv")},
    )


@pytest.mark.usefixtures("_require_gemini_key")
def test_full_conversation_flow_happy_path(api_client, monkeypatch, tmp_path):
    """Upload -> create conversation -> ask a real question -> verify answer
    content, key_numbers, tokens/cost, then GET history and verify totals."""
    upload = _upload_sales_csv(api_client, monkeypatch, tmp_path)
    assert upload.status_code == 200, upload.text
    dataset_id = upload.json()["data"]["dataset"]["id"]

    conv_resp = api_client.post(f"/datasets/{dataset_id}/conversations", json={})
    assert conv_resp.status_code == 200, conv_resp.text
    conv_body = conv_resp.json()["data"]
    assert conv_body["title"] == "Untitled analysis"
    assert conv_body["dataset_id"] == dataset_id
    conversation_id = conv_body["id"]

    expected_total = round(float(pd.read_csv(SALES_CSV)["amount"].sum()), 2)

    ask_resp = api_client.post(
        f"/conversations/{conversation_id}/messages",
        json={"question": "What is the total amount across all rows?"},
    )
    assert ask_resp.status_code == 200, ask_resp.text
    ask_body = ask_resp.json()["data"]

    message = ask_body["message"]
    query_run = ask_body["query_run"]

    assert message["role"] == "assistant"
    assert message["content"]
    assert message["query_run_id"] == query_run["id"]

    assert query_run["execution_status"] == "success"
    assert query_run["generated_code"] and "df" in query_run["generated_code"]
    assert query_run["answer_text"] == message["content"]
    assert query_run["prompt_tokens"] > 0
    assert query_run["completion_tokens"] > 0
    assert query_run["estimated_cost_usd"] > 0
    # INR is display-derived from USD using the echoed rate.
    ask_rate = ask_body["usd_to_inr_rate"]
    assert ask_rate > 0
    assert query_run["estimated_cost_inr"] == pytest.approx(
        round(query_run["estimated_cost_usd"] * ask_rate, 4), abs=1e-9
    )
    assert query_run["step_count"] == 1

    # key_numbers must be populated and contain the real computed total.
    assert query_run["key_numbers"], "key_numbers should be populated"
    found = False
    for value in query_run["key_numbers"].values():
        try:
            if abs(float(value) - expected_total) < 1.0:
                found = True
        except (TypeError, ValueError):
            continue
    assert found, (
        f"Expected total ~{expected_total} to appear in key_numbers, "
        f"got {query_run['key_numbers']!r} / answer={query_run['answer_text']!r}"
    )

    # GET history persisted correctly.
    history_resp = api_client.get(f"/conversations/{conversation_id}/messages")
    assert history_resp.status_code == 200, history_resp.text
    history = history_resp.json()["data"]

    assert history["conversation"]["id"] == conversation_id
    assert history["conversation"]["title"] != "Untitled analysis"  # derived from question
    assert len(history["messages"]) == 2
    assert history["messages"][0]["role"] == "user"
    assert history["messages"][0]["content"] == "What is the total amount across all rows?"
    assert history["messages"][1]["role"] == "assistant"
    assert history["messages"][1]["query_run_id"] == query_run["id"]

    assert history["session_cost_total_usd"] == pytest.approx(
        query_run["estimated_cost_usd"], rel=1e-6
    )
    hist_rate = history["usd_to_inr_rate"]
    assert hist_rate > 0
    assert history["session_cost_total_inr"] == pytest.approx(
        round(history["session_cost_total_usd"] * hist_rate, 4), abs=1e-9
    )
    assert history["session_tokens_total"] == (
        query_run["prompt_tokens"] + query_run["completion_tokens"]
    )


def test_post_message_empty_question_rejected(api_client, monkeypatch, tmp_path):
    """Edge case: an empty/whitespace question is a 400, not run through the graph."""
    upload = _upload_sales_csv(api_client, monkeypatch, tmp_path)
    dataset_id = upload.json()["data"]["dataset"]["id"]
    conv = api_client.post(f"/datasets/{dataset_id}/conversations", json={})
    conversation_id = conv.json()["data"]["id"]

    r = api_client.post(
        f"/conversations/{conversation_id}/messages", json={"question": "   "}
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "BAD_REQUEST"


def test_post_message_unknown_conversation_returns_404(api_client):
    r = api_client.post(
        "/conversations/does-not-exist/messages", json={"question": "hi?"}
    )
    assert r.status_code == 404


def test_post_message_conflicts_when_already_running(api_client, monkeypatch, tmp_path):
    """spec/agent.md -> Concurrency Model: a second question for the same
    conversation while one is already running gets 409, not queued/500."""
    from api import conversations as conversations_module

    upload = _upload_sales_csv(api_client, monkeypatch, tmp_path)
    dataset_id = upload.json()["data"]["dataset"]["id"]
    conv = api_client.post(f"/datasets/{dataset_id}/conversations", json={})
    conversation_id = conv.json()["data"]["id"]

    # Simulate an in-flight run for this conversation without needing a real
    # concurrent request (deterministic, no LLM call required).
    conversations_module._running_conversations.add(conversation_id)
    try:
        r = api_client.post(
            f"/conversations/{conversation_id}/messages",
            json={"question": "What is the total amount?"},
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "CONFLICT"
    finally:
        conversations_module._running_conversations.discard(conversation_id)


@pytest.mark.usefixtures("_require_gemini_key")
def test_post_message_cannot_answer_returns_200_with_explanation(
    api_client, monkeypatch, tmp_path
):
    """A question the data can't answer should degrade gracefully to a 200
    response with execution_status='cannot_answer', never a 500. The
    `generate_code`/`compose_answer` LLM calls are still real — only the
    sandbox's execution outcome is forced (same technique as
    tests/integration/test_pipeline.py), since a capable model may otherwise
    dodge a literally-invalid column reference rather than erroring."""
    import sandbox.executor as executor_module
    from sandbox.executor import ExecutionResult

    upload = _upload_sales_csv(api_client, monkeypatch, tmp_path)
    dataset_id = upload.json()["data"]["dataset"]["id"]
    conv = api_client.post(f"/datasets/{dataset_id}/conversations", json={})
    conversation_id = conv.json()["data"]["id"]

    def _fake_run_code(code, dataset_path, file_type):
        return ExecutionResult(
            result=None, stdout="", error="KeyError: 'nonexistent_column_xyz'"
        )

    monkeypatch.setattr(executor_module, "run_code", _fake_run_code)

    r = api_client.post(
        f"/conversations/{conversation_id}/messages",
        json={
            # An answerable question (the `amount` column exists, so it passes
            # the now-active check_clarity gate) whose sandbox execution is
            # forced to fail — exercising the cannot_answer degradation path.
            "question": "What is the total amount across all rows?"
        },
    )
    assert r.status_code == 200, r.text
    query_run = r.json()["data"]["query_run"]
    assert query_run["execution_status"] in ("cannot_answer", "execution_error")
    assert query_run["answer_text"]
    assert (
        "could not answer" in query_run["answer_text"].lower()
        or "couldn't answer" in query_run["answer_text"].lower()
        or "cannot answer" in query_run["answer_text"].lower()
    )
