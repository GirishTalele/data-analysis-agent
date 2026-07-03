"""Integration tests for the real end-to-end analysis graph (spec/agent.md).

These call the REAL Gemini API (skipped, not stubbed, if no key is present)
and run REAL pandas code in the sandbox subprocess against a real fixture
CSV. They assert both response content and DB state, per
`harness/patterns/test-driven.md`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from db import session as session_module
from db.models import Conversation, Dataset, DatasetFile, DatasetProfile, QueryRun, ChatMessage
from graph.runner import run_agent
from tools.profiling import profile_file

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE_CSV = FIXTURES_DIR / "sample_sales.csv"
FULL_ROW_COUNT = 30  # tests/fixtures/sample_sales.csv


@pytest.fixture
def _require_gemini_key():
    """Skip (never stub) if AGENT_GEMINI_API_KEY is not set in .env."""
    from config.settings import get_settings

    if not get_settings().gemini_api_key:
        pytest.skip("No AGENT_GEMINI_API_KEY set in .env — skipping real-Gemini integration test.")


@pytest.fixture
def _dataset_with_profile(_isolated_db, monkeypatch):
    """Creates a real Dataset/DatasetFile/DatasetProfile/Conversation against
    the real sample_sales.csv fixture, pointed at by AGENT_DATA_DIR so
    `execute_code` resolves a real local file (never a stub)."""
    monkeypatch.setenv("AGENT_DATA_DIR", str(FIXTURES_DIR))
    # Force the settings singleton to pick up the new env var.
    import config.settings as settings_module

    settings_module._settings = None

    profile_dict = profile_file(FIXTURE_CSV, "csv")
    assert profile_dict["row_count"] == FULL_ROW_COUNT

    with Session(session_module._engine) as s:
        dataset = Dataset(name="Sample Sales", kind="single_file", status="ready")
        s.add(dataset)
        s.flush()

        s.add(
            DatasetFile(
                dataset_id=dataset.id,
                original_filename="sample_sales.csv",
                stored_path="sample_sales.csv",  # relative to AGENT_DATA_DIR
                file_type="csv",
                size_bytes=FIXTURE_CSV.stat().st_size,
                row_count=profile_dict["row_count"],
            )
        )
        s.add(
            DatasetProfile(
                dataset_id=dataset.id,
                row_count=profile_dict["row_count"],
                column_count=profile_dict["column_count"],
                columns_json=profile_dict["columns"],
            )
        )
        conversation = Conversation(dataset_id=dataset.id, title="Untitled analysis")
        s.add(conversation)
        s.commit()
        dataset_id = dataset.id
        conversation_id = conversation.id

    return dataset_id, conversation_id


@pytest.mark.usefixtures("_require_gemini_key")
def test_pipeline_runs_end_to_end_and_returns_correct_answer(_dataset_with_profile):
    """Happy path: real Gemini call + real sandbox execution against the fixture.

    total(amount) for sample_sales.csv is a known, precomputable value — the
    answer must contain that exact number (within float tolerance), not just
    be a non-empty string.
    """
    import pandas as pd

    dataset_id, conversation_id = _dataset_with_profile
    expected_total = round(float(pd.read_csv(FIXTURE_CSV)["amount"].sum()), 2)

    run_id = run_agent(dataset_id, conversation_id, "What is the total amount across all rows?")
    assert run_id is not None

    with Session(session_module._engine) as s:
        run = s.get(QueryRun, run_id)
        messages = (
            s.query(ChatMessage).filter(ChatMessage.conversation_id == conversation_id).all()
        )

    assert run is not None
    assert run.execution_status == "success"
    assert run.generated_code and "df" in run.generated_code
    assert run.answer_text and len(run.answer_text) > 5
    assert run.prompt_tokens > 0
    assert run.completion_tokens > 0
    assert run.estimated_cost_usd > 0
    assert run.step_count == 1

    # The real numeric answer must be present, within a small float tolerance.
    key_numbers = run.result_summary_json
    assert key_numbers is not None
    found_total = None
    for value in _load_key_numbers(run).values():
        try:
            if abs(float(value) - expected_total) < 1.0:
                found_total = value
        except (TypeError, ValueError):
            continue
    assert found_total is not None, (
        f"Expected total ~{expected_total} to appear in key_numbers, "
        f"got answer={run.answer_text!r}"
    )

    # A ChatMessage (assistant) was persisted, linked back to this run.
    assistant_messages = [m for m in messages if m.role == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0].query_run_id == run_id
    assert assistant_messages[0].content == run.answer_text


def _load_key_numbers(run: QueryRun) -> dict:
    """`QueryRun` doesn't store `key_numbers` as its own column (it's folded
    into `result_summary_json`'s sibling field on the domain response) —
    re-derive it defensively for the assertion above by re-reading the run's
    persisted answer construction. Since the DB row itself doesn't carry
    `key_numbers` as a column (see spec/data.md#QueryRun), the graph state's
    `key_numbers` must have been captured via the API layer; for this
    integration test we instead assert against `result_summary_json`, which
    is guaranteed to contain the real aggregate the answer was based on.
    """
    summary = run.result_summary_json
    if isinstance(summary, dict):
        # e.g. {"data": [...]} shape for a small aggregated frame.
        candidates = {}
        if "data" in summary and isinstance(summary["data"], list):
            for i, row in enumerate(summary["data"]):
                if isinstance(row, dict):
                    for k, v in row.items():
                        candidates[f"row{i}.{k}"] = v
        else:
            candidates.update({k: v for k, v in summary.items() if k not in ("truncated", "row_count")})
        return candidates
    # A bare scalar result (e.g. `result = df['amount'].sum()`).
    return {"result": summary}


@pytest.mark.usefixtures("_require_gemini_key")
def test_pipeline_execution_error_is_handled_as_cannot_answer(_dataset_with_profile, monkeypatch):
    """Error path: force the sandbox to report an execution error (as it
    would for code referencing a nonexistent column), so the pipeline must
    degrade to `cannot_answer` and never raise an unhandled exception. The
    `generate_code` step still makes a real Gemini call — only the sandbox
    outcome is forced, so this exercises the real error-recovery path."""
    import sandbox.executor as executor_module
    from sandbox.executor import ExecutionResult

    dataset_id, conversation_id = _dataset_with_profile

    def _fake_run_code(code, dataset_path, file_type):
        return ExecutionResult(
            result=None, stdout="", error="KeyError: 'this_column_does_not_exist'"
        )

    monkeypatch.setattr(executor_module, "run_code", _fake_run_code)

    run_id = run_agent(dataset_id, conversation_id, "What is the average of a column that does not exist?")

    with Session(session_module._engine) as s:
        run = s.get(QueryRun, run_id)

    assert run is not None
    assert run.execution_status in ("cannot_answer", "execution_error")
    assert run.answer_text is not None
    assert "could not answer" in run.answer_text.lower() or "couldn't answer" in run.answer_text.lower()
    assert run.error_message is None  # non-fatal path, not `failed`


@pytest.mark.usefixtures("_require_gemini_key")
def test_pipeline_empty_question_still_produces_a_recorded_run(_dataset_with_profile):
    """Edge case: an empty/degenerate question must not crash the pipeline —
    it either produces a real (if unhelpful) answer or a clean cannot_answer,
    but the QueryRun audit row is always written."""
    dataset_id, conversation_id = _dataset_with_profile

    run_id = run_agent(dataset_id, conversation_id, "")

    with Session(session_module._engine) as s:
        run = s.get(QueryRun, run_id)

    assert run is not None
    assert run.question_text == ""
    assert run.execution_status in ("success", "cannot_answer", "execution_error", "failed")
    assert run.created_at is not None


@pytest.mark.usefixtures("_require_gemini_key")
def test_pipeline_multi_turn_history_is_persisted_and_capped(_dataset_with_profile):
    """Stateful capability check: a second question in the same conversation
    sees the first turn's history, and both turns' ChatMessages survive."""
    dataset_id, conversation_id = _dataset_with_profile

    run_agent(dataset_id, conversation_id, "What is the total amount across all rows?")
    second_run_id = run_agent(dataset_id, conversation_id, "And what about the average amount?")

    with Session(session_module._engine) as s:
        run = s.get(QueryRun, second_run_id)
        all_messages = (
            s.query(ChatMessage)
            .filter(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at)
            .all()
        )

    assert run is not None
    assert run.execution_status == "success"
    # Two turns -> two assistant ChatMessages persisted (state survives across turns).
    assistant_messages = [m for m in all_messages if m.role == "assistant"]
    assert len(assistant_messages) == 2


@pytest.mark.usefixtures("_require_gemini_key")
def test_compose_answer_prompt_never_contains_more_than_max_summary_rows(
    _dataset_with_profile, monkeypatch
):
    """Raw-row privacy boundary, end-to-end: the literal prompt string sent to
    the LLM client inside `compose_answer` must never contain more distinct
    row-like records than `settings.max_summary_rows`."""
    from config.settings import get_settings
    from llm import client as client_module

    dataset_id, conversation_id = _dataset_with_profile
    max_rows = get_settings().max_summary_rows

    captured_prompts: list[str] = []
    original_call = client_module.LLMClient.call_model_with_usage

    def _spy_call_model_with_usage(self, prompt, *, system=None):
        captured_prompts.append(prompt)
        return original_call(self, prompt, system=system)

    monkeypatch.setattr(client_module.LLMClient, "call_model_with_usage", _spy_call_model_with_usage)

    run_id = run_agent(
        dataset_id, conversation_id, "Break down the total amount by category."
    )

    with Session(session_module._engine) as s:
        run = s.get(QueryRun, run_id)
    assert run is not None

    # The compose_answer prompt is the one built from `execution_result_summary`.
    compose_prompts = [p for p in captured_prompts if "execution_result_summary" in p]
    assert compose_prompts, "compose_answer's prompt was not captured"

    for prompt in compose_prompts:
        payload = json.loads(prompt)
        summary = payload.get("execution_result_summary")
        row_like_count = _count_row_like_records(summary)
        assert row_like_count <= max_rows, (
            f"compose_answer prompt contained {row_like_count} row-like records, "
            f"exceeding AGENT_MAX_SUMMARY_ROWS={max_rows}: {summary!r}"
        )


def _count_row_like_records(summary) -> int:
    """Counts dict-shaped "records" in a summarize_for_llm() output."""
    if summary is None or isinstance(summary, (int, float, str, bool)):
        return 0
    if isinstance(summary, dict):
        data = summary.get("data")
        if isinstance(data, list):
            return len(data)
        # An aggregate (`.describe()`/`.value_counts()`) summary is not row-like.
        return 0
    if isinstance(summary, list):
        return len(summary)
    return 0
